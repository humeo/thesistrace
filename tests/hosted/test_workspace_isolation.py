import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.capacity import CapacityQualificationService
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import (
    MigrationError,
    apply_migrations,
    provision_service_role_credentials,
)
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.launch import LaunchQualificationService, launch_attestation
from thesistrace.management import HOSTED_TUSHARE_SCOPE, SourceAuthorizationService
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.provisioning import RegistrationService
from thesistrace.quota import QuotaExceededError
from thesistrace.runtime import RuntimePorts
from thesistrace.tenancy import (
    authenticated_subject,
    workspace_execution,
)
from thesistrace.tracking_operations import TrackingOperationService
from thesistrace.working_cache import WorkingCacheStore

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")
LAUNCH_ATTESTATION_KEY = b"workspace-launch-attestation-key-32"
PRIVATE_TABLES = (
    "research_definition_drafts",
    "research_definitions",
    "research_runs",
    "user_compute_admissions",
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


class OpenCapacityGate:
    def is_qualified(self) -> bool:
        return True


class OpenLaunchGate(OpenCapacityGate):
    pass


def passing_capacity_evidence() -> dict[str, object]:
    return {
        "schema_version": "capacity-qualification-v2",
        "universe": "top3000",
        "compute_workers": [
            {
                "status": "succeeded",
                "activity_attempt": 1,
                "p99_memory_mib": 600,
                "peak_memory_mib": 650,
            }
            for _index in range(4)
        ],
        "dataset_publication": {
            "status": "succeeded",
            "worker_slot": "data-1",
            "activity_attempt": 1,
        },
        "nonworker_services": {"memory_limit_mib": 5120, "cpu_limit": 2},
        "runtime_capacity": {
            "source": "docker-info",
            "logical_cpu": 6,
            "memory_bytes": 12 * 1024**3,
        },
        "swap_used": False,
        "oom_kill": False,
        "unexpected_restart": False,
        "missing_heartbeat": False,
        "duplicate_publication": False,
        "incorrect_result": False,
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
    SourceAuthorizationService(
        PostgresManagementStore(TEST_DATABASE_URL)
    ).record(
        actor="operator-isolation-test",
        scope=HOSTED_TUSHARE_SCOPE,
    )
    CapacityQualificationService(
        PostgresManagementStore(TEST_DATABASE_URL)
    ).record(
        actor="operator-isolation-test",
        release_bundle_id="test-release",
        evidence=passing_capacity_evidence(),
    )
    launch_evidence = passing_launch_evidence()
    LaunchQualificationService(PostgresManagementStore(TEST_DATABASE_URL)).record(
        actor="operator-isolation-test",
        release_bundle_id="test-release",
        evidence=launch_evidence,
        attestation=launch_attestation(
            launch_evidence,
            LAUNCH_ATTESTATION_KEY,
        ),
        attestation_key=LAUNCH_ATTESTATION_KEY,
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
                thesistrace_product.user_compute_admissions,
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
        capacity_qualification=OpenCapacityGate(),
        launch_qualification=OpenLaunchGate(),
    )
    app = create_app(
        settings,
        runtime_ports=runtime,
        identity_verifier=HeaderIdentityVerifier(identities),
        registration_service=registration,
    )
    return TestClient(app), registration


def bootstrap_shared_release(tmp_path: Path) -> dict[str, object]:
    assert TEST_DATABASE_URL is not None
    publisher = DatasetPublisher(
        PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="data",
        ),
        ImmutableObjectStore(tmp_path / "objects"),
    )
    release, created = publisher.bootstrap(
        f"isolation-{uuid4().hex}",
        "v1",
    )
    assert created is True
    return release


@pytest.mark.parametrize(
    "passwords",
    [
        {
            "api": "api-password",
            "relay": "relay-password",
            "data": "data-password",
        },
        {
            "api": "api-password",
            "relay": "",
            "data": "data-password",
            "compute": "compute-password",
            "health": "health-password",
        },
        {
            "api": "shared-password",
            "relay": "relay-password",
            "data": "data-password",
            "compute": "shared-password",
            "health": "health-password",
        },
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


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_release_path_lookup_returns_only_the_next_release() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    truncate_product_state()
    suffix = uuid4().hex[:8]
    release_ids = [
        f"release-root-{suffix}",
        f"release-middle-{suffix}",
        f"release-target-{suffix}",
    ]
    predecessor: str | None = None
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        for ordinal, release_id in enumerate(release_ids):
            connection.execute(
                """
                INSERT INTO thesistrace_product.dataset_releases
                    (id, manifest_json, created_at)
                VALUES (%s, %s, %s)
                """,
                (
                    release_id,
                    json.dumps(
                        {
                            "id": release_id,
                            "predecessor_id": predecessor,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    f"2026-01-0{ordinal + 1}T00:00:00+00:00",
                ),
            )
            predecessor = release_id
    store = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="compute",
    )

    next_release = store.next_dataset_release_on_path(
        release_ids[0],
        release_ids[2],
    )

    assert next_release is not None
    assert next_release["id"] == release_ids[1]
    assert (
        store.next_dataset_release_on_path(
            release_ids[2],
            release_ids[0],
        )
        is None
    )


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_two_users_have_private_research_and_the_same_bounded_dataset_view(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    truncate_product_state()
    suffix = uuid4().hex
    identity_a = InsForgeIdentity(
        subject=f"subject-a-{suffix}",
        email=f"user-a-{suffix}@example.com",
    )
    identity_b = InsForgeIdentity(
        subject=f"subject-b-{suffix}",
        email=f"user-b-{suffix}@example.com",
    )
    workspace_a = provision_identity(identity_a)
    provision_identity(identity_b)
    release = bootstrap_shared_release(tmp_path)
    graph_a = seed_private_table_graph(
        workspace_a,
        str(release["id"]),
        f"public-a-{suffix}",
    )
    client, _registration = build_hosted_app(
        tmp_path,
        {
            "Bearer user-a": identity_a,
            "Bearer user-b": identity_b,
        },
    )
    headers_a = {"Authorization": "Bearer user-a"}
    headers_b = {"Authorization": "Bearer user-b"}

    with client:
        draft_a = client.post(
            "/api/v1/research-definitions",
            headers=headers_a,
            json={"name": "private-a"},
        ).json()
        draft_b = client.post(
            "/api/v1/research-definitions",
            headers=headers_b,
            json={"name": "private-b"},
        ).json()

        assert set(item["id"] for item in client.get(
            "/api/v1/research-definitions",
            headers=headers_a,
        ).json()["items"]) == {
            graph_a["research_definition_drafts"],
            draft_a["id"],
        }
        assert [item["id"] for item in client.get(
            "/api/v1/research-definitions",
            headers=headers_b,
        ).json()["items"]] == [draft_b["id"]]
        assert client.get(
            f"/api/v1/research-definitions/{draft_b['id']}",
            headers=headers_a,
        ).status_code == 404
        assert client.put(
            f"/api/v1/research-definitions/{draft_b['id']}",
            headers=headers_a,
            json={"name": "stolen"},
        ).status_code == 404

        cross_workspace_operations = (
            ("get", f"/api/v1/research-runs/{graph_a['research_runs']}", None),
            (
                "get",
                f"/api/v1/research-runs/{graph_a['research_runs']}/result",
                None,
            ),
            (
                "post",
                f"/api/v1/research-runs/{graph_a['research_runs']}/cancel",
                None,
            ),
            (
                "post",
                f"/api/v1/research-runs/{graph_a['research_runs']}/rerun",
                {"headers": {"Idempotency-Key": f"cross-rerun-{suffix}"}},
            ),
            (
                "post",
                f"/api/v1/research-runs/{graph_a['research_runs']}/daily-tracks",
                {"headers": {"Idempotency-Key": f"cross-track-{suffix}"}},
            ),
            ("get", f"/api/v1/daily-tracks/{graph_a['daily_tracks']}", None),
            (
                "get",
                f"/api/v1/daily-tracks/{graph_a['daily_tracks']}"
                f"/advances/{graph_a['tracking_advances']}",
                None,
            ),
            (
                "post",
                f"/api/v1/daily-tracks/{graph_a['daily_tracks']}/stop",
                None,
            ),
            (
                "post",
                f"/api/v1/daily-tracks/{graph_a['daily_tracks']}"
                "/equivalence-requests",
                {"headers": {"Idempotency-Key": f"cross-verify-{suffix}"}},
            ),
            ("delete", f"/api/v1/daily-tracks/{graph_a['daily_tracks']}", None),
            ("delete", f"/api/v1/research-runs/{graph_a['research_runs']}", None),
        )
        for method, path, options in cross_workspace_operations:
            response = getattr(client, method)(
                path,
                headers={
                    **headers_b,
                    **((options or {}).get("headers", {})),
                },
            )
            assert response.status_code == 404, (method, path, response.text)

        assert [item["id"] for item in client.get(
            "/api/v1/research-runs",
            headers=headers_b,
        ).json()["items"]] == []
        assert [item["id"] for item in client.get(
            "/api/v1/daily-tracks",
            headers=headers_b,
        ).json()["items"]] == []

        assert client.put(
            f"/api/v1/research-definitions/{draft_a['id']}",
            headers=headers_a,
            json={"name": "updated-a"},
        ).json()["content"]["name"] == "updated-a"

        releases_a = client.get(
            "/api/v1/dataset-releases",
            headers=headers_a,
        ).json()
        releases_b = client.get(
            "/api/v1/dataset-releases",
            headers=headers_b,
        ).json()
        assert releases_a == releases_b
        assert releases_a["items"][0]["id"] == release["id"]
        serialized_release = str(releases_a).lower()
        assert "objects" not in serialized_release
        assert "sha256" not in serialized_release
        assert "path" not in serialized_release

        contract_a = client.get(
            f"/api/v1/dataset-releases/{release['id']}/data-contract",
            headers=headers_a,
        ).json()
        contract_b = client.get(
            f"/api/v1/dataset-releases/{release['id']}/data-contract",
            headers=headers_b,
        ).json()
        assert contract_a == contract_b
        assert contract_a["release_id"] == release["id"]

        assert client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={**headers_a, "Idempotency-Key": "forbidden"},
            json={"fixture": "v1"},
        ).status_code == 404
        assert client.get(
            f"/api/v1/objects/{'a' * 64}",
            headers=headers_a,
        ).status_code == 404
        assert client.get(
            "/api/v1/research-definitions?workspace_id=forged",
            headers=headers_a,
        ).status_code == 422
        assert client.post(
            "/api/v1/research-definitions",
            headers=headers_a,
            json={"name": "forged", "workspace_id": "forged"},
        ).status_code == 422


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
        "user_compute_admissions": f"run-{prefix}",
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
            INSERT INTO thesistrace_product.user_compute_admissions
                (workspace_id, resource_kind, resource_id, admitted_at, completed_at)
            VALUES (%s, 'research_run', %s, %s, %s)
            """,
            (
                workspace_id,
                ids["user_compute_admissions"],
                now,
                now,
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
def test_production_roles_and_rls_cover_every_private_table(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    truncate_product_state()
    suffix = uuid4().hex
    identity_a = InsForgeIdentity(
        subject=f"contract-a-{suffix}",
        email=f"contract-a-{suffix}@example.com",
    )
    identity_b = InsForgeIdentity(
        subject=f"contract-b-{suffix}",
        email=f"contract-b-{suffix}@example.com",
    )
    workspace_a = provision_identity(identity_a)
    workspace_b = provision_identity(identity_b)
    release = bootstrap_shared_release(tmp_path)
    ids_a = seed_private_table_graph(workspace_a, str(release["id"]), f"a-{suffix}")
    ids_b = seed_private_table_graph(workspace_b, str(release["id"]), f"b-{suffix}")

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        roles = connection.execute(
            """
            SELECT rolname, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname = ANY(%s)
            ORDER BY rolname
            """
            ,
            (
                [
                    "thesistrace_api",
                    "thesistrace_compute",
                    "thesistrace_data",
                    "thesistrace_health",
                    "thesistrace_relay",
                ],
            ),
        ).fetchall()
        assert roles == [
            ("thesistrace_api", False, False),
            ("thesistrace_compute", False, False),
            ("thesistrace_data", False, False),
            ("thesistrace_health", False, False),
            ("thesistrace_relay", False, False),
        ]
        table_contracts = connection.execute(
            """
            SELECT table_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'thesistrace_product'
              AND column_name = 'workspace_id'
            ORDER BY table_name
            """
        ).fetchall()
        assert {row[0] for row in table_contracts} == set(PRIVATE_TABLES)
        assert {row[1] for row in table_contracts} == {"NO"}
        protected_tables = connection.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
            WHERE nspname = 'thesistrace_product'
              AND relname = ANY(%s)
            """,
            (list(PRIVATE_TABLES),),
        ).fetchall()
        assert {
            row[0] for row in protected_tables if row[1] and row[2]
        } == set(PRIVATE_TABLES)

    for role in (
        "thesistrace_api",
        "thesistrace_compute",
        "thesistrace_data",
        "thesistrace_health",
        "thesistrace_relay",
    ):
        for forged_workspace in (None, workspace_b):
            with psycopg.connect(TEST_DATABASE_URL) as connection:
                connection.execute(f"SET LOCAL ROLE {role}")
                connection.execute(
                    "SET LOCAL search_path = thesistrace_product, public"
                )
                if forged_workspace is not None:
                    connection.execute(
                        "SELECT set_config('thesistrace.workspace_id', %s, true)",
                        (forged_workspace,),
                    )
                for table in PRIVATE_TABLES:
                    try:
                        with connection.transaction():
                            count = connection.execute(
                                f"SELECT count(*) FROM {table}"
                            ).fetchone()[0]
                    except (
                        psycopg.errors.InsufficientPrivilege,
                        psycopg.errors.UndefinedTable,
                    ):
                        pass
                    else:
                        assert count == 0, (
                            role,
                            forged_workspace,
                            table,
                            "read",
                        )
                    try:
                        with connection.transaction():
                            changed = connection.execute(
                                f"UPDATE {table} SET workspace_id = workspace_id"
                            ).rowcount
                    except (
                        psycopg.errors.InsufficientPrivilege,
                        psycopg.errors.UndefinedTable,
                    ):
                        pass
                    else:
                        assert changed == 0, (
                            role,
                            forged_workspace,
                            table,
                            "write",
                        )

    with authenticated_subject(identity_a.subject):
        api_store = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="api",
        )
        with api_store.connect() as connection:
            for table in PRIVATE_TABLES:
                own_id = ids_a[table]
                other_id = ids_b[table]
                identifying_column = (
                    "idempotency_key"
                    if table
                    in {
                        "research_run_idempotency",
                        "daily_track_activation_idempotency",
                    }
                    else "daily_track_id"
                    if table == "working_cache_deletions"
                    else "track_id"
                    if table == "daily_track_activation_reservations"
                    else "resource_id"
                    if table == "user_compute_admissions"
                    else "id"
                )
                own = connection.execute(
                    f"SELECT count(*) FROM {table} WHERE {identifying_column} = ?",
                    (own_id,),
                ).fetchone()[0]
                hidden = connection.execute(
                    f"SELECT count(*) FROM {table} WHERE {identifying_column} = ?",
                    (other_id,),
                ).fetchone()[0]
                assert own == 1
                assert hidden == 0
                if table not in {
                    "daily_track_activation_reservations",
                    "tracking_equivalence_requests",
                    "tracking_generation_rebuilds",
                }:
                    changed = connection.execute(
                        f"""
                        UPDATE {table}
                        SET workspace_id = workspace_id
                        WHERE {identifying_column} = ?
                        """,
                        (other_id,),
                    ).rowcount
                    assert changed == 0

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    INSERT INTO research_definition_drafts
                        (workspace_id, id, content_json, created_at, updated_at)
                    VALUES (?, 'forged', '{}', 'now', 'now')
                    """,
                    (workspace_b,),
                )

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute("SET LOCAL ROLE thesistrace_api")
        connection.execute("SET LOCAL search_path = thesistrace_product, public")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE dataset_releases
                SET created_at = created_at
                WHERE id = %s
                """,
                (release["id"],),
            )
        connection.rollback()

        connection.execute("BEGIN")
        connection.execute("SET LOCAL ROLE thesistrace_data")
        connection.execute("SET LOCAL search_path = thesistrace_product, public")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM research_definition_drafts")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_tracking_operations_share_quota_and_keep_rebuild_operator_only(
    tmp_path: Path,
) -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    truncate_product_state()
    suffix = uuid4().hex
    identity_a = InsForgeIdentity(
        subject=f"operations-a-{suffix}",
        email=f"operations-a-{suffix}@example.com",
    )
    identity_b = InsForgeIdentity(
        subject=f"operations-b-{suffix}",
        email=f"operations-b-{suffix}@example.com",
    )
    workspace_a = provision_identity(identity_a)
    workspace_b = provision_identity(identity_b)
    release = bootstrap_shared_release(tmp_path)
    ids_a = seed_private_table_graph(
        workspace_a,
        str(release["id"]),
        f"operations-a-{suffix}",
    )
    ids_b = seed_private_table_graph(
        workspace_b,
        str(release["id"]),
        f"operations-b-{suffix}",
    )
    now = datetime.now(UTC).isoformat()
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        for index in range(7):
            connection.execute(
                """
                INSERT INTO thesistrace_product.user_compute_admissions
                    (workspace_id, resource_kind, resource_id, admitted_at)
                VALUES (%s, 'research_run', %s, %s)
                """,
                (workspace_a, f"queued-run-{index}-{suffix}", now),
            )

    with authenticated_subject(identity_a.subject):
        api_store = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="api",
        )
        operations = TrackingOperationService(api_store, object())
        equivalence, created = operations.request_equivalence(
            ids_a["daily_tracks"],
            f"equivalence-{suffix}",
        )
        assert created is True
        assert equivalence["status"] == "queued"
        repeated, repeated_created = operations.request_equivalence(
            ids_a["daily_tracks"],
            f"equivalence-{suffix}",
        )
        assert repeated_created is False
        assert repeated["id"] == equivalence["id"]
        with pytest.raises(QuotaExceededError):
            operations.request_equivalence(
                ids_a["daily_tracks"],
                f"equivalence-over-quota-{suffix}",
            )
        with pytest.raises(KeyError):
            operations.request_equivalence(
                ids_b["daily_tracks"],
                f"equivalence-cross-workspace-{suffix}",
            )
        cancelled_equivalence = operations.cancel_equivalence(
            str(equivalence["id"]),
            enqueue_workflow_cancellation=True,
        )
        assert cancelled_equivalence["status"] == "cancelled"

    compute_store = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="compute",
    )
    with workspace_execution(workspace_a):
        operations = TrackingOperationService(compute_store, object())
        rebuild, created = operations.request_generation_rebuild(
            ids_a["daily_tracks"],
            calculation_kernel="kernel-v2",
            numeric_execution_contract="numeric-v1",
            idempotency_key=f"rebuild-{suffix}",
            operator_authorized=True,
        )
        assert created is True
        assert rebuild["status"] == "queued"
        cancelled_rebuild = operations.cancel_generation_rebuild(
            str(rebuild["id"]),
            enqueue_workflow_cancellation=True,
        )
        assert cancelled_rebuild["status"] == "cancelled"

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        active = connection.execute(
            """
            SELECT count(*)
            FROM thesistrace_product.user_compute_admissions
            WHERE workspace_id = %s AND completed_at IS NULL
            """,
            (workspace_a,),
        ).fetchone()[0]
        assert active == 7


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_service_database_credentials_are_distinct_and_role_bound() -> None:
    assert TEST_DATABASE_URL is not None
    prepare_postgres()
    passwords = {
        "api": "acceptance-api-password",
        "relay": "acceptance-relay-password",
        "data": "acceptance-data-password",
        "compute": "acceptance-compute-password",
        "health": "acceptance-health-password",
    }
    provision_service_role_credentials(
        TEST_DATABASE_URL,
        passwords,
    )
    roles = {
        "api": "thesistrace_api",
        "relay": "thesistrace_relay",
        "data": "thesistrace_data",
        "compute": "thesistrace_compute",
        "health": "thesistrace_health",
    }
    for service, role in roles.items():
        connection_url = psycopg.conninfo.make_conninfo(
            TEST_DATABASE_URL,
            user=role,
            password=passwords[service],
        )
        with psycopg.connect(connection_url) as connection:
            current = connection.execute(
                "SELECT current_user"
            ).fetchone()[0]
        assert current == role

    wrong_password_url = psycopg.conninfo.make_conninfo(
        TEST_DATABASE_URL,
        user=roles["compute"],
        password=passwords["data"],
        connect_timeout=2,
    )
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(wrong_password_url)


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
