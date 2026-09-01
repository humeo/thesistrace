from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from jwt import PyJWK, PyJWTError
from mcp.server.auth.provider import AccessToken, TokenVerifier

from thesistrace.research_agent.http_server import ResearchAgentHTTPConfiguration
from thesistrace.research_agent.models import ResearchAgentScope
from thesistrace.research_agent.registry import RESEARCH_AGENT_TOOL_NAMES

_JWK_MEMBER = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)
_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$", re.ASCII)
_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$", re.ASCII)
_PUBLIC_JWK_KEYS = frozenset({"alg", "crv", "kid", "kty", "use", "x"})
PRODUCTION_RESEARCH_AGENT_SCOPES = frozenset(
    {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
)


@dataclass(frozen=True)
class ResearchAgentProductionSettings:
    issuer_url: str
    resource_server_url: str
    client_id: str
    public_jwk: Mapping[str, str]
    clock_skew_seconds: int
    deployment_tool_allowlist: frozenset[str]
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> ResearchAgentProductionSettings:
        selected = os.environ if environment is None else environment
        issuer_url = _canonical_https_url(
            _required(selected, "THESISTRACE_MCP_ISSUER_URL"),
            "THESISTRACE_MCP_ISSUER_URL",
        )
        resource_server_url = _canonical_https_url(
            _required(selected, "THESISTRACE_MCP_RESOURCE_URL"),
            "THESISTRACE_MCP_RESOURCE_URL",
        )
        if urlsplit(resource_server_url).path != "/mcp":
            raise RuntimeError(
                "THESISTRACE_MCP_RESOURCE_URL must identify the canonical /mcp resource"
            )
        client_id = _required(selected, "THESISTRACE_MCP_CLIENT_ID")
        if _CLIENT_ID.fullmatch(client_id) is None:
            raise RuntimeError("THESISTRACE_MCP_CLIENT_ID is invalid")
        public_jwk = _public_jwk(
            _required(selected, "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK")
        )
        clock_skew_seconds = _nonnegative_integer(
            _required(selected, "THESISTRACE_MCP_CLOCK_SKEW_SECONDS"),
            "THESISTRACE_MCP_CLOCK_SKEW_SECONDS",
        )
        deployment_tool_allowlist = frozenset(
            _json_string_list(
                _required(selected, "THESISTRACE_MCP_DEPLOYMENT_TOOLS"),
                "THESISTRACE_MCP_DEPLOYMENT_TOOLS",
            )
        )
        unknown_tools = deployment_tool_allowlist - RESEARCH_AGENT_TOOL_NAMES
        if unknown_tools:
            raise RuntimeError("THESISTRACE_MCP_DEPLOYMENT_TOOLS contains unknown Tools")
        allowed_hosts = tuple(
            _json_string_list(
                _required(selected, "THESISTRACE_MCP_ALLOWED_HOSTS"),
                "THESISTRACE_MCP_ALLOWED_HOSTS",
            )
        )
        for host in allowed_hosts:
            _allowed_host(host)
        allowed_origins = tuple(
            _json_string_list(
                _required(selected, "THESISTRACE_MCP_ALLOWED_ORIGINS"),
                "THESISTRACE_MCP_ALLOWED_ORIGINS",
            )
        )
        for origin in allowed_origins:
            _exact_http_origin(origin, "THESISTRACE_MCP_ALLOWED_ORIGINS")
        return cls(
            issuer_url=issuer_url,
            resource_server_url=resource_server_url,
            client_id=client_id,
            public_jwk=public_jwk,
            clock_skew_seconds=clock_skew_seconds,
            deployment_tool_allowlist=deployment_tool_allowlist,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

    def http_configuration(self) -> ResearchAgentHTTPConfiguration:
        return ResearchAgentHTTPConfiguration(
            token_verifier=ProductionResearchAgentTokenVerifier(
                issuer=self.issuer_url,
                audience=self.resource_server_url,
                client_id=self.client_id,
                public_jwk=self.public_jwk,
                clock_skew_seconds=self.clock_skew_seconds,
            ),
            issuer_url=self.issuer_url,
            resource_server_url=self.resource_server_url,
            deployment_tool_allowlist=self.deployment_tool_allowlist,
            allowed_hosts=self.allowed_hosts,
            allowed_origins=self.allowed_origins,
            supported_scopes=PRODUCTION_RESEARCH_AGENT_SCOPES,
        )


class ProductionResearchAgentTokenVerifier(TokenVerifier):
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        client_id: str,
        public_jwk: Mapping[str, str],
        clock_skew_seconds: int,
        clock: Callable[[], float] = time,
    ) -> None:
        if clock_skew_seconds < 0:
            raise ValueError("MCP clock skew must be nonnegative")
        self._issuer = issuer
        self._audience = audience
        self._client_id = client_id
        self._clock_skew_seconds = clock_skew_seconds
        self._clock = clock
        try:
            self._key = PyJWK.from_dict(dict(public_jwk), algorithm="EdDSA")
        except (PyJWTError, TypeError, ValueError) as error:
            raise ValueError("MCP verifying public JWK is invalid") from error

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "EdDSA" or header.get("kid") != self._key.key_id:
                return None
            if "crit" in header or "jku" in header or "jwk" in header or "x5u" in header:
                return None
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["EdDSA"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._clock_skew_seconds,
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
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
                    ]
                },
            )
            return self._access_token(token, claims, now=self._clock())
        except (PyJWTError, TypeError, ValueError):
            return None

    def _access_token(
        self,
        token: str,
        claims: Mapping[str, Any],
        *,
        now: float,
    ) -> AccessToken | None:
        if claims.get("iss") != self._issuer or claims.get("aud") != self._audience:
            return None
        if claims.get("client_id") != self._client_id:
            return None
        temporal = tuple(claims.get(name) for name in ("iat", "nbf", "exp"))
        if any(type(value) is not int for value in temporal):
            return None
        issued_at, not_before, expires_at = temporal
        assert isinstance(issued_at, int)
        assert isinstance(not_before, int)
        assert isinstance(expires_at, int)
        if (
            expires_at <= issued_at
            or not_before > expires_at
            or issued_at > now + self._clock_skew_seconds
            or not_before > now + self._clock_skew_seconds
            or expires_at <= now - self._clock_skew_seconds
        ):
            return None
        subject = claims.get("sub")
        if not isinstance(subject, str):
            return None
        try:
            if str(UUID(subject)) != subject:
                return None
        except ValueError:
            return None
        token_id = claims.get("jti")
        try:
            if not isinstance(token_id, str) or str(UUID(token_id)) != token_id:
                return None
        except ValueError:
            return None
        scope_claim = claims.get("scope")
        if not isinstance(scope_claim, str) or not scope_claim:
            return None
        scopes = scope_claim.split(" ")
        allowed_scopes = {
            scope.value for scope in PRODUCTION_RESEARCH_AGENT_SCOPES
        }
        if (
            scope_claim != " ".join(scopes)
            or len(set(scopes)) != len(scopes)
            or any(scope not in allowed_scopes for scope in scopes)
        ):
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=scopes,
            expires_at=expires_at,
            resource=self._audience,
            subject=subject,
            claims={"iss": self._issuer, "jti": token_id},
        )


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise RuntimeError(f"missing Research Agent MCP configuration: {name}")
    return value


