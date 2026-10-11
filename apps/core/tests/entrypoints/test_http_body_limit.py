"""API admission bounds wire bytes before FastAPI parses a JSON model."""

import asyncio

import anyio
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from thesistrace._http_body import BoundedRequestBody
from thesistrace.entrypoints.http import create_app
from thesistrace.researcher import ResearcherIdentity


class Verifier:
    async def verify(self, cookie):
        return ResearcherIdentity(
            researcher_id="00000000-0000-4000-8000-000000000001",
            email="researcher@example.com", display_label="Researcher",
        )


def test_api_bounds_declared_and_streamed_bytes_before_json_parsing(monkeypatch):
    monkeypatch.setattr("thesistrace.entrypoints.http.CORE_HTTP_MAX_BODY_BYTES", 128, raising=False)
    app = create_app(auth_verifier=Verifier(), public_origin="https://core.test")
    accepted = []

    @app.post("/api/body-probe")
    def probe(value: dict[str, object]):
        accepted.append(value)
        return value

    client = TestClient(app)
    headers = {"origin": "https://core.test", "content-type": "application/json"}
    for content in [b" " * 128 + b"{}", iter([b" " * 64, b" " * 64, b"{}"])]:
        response = client.post("/api/body-probe", content=content, headers=headers)
        assert response.status_code == 413
        assert response.json() == {"detail": "Request exceeds server limit"}
    assert accepted == []
    response = client.post("/api/body-probe", content=b" " * 126 + b"{}", headers=headers)
    assert response.status_code == 200
    assert accepted == [{}]


def test_body_read_timeout_does_not_cancel_oversize_error_response():
    async def run():
        statuses = []

        async def app(scope, receive, send):
            raise AssertionError("oversize body reached the parser")

        async def receive():
            return {"type": "http.request", "body": b"x" * 129, "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                statuses.append(message["status"])
                await anyio.sleep(0.02)

        limiter = BoundedRequestBody(app, max_bytes=128, timeout_seconds=0.01,
            accepts=lambda scope: True,
            error_response=lambda status, detail: JSONResponse({"detail": detail}, status))
        await limiter({"type": "http", "headers": []}, receive, send)
        assert statuses == [413]

    asyncio.run(run())
