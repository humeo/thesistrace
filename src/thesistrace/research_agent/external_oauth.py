"""Revocable, resource-bound external OAuth tokens owned by the Auth service."""

from __future__ import annotations

from time import time
from uuid import UUID

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.exceptions import HTTPException

from thesistrace.research_agent.oauth import PRODUCTION_RESEARCH_AGENT_SCOPES


class _VerifiedToken(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    active: bool
    sub: str
    client_id: str
    scopes: list[str]
    exp: int
    jti: str
    resource: str


class McpTokenVerifier(TokenVerifier):
    """Dispatch explicit token formats; an invalid token never tries another verifier."""

    def __init__(
        self,
        *,
        internal: TokenVerifier,
        auth_origin: str,
        resource: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._internal = internal
        self._auth_origin = auth_origin
        self._resource = resource
        self._transport = transport

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("tt_mcp_"):
            return await self._internal.verify_token(token)
        if len(token) > 4096:
            return None
        try:
            async with httpx.AsyncClient(
                timeout=2.0, follow_redirects=False, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._auth_origin}/internal/mcp/verify",
                    json={"token": token},
                )
            if response.status_code != 200 or len(response.content) > 16384:
                raise HTTPException(503, "MCP authorization unavailable")
            payload = response.json()
            if payload == {"active": False}:
                return None
            result = _VerifiedToken.model_validate(payload)
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            raise HTTPException(503, "MCP authorization unavailable") from error
        allowed = {scope.value for scope in PRODUCTION_RESEARCH_AGENT_SCOPES}
        if (
            not result.active
            or result.resource != self._resource
            or result.exp <= time()
            or not result.client_id
            or not result.scopes
            or not set(result.scopes).issubset(allowed)
        ):
            return None
        try:
            if str(UUID(result.sub)) != result.sub or str(UUID(result.jti)) != result.jti:
                return None
        except ValueError:
            return None
        return AccessToken(
            token=token,
            client_id=result.client_id,
            scopes=result.scopes,
            expires_at=result.exp,
            resource=result.resource,
            subject=result.sub,
            claims={"jti": result.jti},
        )
