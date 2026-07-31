import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesistrace.auth import InsForgeIdentity
from thesistrace.hosted.control import PostgresControlMetadataStore
from thesistrace.hosted.management import PostgresManagementStore
from thesistrace.hosted.migrations import apply_migrations
from thesistrace.hosted.object_store import RemoteObjectStore
from thesistrace.hosted.object_store_service import create_object_store_app
from thesistrace.hosted.provisioning import PostgresProvisioningStore
from thesistrace.quota import QuotaExceededError, QuotaProfileService
from thesistrace.storage import MetadataStore
from thesistrace.storage_admission import (
    DiskPressurePolicy,
    StorageAdmissionError,
    publication_storage_objects,
)
from thesistrace.tenancy import workspace_execution

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")
TOKENS = {
    "api": "api-storage-token",
    "compute": "compute-storage-token",
    "data": "data-storage-token",
}


class RejectingPrivateStorageStore(MetadataStore):
    def commit_private_storage_references(
        self,
        connection,
        *,
        resource_kind: str,
        resource_id: str,
        objects: list[dict[str, object]],
    ) -> int:
        del connection, resource_kind, resource_id, objects
        raise QuotaExceededError(
            dimension="max_private_storage_bytes",
            limit=10,
        )


def test_disk_pressure_policy_uses_projected_persistent_disk_usage() -> None:
    policy = DiskPressurePolicy(capacity_bytes=1_000)

    assert policy.evaluate(
        used_bytes=699,
        candidate_bytes=1,
        private_growth=True,
    ).warning is True

    with pytest.raises(StorageAdmissionError) as private_rejected:
        policy.evaluate(
            used_bytes=799,
            candidate_bytes=1,
            private_growth=True,
        )
    assert private_rejected.value.reason_code == "DISK_PRESSURE"
    assert private_rejected.value.limit == 80

    assert policy.evaluate(
        used_bytes=799,
        candidate_bytes=1,
        private_growth=False,
    ).projected_percent == 80

    with pytest.raises(StorageAdmissionError) as all_rejected:
        policy.evaluate(
            used_bytes=899,
            candidate_bytes=1,
            private_growth=False,
        )
    assert all_rejected.value.reason_code == "DISK_PRESSURE"
    assert all_rejected.value.limit == 90


def test_disk_pressure_policy_uses_configured_thresholds() -> None:
    policy = DiskPressurePolicy(
        capacity_bytes=1_000,
        warning_percent=60,
        private_write_rejection_percent=75,
        all_write_rejection_percent=85,
    )

    assert policy.evaluate(
        used_bytes=599,
        candidate_bytes=1,
        private_growth=True,
    ).warning is True

    with pytest.raises(StorageAdmissionError) as private_rejected:
        policy.evaluate(
            used_bytes=749,
            candidate_bytes=1,
            private_growth=True,
        )
    assert private_rejected.value.limit == 75

    with pytest.raises(StorageAdmissionError) as all_rejected:
        policy.evaluate(
            used_bytes=849,
            candidate_bytes=1,
            private_growth=False,
        )
    assert all_rejected.value.limit == 85


@pytest.mark.parametrize(
    ("warning", "private_rejection", "all_rejection"),
    [
        (0, 80, 90),
        (80, 80, 90),
        (70, 91, 90),
        (70, 80, 101),
    ],
)
def test_disk_pressure_policy_rejects_invalid_threshold_order(
    warning: int,
    private_rejection: int,
    all_rejection: int,
) -> None:
    with pytest.raises(ValueError, match="disk pressure thresholds"):
        DiskPressurePolicy(
            capacity_bytes=1_000,
            warning_percent=warning,
            private_write_rejection_percent=private_rejection,
            all_write_rejection_percent=all_rejection,
        )


