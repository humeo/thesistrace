from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID

import anyio
import httpx
import jwt
import pytest
from fastapi import FastAPI
from jwt import PyJWK

from thesistrace.entrypoints.http import create_production_app
from thesistrace.research_agent import (
    PRODUCTION_RESEARCH_AGENT_SCOPES,
    RESEARCH_AGENT_TOOL_NAMES,
    ProductionResearchAgentTokenVerifier,
    ResearchAgentProductionSettings,
)

_PRIVATE_JWK = {
    "alg": "EdDSA",
    "crv": "Ed25519",
    "d": "2SCCVM_DYKEJvq18KV1M4UNFhxTHLKtdXxQFXLGlEBs",
    "kid": "test-signing-key-01",
    "kty": "OKP",
    "use": "sig",
    "x": "3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8",
}
_PUBLIC_JWK = {key: value for key, value in _PRIVATE_JWK.items() if key != "d"}
_ISSUER = "https://issuer.test/"
_AUDIENCE = "https://core.test/mcp"
_CLIENT_ID = "thesistrace-agent"
_SUBJECT = "00000000-0000-4000-8000-000000000001"
_NOW = 2_000_000_000


def test_production_settings_build_one_complete_mcp_configuration() -> None:
    settings = ResearchAgentProductionSettings.from_environment(_environment())

    assert settings.issuer_url == _ISSUER
    assert settings.resource_server_url == _AUDIENCE
    assert settings.client_id == _CLIENT_ID
    assert settings.deployment_tool_allowlist == RESEARCH_AGENT_TOOL_NAMES
    assert settings.allowed_hosts == ("core.test", "api:8100")
    assert settings.allowed_origins == ("https://agent.test",)
    assert settings.http_configuration().resource_server_url.unicode_string() == _AUDIENCE
    assert settings.http_configuration().supported_scopes == (PRODUCTION_RESEARCH_AGENT_SCOPES)


def test_production_factory_mounts_only_the_canonical_protected_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _environment().items():
        monkeypatch.setenv(name, value)

    monkeypatch.setenv("THESISTRACE_ENVIRONMENT", "production")
    monkeypatch.setenv("THESISTRACE_PUBLIC_ORIGIN", "https://core.test")
    monkeypatch.setenv("THESISTRACE_AUTH_INTERNAL_ORIGIN", "http://auth:8200")
    app = create_production_app()
    route_paths = [getattr(route, "path", None) for route in app.routes]

    assert route_paths.count("/mcp") == 1
    assert "/.well-known/oauth-protected-resource/mcp" in route_paths
    metadata = anyio.run(_resource_metadata, app)
    assert metadata["resource"] == _AUDIENCE
    assert metadata["authorization_servers"] == [_ISSUER]
    assert metadata["scopes_supported"] == sorted(
        scope.value for scope in PRODUCTION_RESEARCH_AGENT_SCOPES
    )
    assert "research:cancel" not in metadata["scopes_supported"]
    assert "tracking:stop" not in metadata["scopes_supported"]


@pytest.mark.parametrize(
    "name",
    [
        "THESISTRACE_MCP_ISSUER_URL",
        "THESISTRACE_MCP_RESOURCE_URL",
        "THESISTRACE_MCP_CLIENT_ID",
        "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK",
        "THESISTRACE_MCP_CLOCK_SKEW_SECONDS",
        "THESISTRACE_MCP_DEPLOYMENT_TOOLS",
        "THESISTRACE_MCP_ALLOWED_HOSTS",
        "THESISTRACE_MCP_ALLOWED_ORIGINS",
    ],
)
def test_production_settings_fail_closed_when_one_boundary_is_missing(name: str) -> None:
    environment = _environment()
    environment.pop(name)

    with pytest.raises(RuntimeError, match=name):
        ResearchAgentProductionSettings.from_environment(environment)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("THESISTRACE_MCP_ISSUER_URL", "http://issuer.test/"),
        ("THESISTRACE_MCP_RESOURCE_URL", "https://core.test/mcp/"),
        ("THESISTRACE_MCP_CLIENT_ID", "Agent Client"),
        ("THESISTRACE_MCP_VERIFYING_PUBLIC_JWK", "{}"),
        ("THESISTRACE_MCP_CLOCK_SKEW_SECONDS", "-1"),
        ("THESISTRACE_MCP_DEPLOYMENT_TOOLS", '["unknown_tool"]'),
        ("THESISTRACE_MCP_ALLOWED_HOSTS", '["https://core.test"]'),
        ("THESISTRACE_MCP_ALLOWED_ORIGINS", '["https://agent.test/"]'),
    ],
)
def test_production_settings_reject_malformed_security_policy(
    name: str,
    value: str,
) -> None:
    with pytest.raises(RuntimeError):
        ResearchAgentProductionSettings.from_environment({**_environment(), name: value})


