import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.config import Settings
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import (
    MigrationError,
    apply_migrations,
    provision_service_role_credentials,
)
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.management import HOSTED_TUSHARE_SCOPE, SourceAuthorizationService
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.provisioning import RegistrationService
from thesistrace.runtime import RuntimePorts
from thesistrace.working_cache import WorkingCacheStore

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")
PRIVATE_TABLES = (
    "research_definition_drafts",
    "research_definitions",
    "research_runs",
    "research_run_idempotency",
    "research_run_attempts",
    "daily_tracks",
    "daily_track_activation_idempotency",
    "daily_track_activation_reservations",
    "tracking_generations",
    "tracking_checkpoints",
    "tracking_advances",
    "tracking_advance_attempts",
    "tracking_equivalence_requests",
    "tracking_generation_rebuilds",
    "working_cache_deletions",
)


class OpenSourceGate:
    def is_authorized(self) -> bool:
        return True


class HeaderIdentityVerifier:
    def __init__(self, identities: dict[str, InsForgeIdentity]) -> None:
        self.identities = identities

    def verify(self, authorization: str | None) -> InsForgeIdentity:
        if authorization not in self.identities:
            raise AssertionError("test supplied an unknown token")
        return self.identities[authorization]


def prepare_postgres() -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    SourceAuthorizationService(PostgresManagementStore(TEST_DATABASE_URL)).record(
        actor="operator-isolation-test",
        scope=HOSTED_TUSHARE_SCOPE,
    )


def provision_identity(identity: InsForgeIdentity) -> str:
    assert TEST_DATABASE_URL is not None
    now = datetime.now(UTC)
    store = PostgresProvisioningStore(TEST_DATABASE_URL)
    store.issue_invitation(
        actor="operator-isolation-test",
        normalized_email=identity.email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )
    return store.provision(
        identity=identity,
        normalized_email=identity.email,
        now=now,
    ).identity.workspace_id


