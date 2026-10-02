from __future__ import annotations

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace

import anyio
import httpx
import pytest
from mcp.server.auth.provider import AccessToken
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from psycopg_pool import PoolTimeout

from thesistrace.entrypoints.http import create_app
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
    ResearchAgentScope,
)
from thesistrace.research_agent.http_server import (
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
        "supported_scopes": frozenset(ResearchAgentScope),
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
    with pytest.raises(TypeError, match="supported_scopes"):
        ResearchAgentHTTPConfiguration(
            token_verifier=_RejectingVerifier(),
            issuer_url="https://issuer.test",
            resource_server_url="https://core.test/mcp",
            deployment_tool_allowlist=RESEARCH_AGENT_TOOL_NAMES,
            allowed_hosts=("core.test",),
        )


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
        ({"supported_scopes": frozenset()}, "requires explicit supported_scopes"),
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


def test_http_mcp_discovery_and_formula_diagnosis_survive_database_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Database:
        unavailable = False

        @contextmanager
        def transaction(self):
            if self.unavailable:
                raise PoolTimeout("database temporarily unavailable")
            yield self

        def execute(self, _sql):
            return self

        def fetchone(self):
            return {"secret": "70" * 32}

    database = Database()
    runtime = SimpleNamespace(
        database=database, data_overview=None, research_folders=None,
        research_authoring=None, research_runs=None, research_batches=None, daily_tracks=None,
    )

    @contextmanager
    def open_runtime(*_args, **_kwargs):
        yield runtime

    monkeypatch.setattr("thesistrace.entrypoints.http.open_core_runtime", open_runtime)

    async def exercise() -> None:
        app = create_app(
            settings=object(), auth_verifier=object(), public_origin="https://core.test",
            enable_research_agent_http=True,
            research_agent_http=_configuration(token_verifier=_AcceptingVerifier()),
            event_sink=lambda _event: None,
        )
        async with app.router.lifespan_context(app):
            database.unavailable = True
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://core.test",
            ) as client:
                headers = {
                    "Authorization": "Bearer valid-token",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": LATEST_HANDSHAKE_VERSION,
                }
                discovered = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
                })
                assert discovered.status_code == 200
                assert "diagnose_alpha_formula" in {
                    item["name"] for item in discovered.json()["result"]["tools"]
                }
                diagnosed = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "diagnose_alpha_formula", "arguments": {"source": "close"},
                    },
                })
                assert diagnosed.status_code == 200
                assert diagnosed.json()["result"].get("isError", False) is False

    anyio.run(exercise)


def test_http_mcp_coalesces_and_bounds_chunked_asgi_request_frames() -> None:
    anyio.run(_exercise_chunked_request_boundaries)


@pytest.mark.parametrize("stream", ["stalled", "empty", "trickled"])
def test_http_mcp_body_read_has_a_total_deadline(
    monkeypatch: pytest.MonkeyPatch, stream: str,
) -> None:
    monkeypatch.setattr(
        "thesistrace.research_agent.http_server.RESEARCH_AGENT_HTTP_BODY_TIMEOUT_SECONDS",
        0.02, raising=False,
    )

    async def exercise() -> None:
        app = create_app(
            enable_research_agent_http=True,
            research_agent_http=_configuration(token_verifier=_AcceptingVerifier()),
        )

        async def body():
            yield b"{"
            end = monotonic() + 0.1
            while monotonic() < end:
                if stream == "stalled":
                    await anyio.sleep(0.1)
                elif stream == "trickled":
                    await anyio.sleep(0.005)
                yield b"" if stream == "empty" else b" "
            yield b"}"

        with anyio.fail_after(1):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://core.test",
            ) as client:
                response = await client.post("/mcp", content=body(), headers={
                    "Authorization": "Bearer valid-token", "Content-Type": "application/json",
                })
        assert response.status_code == 408
        assert response.json()["error"]["message"] == "Request body read timed out"

    anyio.run(exercise)


async def _exercise_oversized_request_auth_order() -> None:
    app = create_app(
        enable_research_agent_http=True,
        research_agent_http=_configuration(token_verifier=_AcceptingVerifier()),
    )
    body = b"request-body-canary" + b"x" * RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES
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

    fragmented = await run(
        [
            {"type": "http.request", "body": b"x", "more_body": True}
            for _ in range(480)
        ]
        + [{"type": "http.request", "body": b"", "more_body": False}]
    )
    assert fragmented[0]["status"] == 204
    assert received_by_app == [
        {"type": "http.request", "body": b"x" * 480, "more_body": False}
    ]

    received_by_app.clear()
    disconnected = await run([{"type": "http.disconnect"}])
    assert disconnected[0]["status"] == 204
    assert received_by_app == [{"type": "http.disconnect"}]
