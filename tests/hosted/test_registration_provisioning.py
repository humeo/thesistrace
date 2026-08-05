import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.capacity import CapacityQualificationService
from thesistrace.config import Settings
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import apply_migrations
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.launch import LaunchQualificationService, launch_attestation
from thesistrace.management import (
    HOSTED_TUSHARE_SCOPE,
    SourceAuthorizationService,
)
from thesistrace.operator import run
from thesistrace.provisioning import (
    ProductIdentity,
    ProvisioningError,
    ProvisioningResult,
    RegistrationService,
)

ROOT = Path(__file__).resolve().parents[2]
LAUNCH_ATTESTATION_KEY = b"registration-launch-attestation-key"


class OpenSourceGate:
    def __init__(self, authorized: bool) -> None:
        self.authorized = authorized

    def is_authorized(self) -> bool:
        return self.authorized


class OpenCapacityGate:
    def __init__(self, qualified: bool = True) -> None:
        self.qualified = qualified

    def is_qualified(self) -> bool:
        return self.qualified


class OpenLaunchGate(OpenCapacityGate):
    pass


class RecordingStore:
    def __init__(self) -> None:
        self.issued: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []
        self.invitations: dict[str, dict[str, object]] = {}

    def issue_invitation(self, **values) -> dict[str, object]:
        self.issued.append(values)
        invitation = {"id": "invite_test", "state": "issued", **values}
        self.invitations["invite_test"] = invitation
        return invitation

    def record_invitation_rejection(self, **values) -> None:
        self.rejections.append(values)

    def revoke_invitation(self, **values) -> dict[str, object]:
        invitation = self.invitations[str(values["invitation_id"])]
        invitation["state"] = "revoked"
        return invitation

    def invitation(self, invitation_id: str) -> dict[str, object] | None:
        return self.invitations.get(invitation_id)


class VerifiedIdentity:
    def __init__(self, identity: InsForgeIdentity) -> None:
        self.identity = identity

    def verify(self, authorization: str | None) -> InsForgeIdentity:
        assert authorization == "Bearer valid"
        return self.identity


class ApiRegistrationService:
    def __init__(self, *, eligible: bool = True) -> None:
        self.eligible = eligible
        self.mapping: ProductIdentity | None = None

    def resolve_identity(self, subject: str) -> ProductIdentity | None:
        if self.mapping is None or self.mapping.insforge_subject != subject:
            return None
        return self.mapping

    def provision(self, identity: InsForgeIdentity) -> ProvisioningResult:
        if not self.eligible:
            raise ProvisioningError(
                "INVITATION_NOT_ELIGIBLE",
                "a matching invitation is required",
            )
        created = self.mapping is None
        if self.mapping is None:
            self.mapping = ProductIdentity(
                user_id="user_1",
                workspace_id="workspace_1",
                insforge_subject=identity.subject,
                normalized_email=identity.email.casefold(),
            )
        return ProvisioningResult(
            invitation_id="invite_1",
            identity=self.mapping,
            created=created,
        )


def test_invitation_issue_normalizes_email_and_requires_open_source_gate() -> None:
    store = RecordingStore()
    now = datetime(2026, 7, 31, tzinfo=UTC)
    service = RegistrationService(
        store=store,
        source_authorization=OpenSourceGate(False),
        capacity_qualification=OpenCapacityGate(),
        launch_qualification=OpenLaunchGate(),
    )

    with pytest.raises(ProvisioningError, match="authorization") as closed:
        service.issue_invitation(
            actor="operator-1",
            email=" Researcher@Example.COM ",
            expires_at=now + timedelta(days=1),
            now=now,
        )

    assert closed.value.reason_code == "SOURCE_AUTHORIZATION_REQUIRED"
    assert store.issued == []
    assert store.rejections[-1]["reason_code"] == "SOURCE_AUTHORIZATION_REQUIRED"
    assert "email" not in store.rejections[-1]

    service.source_authorization.authorized = True
    invitation = service.issue_invitation(
        actor=" operator-1 ",
        email=" Researcher@Example.COM ",
        expires_at=now + timedelta(days=1),
        now=now,
    )
    assert invitation["normalized_email"] == "researcher@example.com"
    assert invitation["actor"] == "operator-1"


