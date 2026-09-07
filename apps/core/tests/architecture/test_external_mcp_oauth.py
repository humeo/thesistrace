from __future__ import annotations

from time import time

import httpx
import pytest
from mcp.server.auth.provider import AccessToken
from starlette.exceptions import HTTPException

from thesistrace.research_agent.external_oauth import McpTokenVerifier

RESOURCE = "https://thesistrace.test/mcp"


class InternalVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        assert token == "internal-jwt"
        return AccessToken(token=token, client_id="agent", scopes=["research:read"])


def verifier(payload: object, status: int = 200) -> McpTokenVerifier:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://auth:8200/internal/mcp/verify"
        assert request.method == "POST"
        return httpx.Response(status, json=payload)

    return McpTokenVerifier(
        internal=InternalVerifier(),
        auth_origin="http://auth:8200",
        resource=RESOURCE,
        transport=httpx.MockTransport(handle),
    )


def claims() -> dict[str, object]:
    return dict(
        active=True,
        sub="00000000-0000-4000-8000-000000000001",
        client_id="external-client",
        scopes=["research:read"],
        exp=int(time()) + 60,
        jti="00000000-0000-4000-8000-000000000002",
        resource=RESOURCE,
    )


@pytest.mark.anyio
async def test_external_access_uses_authoritative_owner_resource_and_permissions() -> None:
    result = await verifier(claims()).verify_token("tt_mcp_secret")
    assert result is not None
    assert result.subject == claims()["sub"]
    assert result.client_id == "external-client"
    assert result.scopes == ["research:read"]
    assert (await verifier({"active": False}).verify_token("tt_mcp_revoked")) is None
    assert (await verifier({}).verify_token("internal-jwt")) is not None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [
        dict(resource="https://other.test/mcp"),
        dict(exp=0),
        dict(scopes=["research:cancel"]),
        dict(sub="not-a-user"),
    ],
)
async def test_wrong_resource_expired_or_invalid_grants_are_denied(
    change: dict[str, object],
) -> None:
    assert await verifier(claims() | change).verify_token("tt_mcp_invalid") is None


@pytest.mark.anyio
async def test_auth_outage_does_not_try_the_internal_verifier() -> None:
    with pytest.raises(HTTPException) as error:
        await verifier({}, 503).verify_token("tt_mcp_outage")
    assert error.value.status_code == 503