def test_production_verifier_returns_one_researcher_bound_access_token() -> None:
    token = _token(_claims(_NOW))
    verifier = _verifier()

    access_token = anyio.run(verifier.verify_token, token)

    assert access_token is not None
    assert access_token.client_id == _CLIENT_ID
    assert access_token.subject == _SUBJECT
    assert access_token.resource == _AUDIENCE
    assert access_token.scopes == [
        "research:read",
        "research:execute",
        "tracking:read",
        "tracking:execute",
    ]
    assert UUID(access_token.subject) == UUID(_SUBJECT)
    assert access_token.token == token


@pytest.mark.parametrize(
    "mutate",
    [
        lambda claims: {**claims, "iss": "https://wrong-issuer.test/"},
        lambda claims: {**claims, "aud": "https://core.test/wrong"},
        lambda claims: {**claims, "sub": "not-a-researcher"},
        lambda claims: {**claims, "client_id": "wrong-client"},
        lambda claims: {**claims, "exp": claims["iat"] - 1},
        lambda claims: {**claims, "iat": _NOW + 31},
        lambda claims: {**claims, "nbf": _NOW + 31},
        lambda claims: {**claims, "scope": "research:read research:read"},
        lambda claims: {**claims, "scope": "research:unknown"},
        lambda claims: {**claims, "scope": "research:read research:cancel"},
        lambda claims: {**claims, "scope": "tracking:stop"},
        lambda claims: {key: value for key, value in claims.items() if key != "scope"},
    ],
)
def test_production_verifier_rejects_invalid_claims(
    mutate: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    claims = mutate(_claims(_NOW))
    assert anyio.run(_verifier().verify_token, _token(claims)) is None


def test_production_verifier_rejects_wrong_key_id() -> None:
    token = _token(_claims(_NOW), key_id="wrong-signing-key")
    assert anyio.run(_verifier().verify_token, token) is None


def _environment() -> dict[str, str]:
    return {
        "THESISTRACE_MCP_ISSUER_URL": _ISSUER,
        "THESISTRACE_MCP_RESOURCE_URL": _AUDIENCE,
        "THESISTRACE_MCP_CLIENT_ID": _CLIENT_ID,
        "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK": json.dumps(_PUBLIC_JWK),
        "THESISTRACE_MCP_CLOCK_SKEW_SECONDS": "30",
        "THESISTRACE_MCP_DEPLOYMENT_TOOLS": json.dumps(sorted(RESEARCH_AGENT_TOOL_NAMES)),
        "THESISTRACE_MCP_ALLOWED_HOSTS": '["core.test","api:8100"]',
        "THESISTRACE_MCP_ALLOWED_ORIGINS": '["https://agent.test"]',
    }


def _verifier() -> ProductionResearchAgentTokenVerifier:
    return ProductionResearchAgentTokenVerifier(
        issuer=_ISSUER,
        audience=_AUDIENCE,
        client_id=_CLIENT_ID,
        public_jwk=_PUBLIC_JWK,
        clock_skew_seconds=30,
        clock=lambda: _NOW,
    )


async def _resource_metadata(app: FastAPI) -> dict[str, object]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://core.test",
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    return response.json()


def _claims(now: int) -> dict[str, object]:
    return {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": _SUBJECT,
        "client_id": _CLIENT_ID,
        "iat": now,
        "nbf": now,
        "exp": now + 360,
        "jti": "00000000-0000-4000-8000-000000000099",
        "scope": "research:read research:execute tracking:read tracking:execute",
    }


def _token(claims: dict[str, object], *, key_id: str | None = None) -> str:
    return jwt.encode(
        claims,
        PyJWK.from_dict(_PRIVATE_JWK, algorithm="EdDSA"),
        algorithm="EdDSA",
        headers={"kid": key_id or _PRIVATE_JWK["kid"]},
    )


@pytest.mark.parametrize("mode", ["test", "development"])
def test_local_settings_build_http_configuration(mode: str) -> None:
    environment = _environment()
    environment.update(
        {
            "THESISTRACE_ENVIRONMENT": mode,
            "THESISTRACE_MCP_ISSUER_URL": "http://127.0.0.1:5173/api/auth",
            "THESISTRACE_MCP_RESOURCE_URL": "http://127.0.0.1:5173/mcp",
        }
    )
    config = ResearchAgentProductionSettings.from_environment(environment).http_configuration()
    assert str(config.resource_server_url) == "http://127.0.0.1:5173/mcp"
    environment["THESISTRACE_ENVIRONMENT"] = "production"
    with pytest.raises(RuntimeError, match="HTTPS"):
        ResearchAgentProductionSettings.from_environment(environment)
