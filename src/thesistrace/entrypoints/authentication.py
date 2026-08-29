from __future__ import annotations

import os
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from thesistrace.researcher import ResearcherIdentity

AUTH_VERIFY_TIMEOUT_SECONDS = 2.0


class InvalidLoginSession(RuntimeError):
    pass


class AuthSessionUnavailable(RuntimeError):
    pass


class SessionVerifier(Protocol):
    async def verify(self, cookie: str | None) -> ResearcherIdentity: ...


class _VerifiedSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active: Literal[True]
    display_label: str
    email: str
    researcher_id: str


@dataclass(frozen=True)
class CoreHttpSettings:
    auth_internal_origin: str
    public_origin: str

    @classmethod
    def from_environment(cls) -> CoreHttpSettings:
        environment = os.environ.get("THESISTRACE_ENVIRONMENT", "")
        if environment not in {"development", "test", "production"}:
            raise RuntimeError(
                "THESISTRACE_ENVIRONMENT must be development, test, or production"
            )
        auth_internal_origin = os.environ.get(
            "THESISTRACE_AUTH_INTERNAL_ORIGIN", ""
        )
        public_origin = os.environ.get("THESISTRACE_PUBLIC_ORIGIN", "")
        if not auth_internal_origin:
            raise RuntimeError(
                "missing Core HTTP configuration: THESISTRACE_AUTH_INTERNAL_ORIGIN"
            )
        if not public_origin:
            raise RuntimeError(
                "missing Core HTTP configuration: THESISTRACE_PUBLIC_ORIGIN"
            )
        return cls(
            auth_internal_origin=_exact_origin(
                auth_internal_origin,
                "THESISTRACE_AUTH_INTERNAL_ORIGIN",
            ),
            public_origin=_exact_public_origin(
                public_origin,
                "THESISTRACE_PUBLIC_ORIGIN",
                environment,
            ),
        )


class CoreAuthVerifier:
    def __init__(
        self,
        internal_origin: str,
        *,
        timeout_seconds: float = AUTH_VERIFY_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Auth verification timeout must be positive")
        self._client = httpx.AsyncClient(
            base_url=_exact_origin(
                internal_origin,
                "THESISTRACE_AUTH_INTERNAL_ORIGIN",
            ),
            follow_redirects=False,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def verify(self, cookie: str | None) -> ResearcherIdentity:
        headers = {} if cookie is None or not cookie.strip() else {"cookie": cookie}
        try:
            response = await self._client.post(
                "/internal/session/verify",
                headers=headers,
            )
        except (httpx.HTTPError, OSError) as error:
            raise AuthSessionUnavailable() from error
        if response.status_code == 401:
            raise InvalidLoginSession()
        if response.status_code != 200:
            raise AuthSessionUnavailable()
        try:
            verified = _VerifiedSession.model_validate(response.json())
            return ResearcherIdentity(
                researcher_id=verified.researcher_id,
                email=verified.email,
                display_label=verified.display_label,
            )
        except (ValidationError, ValueError) as error:
            raise AuthSessionUnavailable() from error

    async def aclose(self) -> None:
        await self._client.aclose()


def _exact_origin(value: str, variable_name: str) -> str:
    try:
        parsed = httpx.URL(value)
    except Exception as error:
        raise RuntimeError(f"{variable_name} must be an exact HTTP origin") from error
    canonical = str(parsed.copy_with(path=""))
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.host is None
        or parsed.userinfo
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or value != canonical
    ):
        raise RuntimeError(f"{variable_name} must be an exact HTTP origin")
    return canonical


def _exact_public_origin(
    value: str,
    variable_name: str,
    environment: str,
) -> str:
    origin = _exact_origin(value, variable_name)
    parsed = httpx.URL(origin)
    assert parsed.host is not None
    hostname = parsed.host.lower().removesuffix(".")
    loopback = _is_loopback_hostname(hostname)
    is_ip_address = _is_ip_address(hostname)
    if environment == "production":
        if parsed.scheme != "https" or loopback or is_ip_address:
            raise RuntimeError(
                f"{variable_name} must use HTTPS and a non-loopback hostname in Production"
            )
    elif parsed.scheme != "http" or not loopback:
        raise RuntimeError(
            f"{variable_name} must use an HTTP loopback origin outside Production"
        )
    return origin


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_ip_address(hostname: str) -> bool:
    try:
        ip_address(hostname)
    except ValueError:
        return False
    return True


__all__ = (
    "AUTH_VERIFY_TIMEOUT_SECONDS",
    "AuthSessionUnavailable",
    "CoreAuthVerifier",
    "CoreHttpSettings",
    "InvalidLoginSession",
    "SessionVerifier",
)
