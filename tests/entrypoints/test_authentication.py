from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from thesistrace.entrypoints.authentication import (
    AuthSessionUnavailable,
    CoreAuthVerifier,
    CoreHttpSettings,
    InvalidLoginSession,
    InvalidOperatorProof,
    OperatorAccessNotFound,
)
from thesistrace.entrypoints.http import create_app
from thesistrace.researcher import ResearcherIdentity

PUBLIC_ORIGIN = "https://thesistrace.test"
AUTH_ORIGIN = "http://auth:8200"
RESEARCHER_ID = "00000000-0000-4000-8000-000000000041"


def test_core_auth_verifier_forwards_only_cookie_and_parses_exact_identity() -> None:
    captured: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "active": True,
                "display_label": "researcher",
                "email": "researcher@example.com",
                "researcher_id": RESEARCHER_ID,
            },
        )

    verifier = CoreAuthVerifier(
        AUTH_ORIGIN,
        transport=httpx.MockTransport(respond),
    )
    try:
        identity = asyncio.run(
            verifier.verify(
                "thesistrace.session_token=opaque",
            )
        )
    finally:
        asyncio.run(verifier.aclose())

    assert identity == ResearcherIdentity(
        researcher_id=RESEARCHER_ID,
        email="researcher@example.com",
        display_label="researcher",
    )
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert str(request.url) == f"{AUTH_ORIGIN}/internal/session/verify"
    assert request.headers["cookie"] == "thesistrace.session_token=opaque"
    assert "authorization" not in request.headers
    assert request.content == b""


def test_core_auth_verifier_distinguishes_invalid_session_from_auth_failure() -> None:
    captured: list[httpx.Request] = []

    async def invalid(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(401, json={"code": "AUTHENTICATION_REQUIRED"})

    invalid_verifier = CoreAuthVerifier(
        AUTH_ORIGIN,
        transport=httpx.MockTransport(invalid),
    )
    try:
        try:
            asyncio.run(invalid_verifier.verify(None))
        except InvalidLoginSession:
            pass
        else:
            raise AssertionError("invalid Login Session was accepted")
    finally:
        asyncio.run(invalid_verifier.aclose())
    assert len(captured) == 1
    assert "cookie" not in captured[0].headers

    async def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "active": True,
                "display_label": "researcher",
                "email": "researcher@example.com",
                "researcher_id": "not-a-uuid",
                "session_token": "must-not-be-accepted",
            },
        )

    unavailable_verifier = CoreAuthVerifier(
        AUTH_ORIGIN,
        transport=httpx.MockTransport(malformed),
    )
    try:
        try:
            asyncio.run(unavailable_verifier.verify("opaque"))
        except AuthSessionUnavailable:
            pass
        else:
            raise AssertionError("malformed Auth response was accepted")
    finally:
        asyncio.run(unavailable_verifier.aclose())


