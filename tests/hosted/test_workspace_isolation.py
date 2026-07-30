import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.auth import InsForgeIdentity
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import apply_migrations
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.management import HOSTED_TUSHARE_SCOPE, SourceAuthorizationService
from thesistrace.objects import ImmutableObjectStore
from thesistrace.ports import LocalWorkerDispatch
from thesistrace.provisioning import RegistrationService
from thesistrace.runtime import RuntimePorts
from thesistrace.tenancy import authenticated_subject
from thesistrace.working_cache import WorkingCacheStore

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")
PRIVATE_TABLES = (
    "research_definition_drafts",
    "research_definitions",
    "research_runs",
    "execution_outbox",
    "user_compute_admissions",
    "research_run_idempotency",
    "research_run_attempts",
    "daily_tracks",
    "daily_track_activation_idempotency",
    "tracking_generations",
    "tracking_checkpoints",
    "tracking_advances",
    "tracking_advance_attempts",
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
    SourceAuthorizationService(
        PostgresManagementStore(TEST_DATABASE_URL)
    ).record(
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
                thesistrace_product.execution_outbox,
                thesistrace_product.user_compute_admissions,
                thesistrace_product.research_run_idempotency,
                thesistrace_product.research_run_attempts,
                thesistrace_product.daily_tracks,
                thesistrace_product.daily_track_activation_idempotency,
                thesistrace_product.tracking_generations,
                thesistrace_product.tracking_checkpoints,
                thesistrace_product.tracking_advances,
                thesistrace_product.tracking_advance_attempts,
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
    provision_identity(identity_a)
    provision_identity(identity_b)
    release = bootstrap_shared_release(tmp_path)
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

        assert [item["id"] for item in client.get(
            "/api/v1/research-definitions",
            headers=headers_a,
        ).json()["items"]] == [draft_a["id"]]
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
        "execution_outbox": f"outbox-{prefix}",
        "user_compute_admissions": f"run-{prefix}",
        "research_run_idempotency": f"run-key-{prefix}",
        "research_run_attempts": f"attempt-{prefix}",
        "daily_tracks": f"track-{prefix}",
        "daily_track_activation_idempotency": f"track-key-{prefix}",
        "tracking_generations": f"generation-{prefix}",
        "tracking_checkpoints": f"checkpoint-{prefix}",
        "tracking_advances": f"advance-{prefix}",
        "tracking_advance_attempts": f"advance-attempt-{prefix}",
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
            INSERT INTO thesistrace_product.execution_outbox
                (workspace_id, id, resource_kind, resource_id, status, created_at)
            VALUES (%s, %s, 'research_run', %s, 'dispatched', %s)
            """,
            (
                workspace_id,
                ids["execution_outbox"],
                ids["research_runs"],
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
            INSERT INTO thesistrace_product.daily_tracks
                (workspace_id, id, seed_run_id, definition_version_id,
                 definition_content_hash, activation_release_id, origin_session,
                 numeric_execution_contract, status, current_generation_id,
                 head_checkpoint_id, created_at)
            VALUES (%s, %s, %s, %s, 'hash', %s, '2026-01-01',
                    'numeric-v1', 'stopped', %s, %s, %s)
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
                """,
            (["thesistrace_api", "thesistrace_relay"],),
        ).fetchone()
        assert roles == ("thesistrace_api", False, False)
        relay_role = connection.execute(
            """
            SELECT rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname = 'thesistrace_relay'
            """
        ).fetchone()
        assert relay_role == (False, False)
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

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute("SET LOCAL ROLE thesistrace_api")
        connection.execute("SET LOCAL search_path = thesistrace_product, public")
        connection.execute(
            "SELECT set_config('thesistrace.workspace_id', %s, true)",
            (workspace_b,),
        )
        for table in PRIVATE_TABLES:
            count = connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            assert count == 0
        connection.rollback()

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
                if table != "execution_outbox":
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