def test_invitation_issue_requires_a_passing_capacity_gate() -> None:
    store = RecordingStore()
    now = datetime(2026, 7, 31, tzinfo=UTC)
    service = RegistrationService(
        store=store,
        source_authorization=OpenSourceGate(True),
        capacity_qualification=OpenCapacityGate(False),
        launch_qualification=OpenLaunchGate(),
    )

    with pytest.raises(ProvisioningError) as closed:
        service.issue_invitation(
            actor="operator-1",
            email="researcher@example.com",
            expires_at=now + timedelta(days=1),
            now=now,
        )

    assert closed.value.reason_code == "CAPACITY_QUALIFICATION_REQUIRED"
    assert store.issued == []
    assert store.rejections[-1]["reason_code"] == (
        "CAPACITY_QUALIFICATION_REQUIRED"
    )


def test_invitation_issue_requires_a_passing_launch_gate() -> None:
    store = RecordingStore()
    now = datetime(2026, 7, 31, tzinfo=UTC)
    service = RegistrationService(
        store=store,
        source_authorization=OpenSourceGate(True),
        capacity_qualification=OpenCapacityGate(),
        launch_qualification=OpenLaunchGate(False),
    )

    with pytest.raises(ProvisioningError) as closed:
        service.issue_invitation(
            actor="operator-1",
            email="researcher@example.com",
            expires_at=now + timedelta(days=1),
            now=now,
        )

    assert closed.value.reason_code == "LAUNCH_QUALIFICATION_REQUIRED"
    assert store.issued == []
    assert store.rejections[-1]["reason_code"] == "LAUNCH_QUALIFICATION_REQUIRED"


def test_invalid_email_and_nonfuture_expiry_are_audited() -> None:
    store = RecordingStore()
    now = datetime(2026, 7, 31, tzinfo=UTC)
    service = RegistrationService(
        store=store,
        source_authorization=OpenSourceGate(True),
        capacity_qualification=OpenCapacityGate(),
        launch_qualification=OpenLaunchGate(),
    )

    with pytest.raises(ProvisioningError) as invalid_email:
        service.issue_invitation(
            actor="operator-1",
            email="not-an-email",
            expires_at=now + timedelta(days=1),
            now=now,
        )
    assert invalid_email.value.reason_code == "INVITATION_EMAIL_INVALID"
    assert store.rejections[-1]["reason_code"] == "INVITATION_EMAIL_INVALID"

    with pytest.raises(ProvisioningError) as invalid_expiry:
        service.issue_invitation(
            actor="operator-1",
            email="user@example.com",
            expires_at=now,
            now=now,
        )
    assert invalid_expiry.value.reason_code == "INVITATION_EXPIRY_INVALID"
    assert store.rejections[-1]["reason_code"] == "INVITATION_EXPIRY_INVALID"


def test_operator_cli_issues_inspects_and_revokes_without_an_admin_api(
    tmp_path: Path,
    capsys,
) -> None:
    store = RecordingStore()
    service = RegistrationService(
        store=store,
        source_authorization=OpenSourceGate(True),
        capacity_qualification=OpenCapacityGate(),
        launch_qualification=OpenLaunchGate(),
    )
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )

    assert (
        run(
            [
                "invitation",
                "issue",
                "--actor",
                "operator-1",
                "--email",
                "Researcher@Example.com",
                "--expires-at",
                "2099-01-01T00:00:00Z",
            ],
            settings=settings,
            registration_service=service,
        )
        == 0
    )
    assert '"id": "invite_test"' in capsys.readouterr().out
    assert (
        run(
            ["invitation", "inspect", "--invitation-id", "invite_test"],
            settings=settings,
            registration_service=service,
        )
        == 0
    )
    assert '"state": "issued"' in capsys.readouterr().out
    assert (
        run(
            [
                "invitation",
                "revoke",
                "--actor",
                "operator-1",
                "--invitation-id",
                "invite_test",
            ],
            settings=settings,
            registration_service=service,
        )
        == 0
    )
    assert '"state": "revoked"' in capsys.readouterr().out

    public_routes = {route.path for route in create_app(settings).routes}
    assert "/api/v1/invitations" not in public_routes