def truncate_product_state() -> None:
    assert TEST_DATABASE_URL is not None
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
                thesistrace_product.research_definition_drafts,
                thesistrace_product.research_definitions,
                thesistrace_product.research_runs,
                thesistrace_product.research_run_idempotency,
                thesistrace_product.research_run_attempts,
                thesistrace_product.daily_tracks,
                thesistrace_product.daily_track_activation_idempotency,
                thesistrace_product.daily_track_activation_reservations,
                thesistrace_product.tracking_generations,
                thesistrace_product.tracking_checkpoints,
                thesistrace_product.tracking_advances,
                thesistrace_product.tracking_advance_attempts,
                thesistrace_product.tracking_equivalence_requests,
                thesistrace_product.tracking_generation_rebuilds,
                thesistrace_product.working_cache_deletions,
                thesistrace_product.publication_idempotency,
                thesistrace_product.dataset_release_pointer,
                thesistrace_product.dataset_releases
            CASCADE
            """
        )


def build_hosted_app(
    tmp_path: Path,
    identities: dict[str, InsForgeIdentity],
) -> tuple[TestClient, RegistrationService]:
    assert TEST_DATABASE_URL is not None
    settings = Settings(
        metadata_path=tmp_path / "unused.sqlite3",
        object_root=tmp_path / "objects",
        working_cache_root=tmp_path / "working-cache",
        runtime_mode="hosted",
        database_url=TEST_DATABASE_URL,
        database_role="api",
        auth_mode="insforge",
    )
    metadata = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="api",
    )
    runtime = RuntimePorts(
        control_metadata=metadata,
        objects=ImmutableObjectStore(settings.object_root),
        working_cache=WorkingCacheStore(settings.working_cache_root),
        execution_dispatch=LocalWorkerDispatch(),
    )
    registration = RegistrationService(
        store=PostgresProvisioningStore(TEST_DATABASE_URL),
        source_authorization=OpenSourceGate(),
    )
    app = create_app(
        settings,
        runtime_ports=runtime,
        identity_verifier=HeaderIdentityVerifier(identities),
        registration_service=registration,
    )
    return TestClient(app), registration


@pytest.mark.parametrize(
    "passwords",
    [
        {"api": "api-password"},
        {"api": "api-password", "management": ""},
        {"api": "shared-password", "management": "shared-password"},
    ],
)
def test_service_database_credentials_reject_unsafe_sets(
    passwords: dict[str, str],
) -> None:
    with pytest.raises(MigrationError):
        provision_service_role_credentials(
            "postgresql://unused",
            passwords,
        )


def seed_private_table_graph(
    workspace_id: str,
    release_id: str,
    prefix: str,
) -> dict[str, str]:
    assert TEST_DATABASE_URL is not None
    ids = {
        "research_definition_drafts": f"draft-{prefix}",
        "research_definitions": f"definition-{prefix}",
        "research_runs": f"run-{prefix}",
        "research_run_idempotency": f"run-key-{prefix}",
        "research_run_attempts": f"attempt-{prefix}",
        "daily_tracks": f"track-{prefix}",
        "daily_track_activation_idempotency": f"track-key-{prefix}",
        "daily_track_activation_reservations": f"reservation-{prefix}",
        "tracking_generations": f"generation-{prefix}",
        "tracking_checkpoints": f"checkpoint-{prefix}",
        "tracking_advances": f"advance-{prefix}",
        "tracking_advance_attempts": f"advance-attempt-{prefix}",
        "tracking_equivalence_requests": f"equivalence-{prefix}",
        "tracking_generation_rebuilds": f"rebuild-{prefix}",
        "working_cache_deletions": f"track-{prefix}",
    }
    now = datetime.now(UTC).isoformat()
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO thesistrace_product.research_definition_drafts
                (workspace_id, id, content_json, created_at, updated_at)
            VALUES (%s, %s, '{}', %s, %s)
            """,
            (workspace_id, ids["research_definition_drafts"], now, now),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.research_definitions
                (workspace_id, id, draft_id, version, content_json,
                 content_hash, created_at)
            VALUES (%s, %s, %s, 1, '{}', 'hash', %s)
            """,
            (
                workspace_id,
                ids["research_definitions"],
                ids["research_definition_drafts"],
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.research_runs
                (workspace_id, id, definition_version_id, dataset_release_id,
                 status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'succeeded', %s, %s)
            """,
            (
                workspace_id,
                ids["research_runs"],
                ids["research_definitions"],
                release_id,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.research_run_idempotency
                (workspace_id, idempotency_key, run_id)
            VALUES (%s, %s, %s)
            """,
            (
                workspace_id,
                ids["research_run_idempotency"],
                ids["research_runs"],
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.research_run_attempts
                (workspace_id, id, run_id, ordinal, status, started_at, heartbeat_at)
            VALUES (%s, %s, %s, 1, 'succeeded', %s, %s)
            """,
            (
                workspace_id,
                ids["research_run_attempts"],
                ids["research_runs"],
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.daily_track_activation_reservations
                (workspace_id, track_id, idempotency_key, seed_run_id, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                workspace_id,
                ids["daily_track_activation_reservations"],
                f"reservation-key-{prefix}",
                ids["research_runs"],
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.daily_tracks
                (workspace_id, id, seed_run_id, definition_version_id,
                 definition_content_hash, activation_release_id, origin_session,
                 numeric_execution_contract, status, current_generation_id,
                 head_checkpoint_id, created_at)
            VALUES (%s, %s, %s, %s, 'hash', %s, '2026-01-01',
                    'numeric-v1', 'active', %s, %s, %s)
            """,
            (
                workspace_id,
                ids["daily_tracks"],
                ids["research_runs"],
                ids["research_definitions"],
                release_id,
                ids["tracking_generations"],
                ids["tracking_checkpoints"],
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.daily_track_activation_idempotency
                (workspace_id, idempotency_key, daily_track_id)
            VALUES (%s, %s, %s)
            """,
            (
                workspace_id,
                ids["daily_track_activation_idempotency"],
                ids["daily_tracks"],
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.tracking_generations
                (workspace_id, id, daily_track_id, ordinal, calculation_kernel,
                 numeric_execution_contract, basis_dataset_release_id, reason,
                 created_at)
            VALUES (%s, %s, %s, 0, 'kernel-v1', 'numeric-v1', %s,
                    'activation', %s)
            """,
            (
                workspace_id,
                ids["tracking_generations"],
                ids["daily_tracks"],
                release_id,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.tracking_checkpoints
                (workspace_id, id, daily_track_id, generation_id,
                 target_dataset_release_id, manifest_sha256, created_at)
            VALUES (%s, %s, %s, %s, %s, 'manifest', %s)
            """,
            (
                workspace_id,
                ids["tracking_checkpoints"],
                ids["daily_tracks"],
                ids["tracking_generations"],
                release_id,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.tracking_advances
                (workspace_id, id, daily_track_id, generation_id,
                 target_dataset_release_id, status, checkpoint_id,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'succeeded', %s, %s, %s)
            """,
            (
                workspace_id,
                ids["tracking_advances"],
                ids["daily_tracks"],
                ids["tracking_generations"],
                release_id,
                ids["tracking_checkpoints"],
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.tracking_advance_attempts
                (workspace_id, id, advance_id, ordinal, status, started_at)
            VALUES (%s, %s, %s, 1, 'succeeded', %s)
            """,
            (
                workspace_id,
                ids["tracking_advance_attempts"],
                ids["tracking_advances"],
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.tracking_equivalence_requests
                (workspace_id, id, daily_track_id, generation_id,
                 head_checkpoint_id, idempotency_key, status,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'succeeded', %s, %s)
            """,
            (
                workspace_id,
                ids["tracking_equivalence_requests"],
                ids["daily_tracks"],
                ids["tracking_generations"],
                ids["tracking_checkpoints"],
                f"equivalence-key-{prefix}",
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.tracking_generation_rebuilds
                (workspace_id, id, daily_track_id, calculation_kernel,
                 numeric_execution_contract, basis_generation_id,
                 basis_head_checkpoint_id, idempotency_key, status,
                 generation_id, advance_id, created_at, updated_at)
            VALUES (%s, %s, %s, 'kernel-v1', 'numeric-v1', %s, %s, %s,
                    'succeeded', %s, %s, %s, %s)
            """,
            (
                workspace_id,
                ids["tracking_generation_rebuilds"],
                ids["daily_tracks"],
                ids["tracking_generations"],
                ids["tracking_checkpoints"],
                f"rebuild-key-{prefix}",
                ids["tracking_generations"],
                ids["tracking_advances"],
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO thesistrace_product.working_cache_deletions
                (workspace_id, daily_track_id, fencing_token, status, requested_at)
            VALUES (%s, %s, 1, 'completed', %s)
            """,
            (workspace_id, ids["daily_tracks"], now),
        )
    return ids


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_service_database_credentials_are_distinct_and_role_bound() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    passwords = {
        "api": "acceptance-api-password",
        "management": "acceptance-management-password",
    }
    provision_service_role_credentials(
        TEST_DATABASE_URL,
        passwords,
    )
    roles = {
        "api": "thesistrace_api",
        "management": "thesistrace_management",
    }

    wrong_password_url = psycopg.conninfo.make_conninfo(
        TEST_DATABASE_URL,
        user=roles["api"],
        password=passwords["management"],
        connect_timeout=2,
    )
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(wrong_password_url)
    for service, role in roles.items():
        connection_url = psycopg.conninfo.make_conninfo(
            TEST_DATABASE_URL,
            user=role,
            password=passwords[service],
        )
        with psycopg.connect(connection_url) as connection:
            current = connection.execute("SELECT current_user").fetchone()[0]
        assert current == role


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_api_identity_directory_has_only_verification_column_access() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    allowed = {"id", "email", "email_verified"}
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        columns = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'auth' AND table_name = 'users'
                """
            ).fetchall()
        }
        privileges = {
            column: bool(
                connection.execute(
                    "SELECT has_column_privilege(%s, 'auth.users', %s, 'SELECT')",
                    ("thesistrace_api", column),
                ).fetchone()[0]
            )
            for column in columns
        }

    assert allowed <= columns
    assert {column for column, granted in privileges.items() if granted} == allowed


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_api_role_has_only_the_control_table_access_needed_for_provisioning() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    expected = {
        "management_audit_events": {"INSERT"},
        "personal_workspaces": {"INSERT", "SELECT"},
        "product_users": {"INSERT", "SELECT"},
        "registration_invitations": {"SELECT", "UPDATE"},
    }
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        actual = {
            table: {
                privilege
                for privilege in ("DELETE", "INSERT", "SELECT", "TRUNCATE", "UPDATE")
                if connection.execute(
                    "SELECT has_table_privilege(%s, %s, %s)",
                    (
                        "thesistrace_api",
                        f"thesistrace_control.{table}",
                        privilege,
                    ),
                ).fetchone()[0]
            }
            for table in expected
        }

    assert actual == expected
