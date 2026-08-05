from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.datasets import DatasetPublisher
from thesistrace.objects import ImmutableObjectStore
from thesistrace.publication_object_index import publication_storage_objects
from thesistrace.resource_deletion import (
    ResourceDeletionError,
    ResourceDeletionService,
)
from thesistrace.storage import MetadataStore


def seeded_run(
    tmp_path: Path,
    *,
    status: str = "succeeded",
) -> tuple[MetadataStore, ImmutableObjectStore, str]:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    run_id = "run_delete"
    manifest = {
        "id": "result_delete",
        "research_run_id": run_id,
        "payload": objects.put_json({"value": 1}),
    }
    objects.put_manifest("result_delete", manifest)
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id, status, created_at, updated_at, completed_at,
                result_bundle_id, result_manifest_sha256
            ) VALUES (?, ?, '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00', ?, ?)
            """,
            (run_id, status, "result_delete", "a" * 64),
        )
        store.commit_private_storage_references(
            connection,
            resource_kind="research_run",
            resource_id=run_id,
            objects=publication_storage_objects(manifest),
        )
    return store, objects, run_id


def test_terminal_research_run_is_unreadable_before_cleanup_completes(
    tmp_path: Path,
) -> None:
    store, objects, run_id = seeded_run(tmp_path)
    service = ResourceDeletionService(store, objects)

    tombstone = service.delete_research_run(run_id, actor="subject-1")

    assert tombstone["resource_kind"] == "research_run"
    assert tombstone["resource_id"] == run_id
    assert tombstone["actor"] == "subject-1"
    assert store.research_run(run_id) is None
    assert store.pending_resource_cleanups() == []
    assert not (objects.root / "manifests" / "result_delete.json").exists()
    assert list((objects.root / "sha256").rglob("*.json")) == []


def test_nonterminal_or_retained_research_run_cannot_be_deleted(
    tmp_path: Path,
) -> None:
    store, objects, run_id = seeded_run(
        tmp_path,
        status="running",
    )
    service = ResourceDeletionService(store, objects)

    with pytest.raises(ResourceDeletionError) as nonterminal:
        service.delete_research_run(run_id, actor="subject-1")
    assert nonterminal.value.reason_code == "RESOURCE_NOT_TERMINAL"
    assert store.research_run(run_id) is not None

    with store.connect() as connection:
        connection.execute(
            "UPDATE research_runs SET status = 'succeeded' WHERE id = ?",
            (run_id,),
        )
        connection.execute(
            """
            INSERT INTO daily_tracks (
                id, seed_run_id, status, created_at, fencing_token
            ) VALUES ('track_retained', ?, 'stopped',
                      '2026-07-31T00:00:00+00:00', 2)
            """,
            (run_id,),
        )

    with pytest.raises(ResourceDeletionError) as retained:
        service.delete_research_run(run_id, actor="subject-1")
    assert retained.value.reason_code == "RESOURCE_RETAINED"
    assert store.research_run(run_id) is not None


def test_cleanup_failure_is_durable_and_retryable(tmp_path: Path) -> None:
    store, objects, run_id = seeded_run(tmp_path)
    original_delete = objects.delete_storage_object
    failures = [True]

    def fail_once(object_key: str) -> bool:
        if failures.pop():
            raise OSError("volume unavailable")
        return original_delete(object_key)

    objects.delete_storage_object = fail_once  # type: ignore[method-assign]
    service = ResourceDeletionService(store, objects)

    service.delete_research_run(run_id, actor="subject-1")

    pending = store.pending_resource_cleanups()
    assert len(pending) == 1
    assert pending[0]["attempt_count"] == 1
    objects.delete_storage_object = original_delete  # type: ignore[method-assign]

    assert service.reconcile_pending() == [
        {"tombstone_id": pending[0]["tombstone_id"], "status": "completed"}
    ]
    assert store.pending_resource_cleanups() == []


def test_shared_content_remains_until_last_live_reference_is_deleted(
    tmp_path: Path,
) -> None:
    store, objects, first_run_id = seeded_run(tmp_path)
    shared = objects.put_json({"shared": True})
    first_manifest = {
        "id": "result_shared_first",
        "payload": shared,
    }
    second_manifest = {
        "id": "result_shared_second",
        "payload": shared,
    }
    objects.put_manifest("result_shared_first", first_manifest)
    objects.put_manifest("result_shared_second", second_manifest)
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id, status, created_at, updated_at, completed_at,
                result_bundle_id, result_manifest_sha256
            ) VALUES ('run_shared_second', 'succeeded',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      'result_shared_second', ?)
            """,
            ("c" * 64,),
        )
        store.commit_private_storage_references(
            connection,
            resource_kind="research_run",
            resource_id=first_run_id,
            objects=publication_storage_objects(first_manifest),
        )
        store.commit_private_storage_references(
            connection,
            resource_kind="research_run",
            resource_id="run_shared_second",
            objects=publication_storage_objects(second_manifest),
        )
    service = ResourceDeletionService(store, objects)

    service.delete_research_run(first_run_id, actor="subject-1")
    assert objects.read_json(str(shared["sha256"])) == {"shared": True}

    service.delete_research_run("run_shared_second", actor="subject-1")
    with pytest.raises(FileNotFoundError):
        objects.read_json(str(shared["sha256"]))


