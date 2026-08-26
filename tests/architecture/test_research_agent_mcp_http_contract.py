from __future__ import annotations

import pytest
from mcp.server.auth.provider import AccessToken

from thesistrace.entrypoints.http import create_app
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
)


class _RejectingVerifier:
    async def verify_token(self, _token: str) -> AccessToken | None:
        return None


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
