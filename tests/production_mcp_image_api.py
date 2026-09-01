from __future__ import annotations

import json
import os

from mcp.server.auth.provider import AccessToken
from production_mcp_image_canaries import ACTION_TOKEN, READ_TOKEN, SUBJECT
from uvicorn import run

from thesistrace.entrypoints.http import create_app
from thesistrace.research_agent import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentHTTPConfiguration,
    ResearchAgentScope,
)

ISSUER_URL = "https://image-smoke-issuer.test/"
RESOURCE_URL = "https://core.test/mcp"
TRUSTED_ORIGIN = "https://codex.test"


class LocalImageSmokeTokenVerifier:
    """Explicit local verifier used only by the mounted production-image harness."""

    async def verify_token(self, token: str) -> AccessToken | None:
        grants = {
            READ_TOKEN: (ResearchAgentScope.RESEARCH_READ.value,),
            ACTION_TOKEN: (
                ResearchAgentScope.RESEARCH_READ.value,
                ResearchAgentScope.RESEARCH_EXECUTE.value,
            ),
        }
        scopes = grants.get(token)
        if scopes is None:
            return None
        return AccessToken(
            token=token,
            client_id="image-smoke-client",
            scopes=list(scopes),
            expires_at=4_102_444_800,
            resource=RESOURCE_URL,
            subject=SUBJECT,
            claims={"iss": ISSUER_URL, "test_verifier": True},
        )


def application():
    return create_app(
        enable_research_agent_http=True,
        research_agent_http=ResearchAgentHTTPConfiguration(
            token_verifier=LocalImageSmokeTokenVerifier(),
            issuer_url=ISSUER_URL,
            resource_server_url=RESOURCE_URL,
            deployment_tool_allowlist=RESEARCH_AGENT_TOOL_NAMES,
            supported_scopes=frozenset(ResearchAgentScope),
            allowed_hosts=tuple(
                json.loads(os.environ["THESISTRACE_MCP_ALLOWED_HOSTS"])
            ),
            allowed_origins=(
                *tuple(json.loads(os.environ["THESISTRACE_MCP_ALLOWED_ORIGINS"])),
                TRUSTED_ORIGIN,
            ),
        ),
    )


if __name__ == "__main__":
    run(application(), host="0.0.0.0", port=8100, access_log=False)
