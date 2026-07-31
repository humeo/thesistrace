from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.config import Settings
from thesistrace.provisioning import ProductIdentity, ProvisioningResult


class AcceptedIdentityVerifier:
    def verify(self, authorization: str | None) -> InsForgeIdentity:
        assert authorization == "Bearer accepted"
        return InsForgeIdentity(
            subject="subject-rate-limit",
            email="rate-limit@example.test",
        )


class ProvisionedRegistrationService:
    identity = ProductIdentity(
        user_id="user-rate-limit",
        workspace_id="workspace-rate-limit",
        insforge_subject="subject-rate-limit",
        normalized_email="rate-limit@example.test",
    )

    def resolve_identity(self, insforge_subject: str) -> ProductIdentity | None:
        return self.identity if insforge_subject == self.identity.insforge_subject else None

    def provision(self, _identity: InsForgeIdentity) -> ProvisioningResult:
        return ProvisioningResult(
            invitation_id="invitation-rate-limit",
            identity=self.identity,
            created=False,
        )


def rate_settings(
    tmp_path: Path,
    *,
    user_limit: int,
    workspace_limit: int,
    mutation_limit: int,
) -> Settings:
    return Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
        auth_mode="insforge",
        api_rate_limit_window_seconds=60,
        api_user_request_limit=user_limit,
        api_workspace_request_limit=workspace_limit,
        api_mutation_request_limit=mutation_limit,
    )


def client_for(settings: Settings) -> TestClient:
    return TestClient(
        create_app(
            settings,
            identity_verifier=AcceptedIdentityVerifier(),
            registration_service=ProvisionedRegistrationService(),
        )
    )


def test_authenticated_user_short_window_limit_returns_sanitized_429(
    tmp_path: Path,
) -> None:
    settings = rate_settings(
        tmp_path,
        user_limit=2,
        workspace_limit=10,
        mutation_limit=10,
    )
    with client_for(settings) as client:
        responses = [
            client.get(
                "/api/v1/workspace",
                headers={"Authorization": "Bearer accepted"},
            )
            for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]
    rejected = responses[-1]
    assert rejected.headers["Retry-After"] == "60"
    assert rejected.json() == {
        "detail": {
            "reason_code": "REQUEST_RATE_LIMITED",
            "message": "request rate limit exceeded",
            "dimension": "authenticated_user_requests",
            "retry_after_seconds": 60,
        }
    }
    assert "quota" not in rejected.text.casefold()
    assert "disk" not in rejected.text.casefold()


def test_personal_workspace_limit_is_independent_from_user_limit(
    tmp_path: Path,
) -> None:
    settings = rate_settings(
        tmp_path,
        user_limit=10,
        workspace_limit=1,
        mutation_limit=10,
    )
    with client_for(settings) as client:
        accepted = client.get(
            "/api/v1/workspace",
            headers={"Authorization": "Bearer accepted"},
        )
        rejected = client.get(
            "/api/v1/workspace",
            headers={"Authorization": "Bearer accepted"},
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 429
    assert rejected.json()["detail"]["dimension"] == (
        "personal_workspace_requests"
    )


def test_state_changes_have_a_stricter_authenticated_limit(
    tmp_path: Path,
) -> None:
    settings = rate_settings(
        tmp_path,
        user_limit=10,
        workspace_limit=10,
        mutation_limit=1,
    )
    with client_for(settings) as client:
        first = client.post(
            "/api/v1/provision",
            headers={"Authorization": "Bearer accepted"},
        )
        rejected = client.post(
            "/api/v1/provision",
            headers={"Authorization": "Bearer accepted"},
        )

    assert first.status_code == 200
    assert rejected.status_code == 429
    assert rejected.json()["detail"]["dimension"] == (
        "authenticated_state_changes"
    )
