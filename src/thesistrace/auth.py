import json
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import jwt
import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class InsForgeIdentity:
    subject: str
    email: str


@dataclass(frozen=True)
class InsForgeUser:
    subject: str
    email: str
    email_verified: bool


class AuthenticationFailure(RuntimeError):
    def __init__(self, reason_code: str, status_code: int) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.status_code = status_code


class IdentityVerifier(Protocol):
    def verify(self, authorization: str | None) -> InsForgeIdentity: ...


class InsForgeIdentityDirectory(Protocol):
    def find_user(self, subject: str) -> InsForgeUser | None: ...


class PostgresInsForgeIdentityDirectory:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def find_user(self, subject: str) -> InsForgeUser | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT id::text AS subject, email, email_verified
                FROM auth.users
                WHERE id::text = %s
                """,
                (subject,),
            ).fetchone()
        if row is None:
            return None
        return InsForgeUser(
            subject=str(row["subject"]),
            email=str(row["email"]),
            email_verified=bool(row["email_verified"]),
        )


class InsForgeJwtVerifier:
    def __init__(
        self,
        *,
        directory: InsForgeIdentityDirectory,
        jwks_url: str,
        issuer: str,
        audience: str,
        jwks_loader: Callable[[], Mapping[str, object]] | None = None,
        cache_seconds: int = 300,
    ) -> None:
        self.directory = directory
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self.jwks_loader = jwks_loader or self._fetch_jwks
        self.cache_seconds = cache_seconds
        self._cached_jwks: Mapping[str, object] | None = None
        self._cached_until = 0.0

    def verify(self, authorization: str | None) -> InsForgeIdentity:
        token = self._bearer_token(authorization)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise jwt.InvalidTokenError
            key = self._key_for(str(header["kid"]))
            payload = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require": ["sub", "email", "role", "exp", "iss", "aud"],
                },
            )
            subject = payload["sub"]
            email = payload["email"]
            if (
                not isinstance(subject, str)
                or not subject
                or not isinstance(email, str)
                or not email
                or payload["role"] != "authenticated"
            ):
                raise jwt.InvalidTokenError
            user = self.directory.find_user(subject)
            if user is None or user.email.casefold() != email.casefold():
                raise jwt.InvalidTokenError
        except AuthenticationFailure:
            raise
        except Exception as error:
            raise AuthenticationFailure("AUTH_TOKEN_INVALID", 401) from error

        if not user.email_verified:
            raise AuthenticationFailure("AUTH_EMAIL_UNVERIFIED", 403)
        return InsForgeIdentity(subject=user.subject, email=user.email)

    @staticmethod
    def _bearer_token(authorization: str | None) -> str:
        if authorization is None:
            raise AuthenticationFailure("AUTH_TOKEN_REQUIRED", 401)
        scheme, separator, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not separator or not token or " " in token:
            raise AuthenticationFailure("AUTH_TOKEN_INVALID", 401)
        return token

    def _key_for(self, kid: str) -> object:
        for refresh in (False, True):
            jwks = self._load_jwks(force=refresh)
            keys = jwks.get("keys")
            if not isinstance(keys, list):
                break
            for candidate in keys:
                if (
                    isinstance(candidate, dict)
                    and candidate.get("kid") == kid
                    and candidate.get("alg") == "RS256"
                    and candidate.get("kty") == "RSA"
                    and candidate.get("use", "sig") == "sig"
                ):
                    return jwt.PyJWK.from_dict(candidate).key
        raise jwt.InvalidTokenError

    def _load_jwks(self, *, force: bool) -> Mapping[str, object]:
        now = time.monotonic()
        if not force and self._cached_jwks is not None and now < self._cached_until:
            return self._cached_jwks
        jwks = self.jwks_loader()
        self._cached_jwks = jwks
        self._cached_until = now + self.cache_seconds
        return jwks

    def _fetch_jwks(self) -> Mapping[str, object]:
        with urllib.request.urlopen(self.jwks_url, timeout=3) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("invalid JWKS")
        return payload


def build_identity_verifier(
    *,
    database_url: str | None,
    jwks_url: str,
    issuer: str,
    audience: str,
) -> IdentityVerifier:
    if not database_url:
        raise RuntimeError("THESISTRACE_DATABASE_URL is required for InsForge authentication")
    return InsForgeJwtVerifier(
        directory=PostgresInsForgeIdentityDirectory(database_url),
        jwks_url=jwks_url,
        issuer=issuer,
        audience=audience,
    )
