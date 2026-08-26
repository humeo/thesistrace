from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256
from itertools import count
from pathlib import Path

import anyio
import httpx2
import jwt
from core_runtime import drop_product_schemas, isolated_core_settings
from jsonschema import validate
from jwt import PyJWTError
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.operational_events import OperationalEvent
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
    ResearchAgentScope,
)

_ISSUER_URL = "https://issuer.test/"
_RESOURCE_URL = "https://core.test/mcp"
_TRUSTED_ORIGIN = "https://codex.test"
_TEST_NOW = 2_000_000_000
_SIGNING_KEY = "deterministic-local-oauth-signing-key"


class _DeterministicOAuthIssuer:
    def __init__(self) -> None:
        self._grant_overrides: dict[str, tuple[str, ...]] = {}
        self._token_ids = count()

    def issue(
        self,
        *,
        scopes: tuple[str, ...] = (ResearchAgentScope.RESEARCH_READ.value,),
        lifetime_seconds: int = 120,
        not_before_seconds: int = 0,
        issuer: str = _ISSUER_URL,
        audience: str = _RESOURCE_URL,
        signing_key: str = _SIGNING_KEY,
    ) -> str:
        return jwt.encode(
            {
                "iss": issuer,
                "aud": audience,
                "sub": "researcher_test",
                "client_id": "codex_test_client",
                "iat": _TEST_NOW,
                "nbf": _TEST_NOW + not_before_seconds,
                "exp": _TEST_NOW + lifetime_seconds,
                "jti": f"token_{next(self._token_ids)}",
                "scope": " ".join(scopes),
            },
            signing_key,
            algorithm="HS256",
        )

    def replace_grant(self, token: str, scopes: tuple[str, ...]) -> None:
        self._grant_overrides[token] = scopes

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                _SIGNING_KEY,
                algorithms=["HS256"],
                issuer=_ISSUER_URL,
                audience=_RESOURCE_URL,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "client_id",
                        "iat",
                        "nbf",
                        "exp",
                        "jti",
                        "scope",
                    ],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except PyJWTError:
            return None
        temporal_claims = (claims["iat"], claims["nbf"], claims["exp"])
        if any(type(value) is not int for value in temporal_claims):
            return None
        if claims["iat"] > _TEST_NOW or claims["nbf"] > _TEST_NOW:
            return None
        if claims["exp"] <= _TEST_NOW:
            return None
        if not isinstance(claims["scope"], str):
            return None
        scopes = self._grant_overrides.get(token, tuple(claims["scope"].split()))
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=list(scopes),
            expires_at=claims["exp"],
            resource=_RESOURCE_URL,
            subject=claims["sub"],
            claims={"iss": claims["iss"], "jti": claims["jti"]},
        )


