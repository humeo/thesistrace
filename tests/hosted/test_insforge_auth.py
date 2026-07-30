import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import (
    InsForgeJwtVerifier,
    InsForgeUser,
)
from thesistrace.config import Settings

ROOT = Path(__file__).resolve().parents[2]


class MemoryIdentityDirectory:
    def __init__(self, user: InsForgeUser | None) -> None:
        self.user = user

    def find_user(self, subject: str) -> InsForgeUser | None:
        if self.user is None or self.user.subject != subject:
            return None
        return self.user


def auth_settings(tmp_path: Path) -> Settings:
    return Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        auth_mode="insforge",
    )


def key_material() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "insforge-key", "alg": "RS256", "use": "sig"})
    return private_key, {"keys": [public_jwk]}


def token(
    private_key: object,
    *,
    issuer: str = "insforge",
    audience: str = "thesistrace",
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "4d416bec-5922-49ad-944f-332b9245e56d",
            "email": "researcher@example.com",
            "role": "authenticated",
            "iss": issuer,
            "aud": audience,
            "exp": expires_at or now + timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "insforge-key"},
    )


def verifier(
    user: InsForgeUser | None,
    private_key: object,
    jwks: dict[str, object],
) -> tuple[InsForgeJwtVerifier, str]:
    return (
        InsForgeJwtVerifier(
            directory=MemoryIdentityDirectory(user),
            jwks_url="http://unused.test/.well-known/jwks.json",
            issuer="insforge",
            audience="thesistrace",
            jwks_loader=lambda: jwks,
        ),
        token(private_key),
    )


def verified_user(*, verified: bool = True) -> InsForgeUser:
    return InsForgeUser(
        subject="4d416bec-5922-49ad-944f-332b9245e56d",
        email="researcher@example.com",
        email_verified=verified,
    )


def test_valid_verified_identity_is_explicitly_non_provisioned(tmp_path: Path) -> None:
    private_key, jwks = key_material()
    identity_verifier, access_token = verifier(
        verified_user(),
        private_key,
        jwks,
    )

    with TestClient(
        create_app(auth_settings(tmp_path), identity_verifier=identity_verifier)
    ) as client:
        response = client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        workspace = client.get(
            "/api/v1/workspace",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "product_state": "non_provisioned",
        "identity": {
            "subject": "4d416bec-5922-49ad-944f-332b9245e56d",
            "email": "researcher@example.com",
        },
    }
    assert workspace.status_code == 200


def test_missing_invalid_expired_and_unverified_tokens_are_sanitized(
    tmp_path: Path,
) -> None:
    private_key, jwks = key_material()
    identity_verifier, _access_token = verifier(
        verified_user(),
        private_key,
        jwks,
    )
    expired = token(
        private_key,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    wrong_issuer = token(private_key, issuer="forged")
    wrong_audience = token(private_key, audience="another-product")

    with TestClient(
        create_app(auth_settings(tmp_path), identity_verifier=identity_verifier)
    ) as client:
        missing = client.get("/api/v1/session")
        forged = client.get(
            "/api/v1/session",
            headers={"Authorization": "Bearer forged.token.value"},
        )
        expired_response = client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {expired}"},
        )
        issuer_response = client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {wrong_issuer}"},
        )
        audience_response = client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {wrong_audience}"},
        )

    assert missing.json()["detail"] == {
        "reason_code": "AUTH_TOKEN_REQUIRED",
        "message": "authentication required",
    }
    for response in (forged, expired_response, issuer_response, audience_response):
        assert response.status_code == 401
        assert response.json()["detail"] == {
            "reason_code": "AUTH_TOKEN_INVALID",
            "message": "authentication required",
        }
        assert "mapping" not in response.text.lower()

    unverified_verifier, unverified_token = verifier(
        verified_user(verified=False),
        private_key,
        jwks,
    )
    with TestClient(
        create_app(auth_settings(tmp_path), identity_verifier=unverified_verifier)
    ) as client:
        unverified = client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {unverified_token}"},
        )
    assert unverified.status_code == 403
    assert unverified.json()["detail"] == {
        "reason_code": "AUTH_EMAIL_UNVERIFIED",
        "message": "verified email required",
    }


def test_valid_token_without_insforge_identity_is_not_product_mapping_detail(
    tmp_path: Path,
) -> None:
    private_key, jwks = key_material()
    identity_verifier, access_token = verifier(None, private_key, jwks)

    with TestClient(
        create_app(auth_settings(tmp_path), identity_verifier=identity_verifier)
    ) as client:
        response = client.get(
            "/api/v1/session",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["reason_code"] == "AUTH_TOKEN_INVALID"
    assert "user" not in response.text.lower()
    assert "mapping" not in response.text.lower()


def test_health_remains_anonymous_but_product_routes_require_auth(tmp_path: Path) -> None:
    private_key, jwks = key_material()
    identity_verifier, _access_token = verifier(
        verified_user(),
        private_key,
        jwks,
    )

    with TestClient(
        create_app(auth_settings(tmp_path), identity_verifier=identity_verifier)
    ) as client:
        health = client.get("/api/v1/health")
        product = client.get("/api/v1/workspace")

    assert health.status_code == 200
    assert product.status_code == 401


def test_public_origin_exposes_only_end_user_auth_routes() -> None:
    caddyfile = (ROOT / "deploy" / "hosted" / "Caddyfile").read_text()
    required = {
        "/api/auth/users",
        "/api/auth/sessions",
        "/api/auth/sessions/current",
        "/api/auth/refresh",
        "/api/auth/logout",
        "/api/auth/email/send-verification",
        "/api/auth/email/verify",
        "/api/auth/email/verify-link",
        "/api/auth/email/send-reset-password",
        "/api/auth/email/exchange-reset-password-token",
        "/api/auth/email/reset-password",
        "/api/auth/email/reset-password-link",
        "/api/auth/anon-key",
    }
    assert required <= set(caddyfile.split())
    assert "handle /api/auth/*" in caddyfile
    assert "respond 404" in caddyfile
    assert "@insforge_auth path /api/auth/*" not in caddyfile
    smoke = (ROOT / "scripts" / "hosted-auth-smoke.py").read_text()
    assert "/api/v1/session" in smoke
    assert "/api/auth/sessions/current" in smoke
    assert "/api/auth/email/send-reset-password" in smoke
    assert "/api/auth/config" in smoke


def test_pinned_insforge_patch_supplies_the_hosted_identity_contract() -> None:
    patch = (
        ROOT
        / "deploy"
        / "hosted"
        / "patches"
        / "insforge-v2.2.9-jwt-contract.patch"
    ).read_text()
    stack = (ROOT / "scripts" / "hosted-stack").read_text()
    assert "issuer: 'insforge'" in patch
    assert "audience: 'thesistrace'" in patch
    assert "apiRouter.get('/auth/anon-key'" in patch
    assert "apply --check" in stack
    assert "apply --reverse --check" in stack


def test_thesistrace_schema_has_no_parallel_credential_or_session_store() -> None:
    migrations = "\n".join(
        path.read_text() for path in sorted((ROOT / "deploy/hosted/migrations").glob("*.sql"))
    ).lower()
    forbidden = ("password_hash", "recovery_token", "refresh_token", "user_session")
    for term in forbidden:
        assert term not in migrations