def test_api_provisions_once_and_then_resolves_the_same_workspace(tmp_path: Path) -> None:
    identity = InsForgeIdentity(
        subject="b6de0e96-1bc5-4985-9883-286a19226d14",
        email="researcher@example.com",
    )
    registration = ApiRegistrationService()
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        auth_mode="insforge",
    )
    app = create_app(
        settings,
        identity_verifier=VerifiedIdentity(identity),
        registration_service=registration,
    )

    with TestClient(app) as client:
        before = client.get(
            "/api/v1/session",
            headers={"Authorization": "Bearer valid"},
        )
        blocked = client.get(
            "/api/v1/workspace",
            headers={"Authorization": "Bearer valid"},
        )
        first = client.post(
            "/api/v1/provision",
            headers={"Authorization": "Bearer valid"},
        )
        retry = client.post(
            "/api/v1/provision",
            headers={"Authorization": "Bearer valid"},
        )
        after = client.get(
            "/api/v1/session",
            headers={"Authorization": "Bearer valid"},
        )

    assert before.json()["product_state"] == "non_provisioned"
    assert blocked.status_code == 403
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert retry.status_code == 200
    assert retry.json()["created"] is False
    assert retry.json()["workspace_id"] == first.json()["workspace_id"]
    assert after.json()["product_state"] == "provisioned"
    assert after.json()["workspace_id"] == first.json()["workspace_id"]


def test_api_rejects_noneligible_identity_without_mapping_detail(tmp_path: Path) -> None:
    identity = InsForgeIdentity(subject="subject-2", email="other@example.com")
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        auth_mode="insforge",
    )
    app = create_app(
        settings,
        identity_verifier=VerifiedIdentity(identity),
        registration_service=ApiRegistrationService(eligible=False),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/provision",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "reason_code": "INVITATION_NOT_ELIGIBLE",
        "message": "product provisioning is not available",
    }
    assert "email" not in response.text.lower()


TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")


def prepare_postgres() -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    SourceAuthorizationService(
        PostgresManagementStore(TEST_DATABASE_URL)
    ).record(
        actor="operator-test",
        scope=HOSTED_TUSHARE_SCOPE,
    )
    CapacityQualificationService(
        PostgresManagementStore(TEST_DATABASE_URL)
    ).record(
        actor="operator-test",
        release_bundle_id="test-release",
        evidence=passing_capacity_evidence(),
    )
    launch_evidence = passing_launch_evidence()
    record_launch(
        LaunchQualificationService(PostgresManagementStore(TEST_DATABASE_URL)),
        actor="operator-test",
        release_bundle_id="test-release",
        evidence=launch_evidence,
    )


def passing_capacity_evidence() -> dict[str, object]:
    return {
        "schema_version": "capacity-qualification-v3",
        "universe": "top3000",
        "nonworker_services": {"memory_limit_mib": 5120, "cpu_limit": 2},
        "runtime_capacity": {
            "source": "docker-info",
            "logical_cpu": 6,
            "memory_bytes": 12 * 1024**3,
        },
        "swap_used": False,
        "oom_kill": False,
        "unexpected_restart": False,
        "production_paths": {
            "parquet": True,
            "result_bundle": True,
            "working_cache": True,
            "postgresql": True,
            "object_store": True,
        },
    }


def passing_launch_evidence() -> dict[str, object]:
    checks = {
        name: True
        for name in (
            "backend",
            "browser",
            "capacity",
            "coordinated_backup",
            "data_health",
            "direct_origin_security",
            "frontend",
            "full_restore",
            "migrations",
            "postgresql_rls",
            "public_origin",
            "quantitative_health",
            "recovery_matrix",
            "resource_exhaustion_matrix",
            "source_authorization",
            "storage",
            "system_health",
        )
    }
    return {
        "schema_version": "hosted-v2-launch-v1",
        "clean_stack": True,
        "release_bundle_id": "test-release",
        "checks": checks,
        "records": {name: {"status": "passed"} for name in checks},
    }