def _canonical_https_url(value: str, variable_name: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or value != parts.geturl()
    ):
        raise RuntimeError(f"{variable_name} must be a canonical HTTPS URL")
    return value


def _public_jwk(value: str) -> Mapping[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise RuntimeError("THESISTRACE_MCP_VERIFYING_PUBLIC_JWK is invalid") from error
    if not isinstance(parsed, dict) or frozenset(parsed) != _PUBLIC_JWK_KEYS:
        raise RuntimeError("THESISTRACE_MCP_VERIFYING_PUBLIC_JWK is invalid")
    if (
        parsed.get("alg") != "EdDSA"
        or parsed.get("crv") != "Ed25519"
        or parsed.get("kty") != "OKP"
        or parsed.get("use") != "sig"
        or not isinstance(parsed.get("kid"), str)
        or _KEY_ID.fullmatch(parsed["kid"]) is None
        or not isinstance(parsed.get("x"), str)
        or _JWK_MEMBER.fullmatch(parsed["x"]) is None
    ):
        raise RuntimeError("THESISTRACE_MCP_VERIFYING_PUBLIC_JWK is invalid")
    return {key: str(parsed[key]) for key in sorted(_PUBLIC_JWK_KEYS)}


def _json_string_list(value: str, variable_name: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{variable_name} must be a JSON string array") from error
    if (
        not isinstance(parsed, list)
        or not parsed
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(set(parsed)) != len(parsed)
    ):
        raise RuntimeError(f"{variable_name} must be a nonempty unique JSON string array")
    return parsed


def _allowed_host(value: str) -> None:
    parts = urlsplit(f"http://{value}")
    try:
        port = parts.port
    except ValueError as error:
        raise RuntimeError("THESISTRACE_MCP_ALLOWED_HOSTS contains an invalid host") from error
    if (
        not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path
        or parts.query
        or parts.fragment
        or parts.netloc != value
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise RuntimeError("THESISTRACE_MCP_ALLOWED_HOSTS contains an invalid host")


def _exact_http_origin(value: str, variable_name: str) -> None:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path
        or parts.query
        or parts.fragment
        or value != parts.geturl()
    ):
        raise RuntimeError(f"{variable_name} contains an invalid origin")


def _nonnegative_integer(value: str, variable_name: str) -> int:
    if re.fullmatch(r"0|[1-9][0-9]*", value, re.ASCII) is None:
        raise RuntimeError(f"{variable_name} must be a nonnegative integer")
    parsed = int(value)
    if parsed > 86400:
        raise RuntimeError(f"{variable_name} is unreasonably large")
    return parsed


__all__ = (
    "PRODUCTION_RESEARCH_AGENT_SCOPES",
    "ProductionResearchAgentTokenVerifier",
    "ResearchAgentProductionSettings",
)
