import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from thesistrace.hosted.health_service import PostgresHealthSnapshotStore
from thesistrace.hosted.migrations import (
    apply_migrations,
    provision_service_role_credentials,
)

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_health_role_reads_only_bounded_global_snapshot() -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    passwords = {
        "api": "health-test-api-password",
        "relay": "health-test-relay-password",
        "data": "health-test-data-password",
        "compute": "health-test-compute-password",
        "health": "health-test-observer-password",
    }
    provision_service_role_credentials(TEST_DATABASE_URL, passwords)
    suffix = uuid4().hex[:12]
    release_id = f"health-release-{suffix}"
    publication_id = f"health-publication-{suffix}"
    manifest = {
        "id": release_id,
        "predecessor_id": None,
        "created_at": "2026-07-31T00:00:00+00:00",
        "appended_session_range": {
            "start": "2023-08-01",
            "end": "2026-07-31",
        },
        "session_count": 756,
        "instrument_count": 3000,
        "canonical_schema_version": "canonical-eod-v1",
        "canonical_tables": ["prices"],
        "schemas": [{"family": "equity.eod_price", "version": "v1"}],
        "objects": [{"sha256": "a" * 64, "bytes": 100, "kind": "canonical_partition"}],
        "manifest_sha256": "b" * 64,
    }
    health_url = psycopg.conninfo.make_conninfo(
        TEST_DATABASE_URL,
        user="thesistrace_health",
        password=passwords["health"],
    )
    with psycopg.connect(TEST_DATABASE_URL) as admin:
        old_pointer = admin.execute(
            """
            SELECT release_id
            FROM thesistrace_product.dataset_release_pointer
            WHERE singleton = 1
            """
        ).fetchone()
        try:
            admin.execute(
                """
                INSERT INTO thesistrace_product.dataset_releases
                    (id, manifest_json, created_at)
                VALUES (%s, %s, %s)
                """,
                (release_id, json.dumps(manifest), manifest["created_at"]),
            )
            admin.execute(
                """
                INSERT INTO thesistrace_product.dataset_release_pointer
                    (singleton, release_id)
                VALUES (1, %s)
                ON CONFLICT (singleton) DO UPDATE
                SET release_id = excluded.release_id
                """,
                (release_id,),
            )
            admin.execute(
                """
                INSERT INTO thesistrace_product.dataset_publications (
                    id, request_version, kind, parameters_json,
                    idempotency_key, trigger_kind, status,
                    result_release_id, result_manifest_sha256,
                    created_at, updated_at
                )
                VALUES (
                    %s, 'v1', 'fixture_bootstrap', %s, %s, 'operator',
                    'succeeded', %s, %s, %s, %s
                )
                """,
                (
                    publication_id,
                    json.dumps({"fixture": "v1"}),
                    f"health-idempotency-{suffix}",
                    release_id,
                    manifest["manifest_sha256"],
                    manifest["created_at"],
                    manifest["created_at"],
                ),
            )
            admin.commit()
            store = PostgresHealthSnapshotStore(health_url)
            assert store.ready() is True
            snapshot = store.snapshot()
            assert set(snapshot) == {"system", "data", "quantitative"}
            assert snapshot["data"]["publication_validation_succeeded"] is True
            assert snapshot["data"]["release_session_current"] is True
            assert snapshot["data"]["schema_valid"] is True
            assert snapshot["data"]["coverage_valid"] is True
            assert snapshot["data"]["lineage_valid"] is True
            serialized = json.dumps(snapshot)
            assert release_id not in serialized
            assert "workspace_" not in serialized

            with psycopg.connect(health_url) as health_connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    health_connection.execute(
                        "SELECT * FROM thesistrace_product.research_runs"
                    ).fetchall()
        finally:
            admin.rollback()
            if old_pointer is None:
                admin.execute(
                    "DELETE FROM thesistrace_product.dataset_release_pointer WHERE singleton = 1"
                )
            else:
                admin.execute(
                    """
                    UPDATE thesistrace_product.dataset_release_pointer
                    SET release_id = %s
                    WHERE singleton = 1
                    """,
                    (old_pointer[0],),
                )
            admin.execute(
                "DELETE FROM thesistrace_product.dataset_publications WHERE id = %s",
                (publication_id,),
            )
            admin.execute(
                "DELETE FROM thesistrace_product.dataset_releases WHERE id = %s",
                (release_id,),
            )
            admin.commit()
