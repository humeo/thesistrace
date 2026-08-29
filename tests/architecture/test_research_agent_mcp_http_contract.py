from __future__ import annotations

import anyio
import httpx
import pytest
from mcp.server.auth.provider import AccessToken

from thesistrace.entrypoints.http import create_app
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
)
from thesistrace.research_agent.http_server import (
    RESEARCH_AGENT_MAX_HTTP_BODY_FRAMES,
    _BoundedMCPRequestBody,
)
from thesistrace.research_agent.mcp_server import RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES


class _RejectingVerifier:
    async def verify_token(self, _token: str) -> AccessToken | None:
        return None


class _AcceptingVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "valid-token":
            return None
        return AccessToken(
            token=token,
            client_id="codex-development",
            scopes=["research:read"],
            expires_at=None,
            resource="https://core.test/mcp",
            subject="018f6f7e-8342-7c9a-a4df-9a86147d2e01",
        )


def _configuration(**overrides: object) -> ResearchAgentHTTPConfiguration:
    values: dict[str, object] = {
        "token_verifier": _RejectingVerifier(),
        "issuer_url": "https://issuer.test",
        "resource_server_url": "https://core.test/mcp",
        "deployment_tool_allowlist": RESEARCH_AGENT_TOOL_NAMES,
        "allowed_hosts": ("core.test",),
        "allowed_origins": ("https://codex.test",),
    }
    values.update(overrides)
    return ResearchAgentHTTPConfiguration(**values)  # type: ignore[arg-type]


def test_http_mcp_requires_explicit_verifier_configuration_when_enabled() -> None:
    with pytest.raises(ValueError, match="explicitly enabled with a token verifier"):
        create_app(enable_research_agent_http=True)
    with pytest.raises(ValueError, match="explicitly enabled with a token verifier"):
        create_app(research_agent_http=_configuration())
    with pytest.raises(ValueError, match="requires a token verifier"):
        _configuration(token_verifier=None)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"resource_server_url": "https://core.test/mcp/v1"},
            "must end at /mcp",
        ),
        (
            {"issuer_url": "http://issuer.test"},
            "issuer_url must use HTTPS",
        ),
        (
            {"issuer_url": "https://issuer.test/?tenant=example"},
            "issuer_url cannot contain query or fragment",
        ),
        (
            {"issuer_url": "https://issuer.test/#discovery"},
            "issuer_url cannot contain query or fragment",
        ),
        (
            {"resource_server_url": "http://core.test/mcp"},
            "resource_server_url must use HTTPS",
        ),
        (
            {"deployment_tool_allowlist": frozenset({"legacy_tool"})},
            "unknown Research Agent deployment tools",
        ),
        ({"allowed_hosts": ()}, "requires explicit allowed_hosts"),
        ({"allowed_origins": ("",)}, "cannot contain blanks"),
    ],
)
def test_http_mcp_configuration_fails_closed(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _configuration(**overrides)


def test_http_mcp_adds_one_exact_transport_route_and_protected_resource_metadata() -> None:
    app = create_app(
        enable_research_agent_http=True,
        research_agent_http=_configuration(),
    )
    route_paths = [getattr(route, "path", None) for route in app.routes]

    assert route_paths.count("/mcp") == 1
    assert "/.well-known/oauth-protected-resource/mcp" in route_paths
    assert not any(
        path in {"/sse", "/mcp/sse", "/mcp/v1"}
        for path in route_paths
    )
    assert not any(
        name in {"AUTH_DISABLED", "X-Research-Scopes", "X-Tool-Set"}
        for name in app.openapi().get("components", {}).get("headers", {})
    )


def test_http_mcp_authenticates_before_rejecting_oversized_request_body() -> None:
    anyio.run(_exercise_oversized_request_auth_order)


def test_http_mcp_coalesces_and_bounds_chunked_asgi_request_frames() -> None:
    anyio.run(_exercise_chunked_request_boundaries)


async def _exercise_oversized_request_auth_order() -> None:
    app = create_app(
        enable_research_agent_http=True,
        research_agent_http=_configuration(token_verifier=_AcceptingVerifier()),
    )
    body = b"request-body-canary" * 10000
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://core.test",
    ) as client:
        unauthenticated = await client.post("/mcp", content=body)
        authenticated = await client.post(
            "/mcp",
            content=body,
            headers={"Authorization": "Bearer valid-token"},
        )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 413
    assert authenticated.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": -32600,
            "message": "Request exceeds server limit",
        },
    }
    assert "request-body-canary" not in authenticated.text


async def _exercise_chunked_request_boundaries() -> None:
    received_by_app: list[dict[str, object]] = []

    async def app(_scope, receive, send) -> None:
        received_by_app.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("core.test", 443),
        "root_path": "",
    }

    async def run(messages: list[dict[str, object]]) -> list[dict[str, object]]:
        pending = list(messages)
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return pending.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        await _BoundedMCPRequestBody(app)(scope, receive, send)  # type: ignore[arg-type]
        return sent

    sent = await run(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": True},
            {"type": "http.request", "body": b"ghi", "more_body": False},
        ]
    )
    assert sent[0]["status"] == 204
    assert received_by_app == [
        {"type": "http.request", "body": b"abcdefghi", "more_body": False}
    ]

    received_by_app.clear()
    oversized = await run(
        [
            {
                "type": "http.request",
                "body": b"x" * RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES,
                "more_body": True,
            },
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )
    assert oversized[0]["status"] == 413
    assert received_by_app == []

    too_many_frames = await run(
        [
            {"type": "http.request", "body": b"", "more_body": True}
            for _ in range(RESEARCH_AGENT_MAX_HTTP_BODY_FRAMES)
        ]
        + [{"type": "http.request", "body": b"", "more_body": False}]
    )
    assert too_many_frames[0]["status"] == 413
    assert received_by_app == []

    disconnected = await run([{"type": "http.disconnect"}])
    assert disconnected[0]["status"] == 204
    assert received_by_app == [{"type": "http.disconnect"}]