def test_mounted_oauth_streamable_http_read_loop_and_fail_closed_boundaries(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    issuer = _DeterministicOAuthIssuer()
    events: list[OperationalEvent] = []
    app = _app(settings, issuer, events=events)
    try:
        anyio.run(_exercise_http_contract, app, issuer)
        serialized_events = str(events)
        mcp_events = [event for event in events if event.component == "research_agent_mcp"]
        assert mcp_events
        assert all(
            event.context["transport"] == "streamable_http" for event in mcp_events
        )
        expected_subject = f"oauth_{sha256(b'researcher_test').hexdigest()[:32]}"
        assert all(event.context["subject"] == expected_subject for event in mcp_events)
        assert "researcher_test" not in serialized_events
        assert _SIGNING_KEY not in serialized_events
        assert "eyJ" not in serialized_events
    finally:
        drop_product_schemas(settings)


def test_http_discovery_intersects_deployment_allowlist_with_grant(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path / "allowlist-data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    issuer = _DeterministicOAuthIssuer()
    app = _app(
        settings,
        issuer,
        deployment_tool_allowlist=frozenset({"get_research_context"}),
    )
    try:
        anyio.run(_exercise_allowlist_intersection, app, issuer.issue())
    finally:
        drop_product_schemas(settings)


def _app(
    settings: CoreSettings,
    issuer: _DeterministicOAuthIssuer,
    *,
    deployment_tool_allowlist: frozenset[str] = RESEARCH_AGENT_TOOL_NAMES,
    events: list[OperationalEvent] | None = None,
):
    return create_app(
        settings,
        event_sink=(lambda _event: None) if events is None else events.append,
        enable_research_agent_http=True,
        research_agent_http=ResearchAgentHTTPConfiguration(
            token_verifier=issuer,
            issuer_url=_ISSUER_URL,
            resource_server_url=_RESOURCE_URL,
            deployment_tool_allowlist=deployment_tool_allowlist,
            allowed_hosts=("core.test",),
            allowed_origins=(_TRUSTED_ORIGIN,),
        ),
    )


async def _exercise_http_contract(app, issuer: _DeterministicOAuthIssuer) -> None:
    read_token = issuer.issue()
    no_grant_token = issuer.issue(scopes=())
    async with app.router.lifespan_context(app):
        await _assert_protected_resource_and_authentication_boundaries(
            app,
            issuer,
            read_token=read_token,
        )

        first_context: dict[str, object]
        async with _mcp_client(app, read_token) as client:
            tools = await client.list_tools()
            tools_by_name = {tool.name: tool for tool in tools.tools}
            assert set(tools_by_name) == RESEARCH_AGENT_TOOL_NAMES - {
                "submit_research_run"
            }

            context = await client.call_tool("get_research_context", {})
            assert context.is_error is False
            validate(
                context.structured_content,
                tools_by_name["get_research_context"].output_schema,
            )
            first_context = context.structured_content

            catalog = await client.call_tool(
                "get_alpha_catalog",
                {"identifiers": ["close", "ts_mean", "unknown_identifier"]},
            )
            assert catalog.is_error is False
            validate(catalog.structured_content, tools_by_name["get_alpha_catalog"].output_schema)
            assert catalog.structured_content["unknown_identifiers"] == ["unknown_identifier"]

            diagnostic = await client.call_tool(
                "diagnose_alpha_formula",
                {"source": "unknown_alpha + close"},
            )
            assert diagnostic.is_error is False
            validate(
                diagnostic.structured_content,
                tools_by_name["diagnose_alpha_formula"].output_schema,
            )
            assert diagnostic.structured_content["valid"] is False

            issuer.replace_grant(read_token, ())
            denied_after_discovery = await client.call_tool("get_research_context", {})
            assert denied_after_discovery.is_error is True
            assert denied_after_discovery.structured_content["code"] == "FORBIDDEN"
            issuer.replace_grant(read_token, (ResearchAgentScope.RESEARCH_READ.value,))

        async with _mcp_client(app, no_grant_token) as client:
            assert (await client.list_tools()).tools == []

        async with _mcp_client(app, read_token) as reconnected:
            second_context = await reconnected.call_tool("get_research_context", {})
            assert second_context.is_error is False
            assert second_context.structured_content == first_context


async def _exercise_allowlist_intersection(app, token: str) -> None:
    async with app.router.lifespan_context(app):
        async with _mcp_client(app, token) as client:
            discovered = await client.list_tools()
            assert [tool.name for tool in discovered.tools] == ["get_research_context"]
            denied = await client.call_tool("get_alpha_catalog", {})
            assert denied.is_error is True
            assert denied.structured_content["code"] == "FORBIDDEN"


async def _assert_protected_resource_and_authentication_boundaries(
    app,
    issuer: _DeterministicOAuthIssuer,
    *,
    read_token: str,
) -> None:
    async with _raw_http_client(app) as client:
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == _RESOURCE_URL
        assert metadata.json()["authorization_servers"] == [_ISSUER_URL]
        assert set(metadata.json()["scopes_supported"]) == {
            scope.value for scope in ResearchAgentScope
        }

        invalid_tokens = [
            None,
            "malformed-token",
            issuer.issue(lifetime_seconds=-1),
            issuer.issue(not_before_seconds=60),
            issuer.issue(issuer="https://wrong-issuer.test"),
            issuer.issue(audience="https://wrong-resource.test/mcp"),
            issuer.issue(signing_key="wrong-signing-key-that-is-at-least-32-bytes"),
        ]
        for token in invalid_tokens:
            response = await _initialize(client, token=token)
            assert response.status_code == 401
            assert "resource_metadata=" in response.headers["www-authenticate"]

        basic = await _initialize(client, authorization="Basic not-a-bearer-token")
        assert basic.status_code == 401
        query_token = await client.post(
            f"/mcp?access_token={read_token}",
            json=_initialize_request(),
            headers=_protocol_headers(),
        )
        assert query_token.status_code == 401
        scope_header = await client.post(
            "/mcp",
            json=_initialize_request(),
            headers={**_protocol_headers(), "X-Research-Scopes": "research:read"},
        )
        assert scope_header.status_code == 401

        untrusted_host = await _initialize(
            client,
            token=read_token,
            extra_headers={"Host": "attacker.test"},
        )
        assert untrusted_host.status_code == 421
        untrusted_origin = await _initialize(
            client,
            token=read_token,
            extra_headers={"Origin": "https://attacker.test"},
        )
        assert untrusted_origin.status_code == 403
        trusted = await _initialize(
            client,
            token=read_token,
            extra_headers={"Origin": _TRUSTED_ORIGIN},
        )
        assert trusted.status_code == 200

        for path in ("/sse", "/mcp/sse", "/mcp/v1"):
            response = await client.post(
                path,
                json=_initialize_request(),
                headers={
                    **_protocol_headers(),
                    "Authorization": f"Bearer {read_token}",
                },
            )
            assert response.status_code == 404


@asynccontextmanager
async def _mcp_client(app, token: str) -> AsyncIterator[Client]:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="https://core.test",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": _TRUSTED_ORIGIN,
        },
    ) as http_client:
        async with Client(
            streamable_http_client(
                _RESOURCE_URL,
                http_client=http_client,
            ),
            mode="legacy",
        ) as client:
            yield client


def _raw_http_client(app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="https://core.test",
    )


async def _initialize(
    client: httpx2.AsyncClient,
    *,
    token: str | None = None,
    authorization: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx2.Response:
    headers = _protocol_headers()
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if authorization is not None:
        headers["Authorization"] = authorization
    if extra_headers is not None:
        headers.update(extra_headers)
    return await client.post("/mcp", json=_initialize_request(), headers=headers)


def _protocol_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_HANDSHAKE_VERSION,
    }


def _initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "acceptance", "version": "1"},
        },
    }