def test_core_auth_verifier_maps_transport_and_non_401_status_to_unavailable() -> None:
    async def transport_failure(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private auth endpoint")

    for responder in (
        transport_failure,
        _response(503, {"code": "AUTH_SERVICE_UNAVAILABLE"}),
        _response(403, {"code": "unexpected"}),
    ):
        verifier = CoreAuthVerifier(
            AUTH_ORIGIN,
            transport=httpx.MockTransport(responder),
        )
        try:
            try:
                asyncio.run(verifier.verify("opaque"))
            except AuthSessionUnavailable:
                pass
            else:
                raise AssertionError("Auth failure was accepted")
        finally:
            asyncio.run(verifier.aclose())


def test_core_auth_verifier_authorizes_operator_and_consumes_exact_market_proof() -> None:
    captured: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    verifier = CoreAuthVerifier(
        AUTH_ORIGIN,
        transport=httpx.MockTransport(respond),
    )
    try:
        asyncio.run(verifier.authorize_operator("thesistrace.session_token=opaque"))
        asyncio.run(
            verifier.consume_market_refresh_proof(
                "thesistrace.session_token=opaque",
                as_of="2026-08-11T18:00:00+08:00",
                idempotency_key="market-20260811T180000+0800",
                proof="opaque-proof",
            )
        )
        asyncio.run(
            verifier.consume_financial_refresh_proof(
                "thesistrace.session_token=opaque",
                idempotency_key="financial-20260814-custom",
                observation_through_session="2026-08-14",
                proof="opaque-financial-proof",
            )
        )
        asyncio.run(
            verifier.consume_industry_refresh_proof(
                "thesistrace.session_token=opaque",
                idempotency_key="industry-20260814-custom",
                observation_through_session="2026-08-14",
                proof="opaque-industry-proof",
            )
        )
    finally:
        asyncio.run(verifier.aclose())

    assert [(request.method, request.url.path) for request in captured] == [
        ("GET", "/internal/operator/page-access"),
        ("POST", "/internal/operator/proofs/consume"),
        ("POST", "/internal/operator/proofs/consume"),
        ("POST", "/internal/operator/proofs/consume"),
    ]
    assert captured[0].content == b""
    assert captured[1].headers["content-type"] == "application/json"
    assert captured[1].headers["cookie"] == "thesistrace.session_token=opaque"
    assert captured[1].content == (
        b'{"as_of":"2026-08-11T18:00:00+08:00",'
        b'"idempotency_key":"market-20260811T180000+0800",'
        b'"operation":"data.refresh.market.submit","proof":"opaque-proof"}'
    )
    assert captured[2].content == (
        b'{"idempotency_key":"financial-20260814-custom",'
        b'"observation_through_session":"2026-08-14",'
        b'"operation":"data.refresh.financial.submit",'
        b'"proof":"opaque-financial-proof"}'
    )
    assert captured[3].content == (
        b'{"idempotency_key":"industry-20260814-custom",'
        b'"observation_through_session":"2026-08-14",'
        b'"operation":"data.refresh.industry.submit",'
        b'"proof":"opaque-industry-proof"}'
    )


def test_core_auth_verifier_fails_closed_for_operator_rejection() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("page-access"):
            return httpx.Response(404)
        return httpx.Response(400, json={"code": "OPERATOR_PROOF_INVALID"})

    verifier = CoreAuthVerifier(
        AUTH_ORIGIN,
        transport=httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(OperatorAccessNotFound):
            asyncio.run(verifier.authorize_operator("cookie"))
        with pytest.raises(InvalidOperatorProof):
            asyncio.run(
                verifier.consume_market_refresh_proof(
                    "cookie",
                    as_of="2026-08-11T18:00:00+08:00",
                    idempotency_key="market-key",
                    proof="proof",
                )
            )
    finally:
        asyncio.run(verifier.aclose())


def test_core_http_settings_require_two_exact_origins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("THESISTRACE_ENVIRONMENT", "production")
    monkeypatch.setenv("THESISTRACE_AUTH_INTERNAL_ORIGIN", AUTH_ORIGIN)
    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN", PUBLIC_ORIGIN)
    assert CoreHttpSettings.from_environment() == CoreHttpSettings(
        auth_internal_origin=AUTH_ORIGIN,
        public_origin=PUBLIC_ORIGIN,
    )

    for name, value in (
        ("THESISTRACE_AUTH_INTERNAL_ORIGIN", "http://auth:8200/private"),
        ("THESISTRACE_PUBLIC_ORIGIN", "https://user@thesistrace.test"),
        ("THESISTRACE_PUBLIC_ORIGIN", "https://thesistrace.test?secret=value"),
        ("THESISTRACE_PUBLIC_ORIGIN", " https://thesistrace.test"),
        ("THESISTRACE_PUBLIC_ORIGIN", "https://thesistrace.test/"),
        ("THESISTRACE_PUBLIC_ORIGIN", "http://localhost:5173"),
        ("THESISTRACE_PUBLIC_ORIGIN", "https://127.0.0.1"),
    ):
        monkeypatch.setenv(name, value)
        try:
            CoreHttpSettings.from_environment()
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid {name} was accepted")
        monkeypatch.setenv("THESISTRACE_AUTH_INTERNAL_ORIGIN", AUTH_ORIGIN)
        monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN", PUBLIC_ORIGIN)

    monkeypatch.setenv("THESISTRACE_ENVIRONMENT", "invalid")
    try:
        CoreHttpSettings.from_environment()
    except RuntimeError:
        pass
    else:
        raise AssertionError("invalid THESISTRACE_ENVIRONMENT was accepted")


def test_api_middleware_maps_authentication_and_exposes_researcher_context() -> None:
    identity = ResearcherIdentity(
        researcher_id=RESEARCHER_ID,
        email="researcher@example.com",
        display_label="researcher",
    )
    verifier = StubVerifier(identity)
    app = create_app(auth_verifier=verifier, public_origin=PUBLIC_ORIGIN)

    @app.get("/api/test-identity")
    def identity_probe(request: Request) -> dict[str, str]:
        researcher = request.state.researcher
        return {
            "researcher_id": str(researcher.researcher_id),
            "email": researcher.email,
            "display_label": researcher.display_label,
        }

    client = TestClient(app)
    response = client.get(
        "/api/test-identity",
        headers={"cookie": "thesistrace.session_token=opaque"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "researcher_id": RESEARCHER_ID,
        "email": "researcher@example.com",
        "display_label": "researcher",
    }
    assert verifier.cookies == ["thesistrace.session_token=opaque"]
    assert client.get("/health/live").status_code == 200
    assert verifier.cookies == ["thesistrace.session_token=opaque"]


def test_api_middleware_returns_401_or_503_without_entering_route() -> None:
    calls: list[str] = []
    for error, expected_status in (
        (InvalidLoginSession(), 401),
        (AuthSessionUnavailable(), 503),
    ):
        app = create_app(
            auth_verifier=StubVerifier(error),
            public_origin=PUBLIC_ORIGIN,
        )

        @app.get("/api/protected")
        def protected() -> dict[str, bool]:
            calls.append("entered")
            return {"entered": True}

        response = TestClient(app).get("/api/protected")
        assert response.status_code == expected_status
    assert calls == []


def test_api_write_guard_requires_exact_origin_and_json_only_when_body_exists() -> None:
    identity = ResearcherIdentity(
        researcher_id=RESEARCHER_ID,
        email="researcher@example.com",
        display_label="researcher",
    )
    app = create_app(
        auth_verifier=StubVerifier(identity),
        public_origin=PUBLIC_ORIGIN,
    )

    @app.post("/api/write")
    async def write(request: Request) -> dict[str, Any]:
        return await request.json()

    @app.post("/api/bodyless")
    def bodyless() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/api/write", json={"ok": True}).status_code == 403
    assert (
        client.post(
            "/api/write",
            content="{}",
            headers={
                "content-type": "text/plain",
                "origin": PUBLIC_ORIGIN,
            },
        ).status_code
        == 415
    )
    for content_type in ("application/jsonp", "application/jsonevil"):
        assert (
            client.post(
                "/api/write",
                content="{}",
                headers={
                    "content-type": content_type,
                    "origin": PUBLIC_ORIGIN,
                },
            ).status_code
            == 415
        )
    assert (
        client.post(
            "/api/write",
            content="{}",
            headers={
                "content-type": 'application/json; charset="utf-8"',
                "origin": PUBLIC_ORIGIN,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/write",
            content="{}",
            headers={
                "content-type": "Application/JSON; Charset=UTF-8",
                "origin": PUBLIC_ORIGIN,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/write",
            json={"ok": True},
            headers={"origin": "https://attacker.test"},
        ).status_code
        == 403
    )
    assert client.post(
        "/api/write",
        json={"ok": True},
        headers={"origin": PUBLIC_ORIGIN},
    ).json() == {"ok": True}
    assert (
        client.post(
            "/api/bodyless",
            headers={"origin": PUBLIC_ORIGIN},
        ).status_code
        == 200
    )
    assert (
        "access-control-allow-origin"
        not in client.options(
            "/api/write",
            headers={"origin": PUBLIC_ORIGIN},
        ).headers
    )


class StubVerifier:
    def __init__(self, result: ResearcherIdentity | Exception) -> None:
        self._result = result
        self.cookies: list[str | None] = []

    async def verify(self, cookie: str | None) -> ResearcherIdentity:
        self.cookies.append(cookie)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _response(
    status_code: int,
    body: object,
) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return respond
