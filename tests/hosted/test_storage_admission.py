import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.hosted.object_store import RemoteObjectStore
from thesistrace.hosted.object_store_service import create_object_store_app
from thesistrace.quota import QuotaExceededError
from thesistrace.storage import MetadataStore
from thesistrace.storage_admission import (
    DiskPressurePolicy,
    StorageAdmissionError,
    publication_storage_objects,
)

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("THESISTRACE_TEST_DATABASE_URL")
TOKENS = {
    "api": "api-storage-token",
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


def test_object_store_rejects_growth_but_keeps_reads_and_cleanup(
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
    objects = RemoteObjectStore(
        "http://object-store",
        TOKENS["api"],
        client=client,
    )
    try:
        prior = objects.put_json({"prior": "truth"})

        used[0] = 699
        with caplog.at_level(logging.WARNING):
            objects.put_json({})
        assert "persistent disk warning threshold reached" in caplog.text

        used[0] = 790
        with pytest.raises(StorageAdmissionError) as private_rejected:
            objects.put_json({"private": 1})
        assert private_rejected.value.limit == 80

        assert objects.read_json(str(prior["sha256"])) == {"prior": "truth"}

        used[0] = 0
        with pytest.raises(StorageAdmissionError):
            with objects.stage(
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
        assert objects.staged_publication_ids(prefix="run_") == []
        assert objects.read_json(str(prior["sha256"])) == {"prior": "truth"}
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
