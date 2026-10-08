from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from thesistrace.entrypoints.authentication import InvalidLoginSession
from thesistrace.entrypoints.http import create_app
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.researcher import ResearcherIdentity


class SessionVerifier:
    async def verify(self, cookie):
        if cookie != "test-session":
            raise InvalidLoginSession()
        return ResearcherIdentity(
            researcher_id=UUID("018f6f7e-8342-7c9a-a4df-9a86147d2e11"),
            email="researcher@example.test", display_label="researcher",
        )


def test_http_serves_the_same_authoring_reference_with_current_query_validation():
    app = create_app(auth_verifier=SessionVerifier(), public_origin="https://core.test",
                     event_sink=lambda _event: None)
    service = ResearchAuthoringService()
    app.state.core_runtime = SimpleNamespace(research_authoring=service)
    client = TestClient(app)
    path = "/api/research/authoring-reference"
    assert client.get(path).status_code == 401
    client.headers["Cookie"] = "test-session"
    for topic, symbol in (("workflow", None), ("formula", "syntax"),
                          ("python_sdk", "Data.history"), ("examples", "direct")):
        params = {"topic": topic, **({"symbol": symbol} if symbol else {})}
        response = client.get(path, params=params)
        assert response.status_code == 200
        assert response.json() == service.reference(topic, symbol).model_dump(mode="json")
    assert client.get(path, params={"topic": "private"}).status_code == 422
    assert client.get(path, params={"symbol": "x" * 101}).status_code == 422
    assert client.get(path, params={"unexpected": "argument"}).status_code == 422
    missing = client.get(path, params={"topic": "python_sdk", "symbol": "unknown"}).json()
    assert missing["found"] is False
    assert missing["entry"] is None
    assert missing["symbols"]