def test_publication_index_counts_exact_unique_content_and_manifest_bytes() -> None:
    manifest = {
        "id": "result_storage",
        "objects": {
            "first": {"sha256": "a" * 64, "bytes": 11},
            "duplicate": {"sha256": "a" * 64, "bytes": 11},
            "second": {"sha256": "b" * 64, "bytes": 17},
        },
    }
    manifest_object = {"sha256": "c" * 64, "bytes": 23}

    indexed = publication_storage_objects(
        manifest,
        manifest_object=manifest_object,
    )

    assert [entry["object_key"] for entry in indexed] == [
        "manifest:result_storage",
        f"sha256:{'a' * 64}",
        f"sha256:{'b' * 64}",
        f"sha256:{'c' * 64}",
    ]
    assert sum(int(entry["bytes"]) for entry in indexed) == (
        len(b'{"id":"result_storage","objects":{"duplicate":{"bytes":11,'
            b'"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},'
            b'"first":{"bytes":11,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            b'aaaaaaaaaaaaaaaaaaaaaaaa"},"second":{"bytes":17,"sha256":"bbbbbbbb'
            b'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}}')
        + 11
        + 17
        + 23
    )


def test_object_store_rejects_growth_by_role_but_keeps_reads_and_cleanup(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    used = [0]
    client = TestClient(
        create_object_store_app(
            tmp_path / "objects",
            TOKENS,
            disk_capacity_bytes=1_000,
            disk_used_bytes=lambda: used[0],
        )
    )
    compute = RemoteObjectStore(
        "http://object-store",
        TOKENS["compute"],
        client=client,
    )
    data = RemoteObjectStore(
        "http://object-store",
        TOKENS["data"],
        client=client,
    )
    try:
        prior = compute.put_json({"prior": "truth"})

        used[0] = 699
        with caplog.at_level(logging.WARNING):
            data.put_json({})
        assert "persistent disk warning threshold reached" in caplog.text

        used[0] = 790
        with pytest.raises(StorageAdmissionError) as private_rejected:
            compute.put_json({"private": 1})
        assert private_rejected.value.limit == 80
        assert data.put_json({"private": 1})["bytes"] == 13

        used[0] = 890
        with pytest.raises(StorageAdmissionError) as platform_rejected:
            data.put_json({"platform": 1})
        assert platform_rejected.value.limit == 90

        assert compute.read_json(str(prior["sha256"])) == {"prior": "truth"}

        used[0] = 0
        with pytest.raises(StorageAdmissionError):
            with compute.stage(
                "run_disk_pressure",
                "attempt_disk_pressure",
                cleanup_uncommitted_payloads=True,
            ) as stage:
                candidate = stage.put_json({"candidate": True})
                manifest_object = stage.put_json({"candidate": candidate})
                stage.put_manifest(
                    "result_disk_pressure",
                    {"id": "result_disk_pressure", "candidate": candidate},
                )
                used[0] = 800
                with stage.publication(
                    manifest_sha256=str(manifest_object["sha256"])
                ):
                    pytest.fail("disk-pressure publication must not commit")

        used[0] = 950
        assert compute.staged_publication_ids(prefix="run_") == []
        assert compute.read_json(str(prior["sha256"])) == {"prior": "truth"}
    finally:
        client.close()


def test_research_result_quota_check_is_atomic_with_success_publication(
    tmp_path: Path,
) -> None:
    store = RejectingPrivateStorageStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO dataset_releases (id, manifest_json, created_at)
            VALUES ('release-storage', '{}', '2026-07-31T00:00:00+00:00')
            """
        )
    draft = store.create_research_draft({"title": "storage admission"})
    _frozen, run, created = store.freeze_definition_and_create_run(
        draft_id=str(draft["id"]),
        frozen_content={"title": "storage admission"},
        content_hash="storage-admission-hash",
        dataset_release_id="release-storage",
        idempotency_key="storage-admission-request",
    )
    assert created is True
    claimed = store.claim_research_run(str(run["id"]))
    assert claimed is not None
    attempt = claimed[1]

    with pytest.raises(QuotaExceededError):
        store.publish_research_run_success(
            run_id=str(run["id"]),
            attempt_id=str(attempt["id"]),
            result_bundle_id="result-storage",
            result_manifest_sha256="a" * 64,
            storage_objects=[{
                "object_key": f"sha256:{'a' * 64}",
                "sha256": "a" * 64,
                "bytes": 11,
                "kind": "content",
            }],
        )

    unchanged = store.research_run(str(run["id"]))
    assert unchanged is not None
    assert unchanged["status"] == "running"
    assert unchanged["result_bundle_id"] is None
    assert unchanged["result_manifest_sha256"] is None


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="THESISTRACE_TEST_DATABASE_URL is required for PostgreSQL acceptance",
)
def test_postgres_private_storage_is_exact_idempotent_and_excludes_platform() -> None:
    assert TEST_DATABASE_URL is not None
    apply_migrations(
        TEST_DATABASE_URL,
        ROOT / "deploy" / "hosted" / "migrations",
    )
    suffix = uuid4().hex
    identity = InsForgeIdentity(
        subject=f"storage-subject-{suffix}",
        email=f"storage-{suffix}@example.com",
    )
    now = datetime.now(UTC)
    provisioning = PostgresProvisioningStore(TEST_DATABASE_URL)
    provisioning.issue_invitation(
        actor="storage-test",
        normalized_email=identity.email,
        expires_at=now + timedelta(hours=1),
        now=now,
    )
    workspace_id = provisioning.provision(
        identity=identity,
        normalized_email=identity.email,
        now=now,
    ).identity.workspace_id
    QuotaProfileService(PostgresManagementStore(TEST_DATABASE_URL)).override(
        actor="storage-test",
        workspace_id=workspace_id,
        max_private_storage_bytes=10,
    )
    first = [{
        "object_key": f"sha256:{'a' * 64}",
        "sha256": "a" * 64,
        "bytes": 7,
        "kind": "content",
    }]
    second = [{
        "object_key": f"sha256:{'b' * 64}",
        "sha256": "b" * 64,
        "bytes": 5,
        "kind": "content",
    }]

    with workspace_execution(workspace_id):
        compute = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="compute",
        )
        with compute.connect() as connection:
            assert compute.commit_private_storage_references(
                connection,
                resource_kind="research_run",
                resource_id=f"run-{suffix}",
                objects=first,
            ) == 7
        with compute.connect() as connection:
            assert compute.commit_private_storage_references(
                connection,
                resource_kind="tracking_checkpoint",
                resource_id=f"checkpoint-{suffix}",
                objects=first,
            ) == 7

    data = PostgresControlMetadataStore(
        TEST_DATABASE_URL,
        database_role="data",
    )
    with data.connect() as connection:
        assert data.commit_platform_storage_references(
            connection,
            resource_kind="dataset_release",
            resource_id=f"release-{suffix}",
            objects=second,
        ) == 5

    with workspace_execution(workspace_id):
        compute = PostgresControlMetadataStore(
            TEST_DATABASE_URL,
            database_role="compute",
        )
        with pytest.raises(QuotaExceededError) as quota_rejected:
            with compute.connect() as connection:
                compute.commit_private_storage_references(
                    connection,
                    resource_kind="research_run",
                    resource_id=f"run-over-limit-{suffix}",
                    objects=second,
                )
        assert quota_rejected.value.dimension == "max_private_storage_bytes"
        assert quota_rejected.value.limit == 10

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        exact_private_bytes = connection.execute(
            """
            SELECT COALESCE(sum(stored.compressed_bytes), 0)
            FROM thesistrace_control.stored_objects AS stored
            WHERE EXISTS (
                SELECT 1
                FROM thesistrace_control.storage_references AS reference
                WHERE reference.owner_scope = 'workspace'
                  AND reference.workspace_id = %s
                  AND reference.object_key = stored.object_key
            )
            """,
            (workspace_id,),
        ).fetchone()[0]
        rejected_references = connection.execute(
            """
            SELECT count(*)
            FROM thesistrace_control.storage_references
            WHERE workspace_id = %s
              AND resource_id = %s
            """,
            (workspace_id, f"run-over-limit-{suffix}"),
        ).fetchone()[0]
    assert exact_private_bytes == 7
    assert rejected_references == 0