def test_dataset_publication_indexes_shared_content_before_run_cleanup(
    tmp_path: Path,
) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    release, created = DatasetPublisher(store, objects).bootstrap(
        "bootstrap-shared",
        "v1",
    )
    assert created is True
    release_objects = release["objects"]
    assert isinstance(release_objects, list)
    shared = release_objects[0]
    assert isinstance(shared, dict)
    run_manifest = {"id": "result_dataset_shared", "payload": shared}
    objects.put_manifest("result_dataset_shared", run_manifest)
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id, status, created_at, updated_at, completed_at,
                result_bundle_id, result_manifest_sha256
            ) VALUES ('run_dataset_shared', 'succeeded',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      'result_dataset_shared', ?)
            """,
            ("9" * 64,),
        )
        store.commit_private_storage_references(
            connection,
            resource_kind="research_run",
            resource_id="run_dataset_shared",
            objects=publication_storage_objects(run_manifest),
        )

    ResourceDeletionService(store, objects).delete_research_run(
        "run_dataset_shared",
        actor="subject-1",
    )

    assert store.latest_dataset_release() == release
    assert objects.read_json(str(shared["sha256"]))


def test_preindex_resource_is_not_deleted_until_storage_reconciliation(
    tmp_path: Path,
) -> None:
    store = MetadataStore(tmp_path / "metadata.sqlite3")
    store.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    payload = objects.put_json({"legacy": True})
    manifest = {"id": "result_legacy", "payload": payload}
    objects.put_manifest("result_legacy", manifest)
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id, status, created_at, updated_at, completed_at,
                result_bundle_id, result_manifest_sha256
            ) VALUES ('run_legacy', 'succeeded',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      'result_legacy', ?)
            """,
            ("d" * 64,),
        )
    service = ResourceDeletionService(store, objects)

    with pytest.raises(ResourceDeletionError) as unindexed:
        service.delete_research_run("run_legacy", actor="subject-1")

    assert unindexed.value.reason_code == "RESOURCE_STORAGE_UNINDEXED"
    assert store.research_run("run_legacy") is not None
    assert (objects.root / "manifests" / "result_legacy.json").exists()
    assert objects.read_json(str(payload["sha256"])) == {"legacy": True}