def record_launch(
    service: LaunchQualificationService,
    *,
    actor: str,
    release_bundle_id: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    return service.record(
        actor=actor,
        release_bundle_id=release_bundle_id,
        evidence=evidence,
        attestation=launch_attestation(
            evidence,
            LAUNCH_ATTESTATION_KEY,
        ),
        attestation_key=LAUNCH_ATTESTATION_KEY,
    )


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_provisioning_is_atomic_idempotent_and_single_winner() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    now = datetime.now(UTC)
    email = f"concurrent-{now.timestamp()}@example.com"
    identity = InsForgeIdentity(
        subject=f"subject-{now.timestamp()}",
        email=email,
    )
    store = PostgresProvisioningStore(TEST_DATABASE_URL)

    invitation = store.issue_invitation(
        actor="operator-test",
        normalized_email=email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: store.provision(
                    identity=identity,
                    normalized_email=email,
                    now=now,
                ),
                range(2),
            )
        )

    assert sum(result.created for result in results) == 1
    assert {result.identity.user_id for result in results} == {
        results[0].identity.user_id
    }
    assert {result.identity.workspace_id for result in results} == {
        results[0].identity.workspace_id
    }
    assert {result.invitation_id for result in results} == {invitation["id"]}

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        user_count = connection.execute(
            """
            SELECT count(*)
            FROM thesistrace_control.product_users
            WHERE insforge_subject = %s
            """,
            (identity.subject,),
        ).fetchone()[0]
        workspace_count = connection.execute(
            """
            SELECT count(*)
            FROM thesistrace_control.personal_workspaces AS workspaces
            JOIN thesistrace_control.product_users AS users
              ON users.id = workspaces.user_id
            WHERE users.insforge_subject = %s
            """,
            (identity.subject,),
        ).fetchone()[0]
    assert user_count == 1
    assert workspace_count == 1


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_invitation_issue_is_fenced_by_latest_capacity_measurement() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    management = PostgresManagementStore(TEST_DATABASE_URL)
    failing = passing_capacity_evidence()
    failing["runtime_capacity"]["logical_cpu"] = 5
    CapacityQualificationService(management).record(
        actor="operator-test",
        release_bundle_id="test-release",
        evidence=failing,
    )
    now = datetime.now(UTC)
    store = PostgresProvisioningStore(TEST_DATABASE_URL)

    with pytest.raises(ProvisioningError) as rejected:
        store.issue_invitation(
            actor="operator-test",
            normalized_email=f"capacity-closed-{now.timestamp()}@example.com",
            expires_at=now + timedelta(hours=1),
            now=now,
        )

    assert rejected.value.reason_code == "CAPACITY_QUALIFICATION_REQUIRED"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        audit = connection.execute(
            """
            SELECT reason_code
            FROM thesistrace_control.management_audit_events
            WHERE action = 'registration_invitation.issue'
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    assert audit[0] == "CAPACITY_QUALIFICATION_REQUIRED"


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_invitation_issue_is_fenced_by_latest_launch_measurement() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    management = PostgresManagementStore(TEST_DATABASE_URL)
    failing = passing_launch_evidence()
    failing["checks"]["full_restore"] = False
    record_launch(
        LaunchQualificationService(management),
        actor="operator-test",
        release_bundle_id="test-release",
        evidence=failing,
    )
    now = datetime.now(UTC)
    store = PostgresProvisioningStore(TEST_DATABASE_URL)

    with pytest.raises(ProvisioningError) as rejected:
        store.issue_invitation(
            actor="operator-test",
            normalized_email=f"launch-closed-{now.timestamp()}@example.com",
            expires_at=now + timedelta(hours=1),
            now=now,
        )

    assert rejected.value.reason_code == "LAUNCH_QUALIFICATION_REQUIRED"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        audit = connection.execute(
            """
            SELECT reason_code
            FROM thesistrace_control.management_audit_events
            WHERE action = 'registration_invitation.issue'
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    assert audit[0] == "LAUNCH_QUALIFICATION_REQUIRED"


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_invitation_requires_qualifications_for_current_release() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    management = PostgresManagementStore(TEST_DATABASE_URL)
    CapacityQualificationService(management).record(
        actor="operator-test",
        release_bundle_id="old-release",
        evidence=passing_capacity_evidence(),
    )
    stale_launch = passing_launch_evidence()
    stale_launch["release_bundle_id"] = "old-release"
    record_launch(
        LaunchQualificationService(management),
        actor="operator-test",
        release_bundle_id="old-release",
        evidence=stale_launch,
    )
    now = datetime.now(UTC)
    store = PostgresProvisioningStore(
        TEST_DATABASE_URL,
        required_release_bundle_id="current-release",
    )

    with pytest.raises(ProvisioningError) as rejected:
        store.issue_invitation(
            actor="operator-test",
            normalized_email=f"stale-release-{now.timestamp()}@example.com",
            expires_at=now + timedelta(hours=1),
            now=now,
        )

    assert rejected.value.reason_code == "CAPACITY_QUALIFICATION_REQUIRED"


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_two_distinct_identities_cannot_consume_one_invitation() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    now = datetime.now(UTC)
    email = f"rival-{now.timestamp()}@example.com"
    identities = [
        InsForgeIdentity(subject=f"rival-a-{now.timestamp()}", email=email),
        InsForgeIdentity(subject=f"rival-b-{now.timestamp()}", email=email),
    ]
    store = PostgresProvisioningStore(TEST_DATABASE_URL)
    invitation = store.issue_invitation(
        actor="operator-test",
        normalized_email=email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )

    def consume(identity: InsForgeIdentity) -> ProvisioningResult | ProvisioningError:
        try:
            return store.provision(
                identity=identity,
                normalized_email=email,
                now=now,
            )
        except ProvisioningError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(consume, identities))

    winners = [outcome for outcome in outcomes if isinstance(outcome, ProvisioningResult)]
    losers = [outcome for outcome in outcomes if isinstance(outcome, ProvisioningError)]
    assert len(winners) == 1
    assert winners[0].created is True
    assert winners[0].invitation_id == invitation["id"]
    assert len(losers) == 1
    assert losers[0].reason_code == "INVITATION_NOT_ELIGIBLE"


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_failure_before_commit_leaves_invitation_retryable() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    now = datetime.now(UTC)
    email = f"rollback-{now.timestamp()}@example.com"
    identity = InsForgeIdentity(
        subject=f"rollback-subject-{now.timestamp()}",
        email=email,
    )
    base_store = PostgresProvisioningStore(TEST_DATABASE_URL)
    invitation = base_store.issue_invitation(
        actor="operator-test",
        normalized_email=email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )

    def fail() -> None:
        raise RuntimeError("injected pre-commit failure")

    failing_store = PostgresProvisioningStore(
        TEST_DATABASE_URL,
        before_provisioning_commit=fail,
    )
    with pytest.raises(RuntimeError, match="injected"):
        failing_store.provision(
            identity=identity,
            normalized_email=email,
            now=now,
        )

    assert base_store.invitation(str(invitation["id"]))["state"] == "issued"
    assert base_store.resolve_identity(identity.subject) is None
    retry = base_store.provision(
        identity=identity,
        normalized_email=email,
        now=now,
    )
    assert retry.created is True


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_revocation_expiry_and_failed_consumption_are_audited() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    now = datetime.now(UTC)
    store = PostgresProvisioningStore(TEST_DATABASE_URL)

    revoked_email = f"revoked-{now.timestamp()}@example.com"
    revoked = store.issue_invitation(
        actor="operator-test",
        normalized_email=revoked_email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )
    store.revoke_invitation(
        actor="operator-test",
        invitation_id=str(revoked["id"]),
        now=now,
    )
    with pytest.raises(ProvisioningError) as revoked_consumption:
        store.provision(
            identity=InsForgeIdentity(
                subject=f"revoked-subject-{now.timestamp()}",
                email=revoked_email,
            ),
            normalized_email=revoked_email,
            now=now,
        )
    assert revoked_consumption.value.reason_code == "INVITATION_NOT_ELIGIBLE"

    expired_email = f"expired-{now.timestamp()}@example.com"
    expired = store.issue_invitation(
        actor="operator-test",
        normalized_email=expired_email,
        expires_at=now + timedelta(seconds=1),
        now=now,
    )
    with pytest.raises(ProvisioningError) as expired_consumption:
        store.provision(
            identity=InsForgeIdentity(
                subject=f"expired-subject-{now.timestamp()}",
                email=expired_email,
            ),
            normalized_email=expired_email,
            now=now + timedelta(seconds=2),
        )
    assert expired_consumption.value.reason_code == "INVITATION_NOT_ELIGIBLE"
    assert store.invitation(str(expired["id"]))["state"] == "expired"

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        rows = connection.execute(
            """
            SELECT action, outcome, reason_code, details_json::text
            FROM thesistrace_control.management_audit_events
            WHERE subject_id IN (%s, %s)
            ORDER BY occurred_at, id
            """,
            (revoked["id"], expired["id"]),
        ).fetchall()
    serialized = str(rows)
    assert "registration_invitation.revoke" in serialized
    assert "registration_invitation.expire" in serialized
    assert "registration_invitation.consume" in serialized
    assert "INVITATION_NOT_ELIGIBLE" in serialized
    assert revoked_email not in serialized
    assert expired_email not in serialized


def test_registration_schema_has_single_use_and_one_workspace_constraints() -> None:
    migration = (
        ROOT
        / "deploy"
        / "hosted"
        / "migrations"
        / "0003_registration_provisioning.sql"
    ).read_text()
    assert "one_issued_invitation_per_email" in migration
    assert "insforge_subject text NOT NULL UNIQUE" in migration
    assert "normalized_email text NOT NULL UNIQUE" in migration
    assert "user_id text NOT NULL UNIQUE" in migration
    assert "state IN ('issued', 'revoked', 'expired', 'consumed')" in migration