def test_publication_waits_for_cleanup_before_reusing_deleted_digest(
    tmp_path: Path,
) -> None:
    store, objects, run_id = seeded_run(tmp_path)
    shared_payload = objects.put_json({"value": 1})
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id, status, created_at, updated_at, completed_at,
                result_bundle_id, result_manifest_sha256
            ) VALUES ('run_publication_race', 'succeeded',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      'result_publication_race', ?)
            """,
            ("e" * 64,),
        )
    entered_delete = Event()
    allow_delete = Event()
    publication_completed = Event()
    errors: list[BaseException] = []
    original_delete = objects.delete_storage_object

    def blocked_delete(object_key: str) -> bool:
        if object_key == f"sha256:{shared_payload['sha256']}":
            entered_delete.set()
            if not allow_delete.wait(timeout=5):
                raise TimeoutError("test did not release object cleanup")
        return original_delete(object_key)

    objects.delete_storage_object = blocked_delete  # type: ignore[method-assign]
    service = ResourceDeletionService(store, objects)

    def cleanup() -> None:
        try:
            service.delete_research_run(run_id, actor="subject-1")
        except BaseException as error:
            errors.append(error)

    def publish() -> None:
        try:
            with store.storage_mutation_fence():
                republished = objects.put_json({"value": 1})
                republished_manifest = {
                    "id": "result_publication_race",
                    "payload": republished,
                }
                objects.put_manifest(
                    "result_publication_race",
                    republished_manifest,
                )
                with store.connect() as connection:
                    store.commit_private_storage_references(
                        connection,
                        resource_kind="research_run",
                        resource_id="run_publication_race",
                        objects=publication_storage_objects(republished_manifest),
                    )
            publication_completed.set()
        except BaseException as error:
            errors.append(error)

    cleanup_thread = Thread(target=cleanup)
    cleanup_thread.start()
    assert entered_delete.wait(timeout=5)
    publication_thread = Thread(target=publish)
    publication_thread.start()
    assert not publication_completed.wait(timeout=0.1)
    allow_delete.set()
    cleanup_thread.join(timeout=5)
    publication_thread.join(timeout=5)
    objects.delete_storage_object = original_delete  # type: ignore[method-assign]

    assert not cleanup_thread.is_alive()
    assert not publication_thread.is_alive()
    assert errors == []
    assert publication_completed.is_set()
    assert objects.read_json(str(shared_payload["sha256"])) == {"value": 1}


def test_concurrent_tombstone_cleanups_do_not_orphan_shared_content(
    tmp_path: Path,
) -> None:
    store, objects, first_run_id = seeded_run(tmp_path)
    shared = objects.put_json({"shared-race": True})
    first_manifest = {"id": "result_race_first", "payload": shared}
    second_manifest = {"id": "result_race_second", "payload": shared}
    objects.put_manifest("result_race_first", first_manifest)
    objects.put_manifest("result_race_second", second_manifest)
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO research_runs (
                id, status, created_at, updated_at, completed_at,
                result_bundle_id, result_manifest_sha256
            ) VALUES ('run_race_second', 'succeeded',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      '2026-07-31T00:00:00+00:00',
                      'result_race_second', ?)
            """,
            ("f" * 64,),
        )
        store.commit_private_storage_references(
            connection,
            resource_kind="research_run",
            resource_id=first_run_id,
            objects=publication_storage_objects(first_manifest),
        )
        store.commit_private_storage_references(
            connection,
            resource_kind="research_run",
            resource_id="run_race_second",
            objects=publication_storage_objects(second_manifest),
        )
    with store.storage_mutation_fence():
        first = store.request_resource_deletion(
            resource_kind="research_run",
            resource_id=first_run_id,
            actor="subject-1",
            deleted_at="2026-07-31T01:00:00+00:00",
        )
        second = store.request_resource_deletion(
            resource_kind="research_run",
            resource_id="run_race_second",
            actor="subject-1",
            deleted_at="2026-07-31T01:00:01+00:00",
        )
    assert first is not None and second is not None
    service = ResourceDeletionService(store, objects)
    start = Event()
    errors: list[BaseException] = []

    def reconcile(tombstone_id: str) -> None:
        try:
            start.wait(timeout=5)
            service.reconcile_pending(tombstone_id=tombstone_id)
        except BaseException as error:
            errors.append(error)

    threads = [
        Thread(target=reconcile, args=(str(first["id"]),)),
        Thread(target=reconcile, args=(str(second["id"]),)),
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert store.pending_resource_cleanups() == []
    with pytest.raises(FileNotFoundError):
        objects.read_json(str(shared["sha256"]))
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM storage_references").fetchone()[0] == 0


def test_delete_api_distinguishes_conflict_and_immediate_absence(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    store, _objects, run_id = seeded_run(
        tmp_path,
        status="running",
    )
    with TestClient(create_app(settings)) as client:
        conflict = client.delete(f"/api/v1/research-runs/{run_id}")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["reason_code"] == ("RESOURCE_NOT_TERMINAL")

        with store.connect() as connection:
            connection.execute(
                "UPDATE research_runs SET status = 'cancelled' WHERE id = ?",
                (run_id,),
            )
        deleted = client.delete(f"/api/v1/research-runs/{run_id}")
        assert deleted.status_code == 202
        assert deleted.json()["resource_id"] == run_id
        assert client.get(f"/api/v1/research-runs/{run_id}").status_code == 404
        assert client.delete(f"/api/v1/research-runs/{run_id}").status_code == 404
