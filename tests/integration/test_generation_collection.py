from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import (
    CanonicalSourceBatch,
    DataCollectionError,
    DataGarbageCollector,
    DataRefreshService,
    DatasetLifecycle,
    GenerationStoreError,
    MountedGenerationStore,
)
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.source import CollectionPlan
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture


def test_collection_retains_every_live_root_and_shared_object_then_converges(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        run_pinned = _materialize(store, ordinal=1)
        track_pinned = _materialize(store, ordinal=2)
        current = _materialize(store, ordinal=3)
        candidate = _materialize(store, ordinal=4)
        retired = _materialize(store, ordinal=5)
        shared_retired = store.materialize(
            build_minimal_canonical_fixture(price_offset=3),
            prepared_at=datetime(2026, 8, 10, 1, tzinfo=UTC),
            source_name="generation-collection-test",
            source_lineage={"shared": True},
        ).manifest_sha256

        _install_head(lifecycle, run_pinned, operation_id="collection-run-pinned-head")
        run_pin = lifecycle.pin_current(
            owner_kind="research_run_attempt",
            owner_id="collection-active-attempt",
            lease_seconds=60,
        )
        _move_head(
            lifecycle,
            expected=run_pinned,
            candidate=track_pinned,
            operation_id="collection-track-pinned-head",
        )
        track_pin = lifecycle.pin_current(
            owner_kind="tracking_advance_attempt",
            owner_id="collection-active-advance",
            lease_seconds=60,
        )
        _move_head(
            lifecycle,
            expected=track_pinned,
            candidate=current,
            operation_id="collection-current-head",
        )
        lifecycle.protect_candidate(
            operation_id="collection-live-candidate",
            generation_manifest_sha256=candidate,
            lease_seconds=60,
        )

        first = DataGarbageCollector(database, tmp_path).collect(idempotency_key="collection-first")

        assert first.status == "succeeded"
        assert first.deleted_file_count > 0
        assert first.remaining_file_count == 0
        for retained in (run_pinned, track_pinned, current, candidate):
            assert store.open_generation(retained).manifest_sha256 == retained
        _assert_generation_missing(store, retired)
        _assert_generation_missing(store, shared_retired)
        assert store.open_generation(current).canonical == build_minimal_canonical_fixture(
            price_offset=3
        )

        lifecycle.release_pin(run_pin.id, owner_id=run_pin.owner_id)
        lifecycle.release_pin(track_pin.id, owner_id=track_pin.owner_id)
        lifecycle.release_candidate(operation_id="collection-live-candidate")
        second = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="collection-second"
        )
        repeated = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="collection-second"
        )
        no_change = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="collection-no-change"
        )

        assert second == repeated
        assert second.deleted_file_count > 0
        assert no_change.status == "succeeded"
        assert no_change.target_file_count == 0
        assert no_change.deleted_file_count == 0
        assert no_change.remaining_file_count == 0
        assert store.open_generation(current).manifest_sha256 == current
        _assert_generation_missing(store, run_pinned)
        _assert_generation_missing(store, track_pinned)
        _assert_generation_missing(store, candidate)
    finally:
        _clear_collection_state(database)
        database.close()


def test_invalid_retained_generation_aborts_before_any_deletion(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        head = _materialize(store, ordinal=1)
        retired = _materialize(store, ordinal=2)
        _install_head(lifecycle, head, operation_id="invalid-retained-head")
        head_manifest = tmp_path / "manifests" / "sha256" / head[:2] / f"{head}.json"
        head_manifest.unlink()

        with pytest.raises(DataCollectionError) as rejected:
            DataGarbageCollector(database, tmp_path).collect(
                idempotency_key="invalid-retained-collection"
            )

        assert rejected.value.code == "COLLECTION_ROOTS_INVALID"
        assert store.open_generation(retired).manifest_sha256 == retired
        with database.transaction() as transaction:
            assert transaction.execute(
                "SELECT count(*) AS count FROM data.collection_targets"
            ).fetchone() == {"count": 0}
    finally:
        _clear_collection_state(database)
        database.close()


def test_failed_deletion_records_progress_and_retry_does_not_widen_plan(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        head = _materialize(store, ordinal=1)
        retired = _materialize(store, ordinal=2)
        _install_head(lifecycle, head, operation_id="retry-head")
        original_delete = AddressedFileStore.delete
        deleted_once = False

        def fail_after_one(self: AddressedFileStore, path: Path) -> bool:
            nonlocal deleted_once
            if deleted_once:
                raise AddressedFileError("injected collection deletion failure")
            deleted_once = True
            return original_delete(self, path)

        monkeypatch.setattr(AddressedFileStore, "delete", fail_after_one)
        with pytest.raises(DataCollectionError) as failed:
            DataGarbageCollector(database, tmp_path).collect(idempotency_key="retry-fixed-plan")
        assert failed.value.code == "COLLECTION_FILESYSTEM_FAILURE"
        assert _collection_progress(database, "retry-fixed-plan") == {
            "status": "failed",
            "deleted_count": 1,
            "pending_count": _pending_count(database, "retry-fixed-plan"),
        }
        assert _pending_count(database, "retry-fixed-plan") > 0

        new_orphan = _materialize(store, ordinal=3)
        monkeypatch.setattr(AddressedFileStore, "delete", original_delete)
        resumed = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="retry-fixed-plan"
        )

        assert resumed.status == "succeeded"
        assert resumed.remaining_file_count == 0
        _assert_generation_missing(store, retired)
        assert store.open_generation(new_orphan).manifest_sha256 == new_orphan
        DataGarbageCollector(database, tmp_path).collect(idempotency_key="collect-later-orphan")
        _assert_generation_missing(store, new_orphan)
    finally:
        _clear_collection_state(database)
        database.close()


def test_collection_uses_the_same_fence_as_pin_release_and_head_move(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        head = _materialize(store, ordinal=1)
        next_head = _materialize(store, ordinal=2)
        _materialize(store, ordinal=3)
        _install_head(lifecycle, head, operation_id="race-head")
        first_pin = lifecycle.pin_current(
            owner_kind="research_run_attempt",
            owner_id="race-first-pin",
            lease_seconds=60,
        )
        lifecycle.protect_candidate(
            operation_id="race-next-head",
            generation_manifest_sha256=next_head,
            lease_seconds=60,
        )
        deleting = threading.Event()
        continue_deletion = threading.Event()
        original_delete = AddressedFileStore.delete

        def blocked_delete(self: AddressedFileStore, path: Path) -> bool:
            deleting.set()
            if not continue_deletion.wait(timeout=20):
                raise AssertionError("collection race was not released")
            return original_delete(self, path)

        monkeypatch.setattr(AddressedFileStore, "delete", blocked_delete)
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            collection = executor.submit(
                DataGarbageCollector(database, tmp_path).collect,
                idempotency_key="collection-race",
            )
            assert deleting.wait(timeout=20)
            pin = executor.submit(
                lifecycle.pin_current,
                owner_kind="tracking_advance_attempt",
                owner_id="race-second-pin",
                lease_seconds=60,
            )
            release = executor.submit(
                lifecycle.release_pin,
                first_pin.id,
                owner_id=first_pin.owner_id,
            )
            move = executor.submit(
                lifecycle.compare_and_swap_head,
                expected_generation_manifest_sha256=head,
                candidate_generation_manifest_sha256=next_head,
                operation_id="race-next-head",
            )
            selected = pin.result(timeout=2).generation_manifest_sha256
            release.result(timeout=2)
            assert move.result(timeout=2).generation_manifest_sha256 == next_head
            assert not collection.done()
            continue_deletion.set()
            assert collection.result(timeout=20).status == "succeeded"
        finally:
            continue_deletion.set()
            executor.shutdown(wait=True)

        assert selected in {head, next_head}
        assert store.open_generation(selected).manifest_sha256 == selected
        assert lifecycle.current_head().generation_manifest_sha256 == next_head
    finally:
        _clear_collection_state(database)
        database.close()


def test_retained_generation_validation_does_not_hold_the_lifecycle_fence(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    validating = threading.Event()
    continue_validation = threading.Event()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        head = _materialize(store, ordinal=1)
        next_head = _materialize(store, ordinal=2)
        _materialize(store, ordinal=3)
        _install_head(lifecycle, head, operation_id="validation-head")
        lifecycle.protect_candidate(
            operation_id="validation-next-head",
            generation_manifest_sha256=next_head,
            lease_seconds=60,
        )
        original_referenced_files = MountedGenerationStore.referenced_files
        blocked_once = False

        def blocked_validation(
            self: MountedGenerationStore,
            manifest_sha256: str,
        ) -> frozenset[object]:
            nonlocal blocked_once
            if not blocked_once:
                blocked_once = True
                validating.set()
                if not continue_validation.wait(timeout=20):
                    raise AssertionError("retained validation barrier was not released")
            return original_referenced_files(self, manifest_sha256)

        monkeypatch.setattr(MountedGenerationStore, "referenced_files", blocked_validation)
        with ThreadPoolExecutor(max_workers=3) as executor:
            collection = executor.submit(
                DataGarbageCollector(database, tmp_path).collect,
                idempotency_key="validation-outside-fence",
            )
            assert validating.wait(timeout=20)
            pin = lifecycle.pin_current(
                owner_kind="research_run_attempt",
                owner_id="validation-concurrent-pin",
                lease_seconds=60,
            )
            lifecycle.release_pin(pin.id, owner_id=pin.owner_id)
            moved = lifecycle.compare_and_swap_head(
                expected_generation_manifest_sha256=head,
                candidate_generation_manifest_sha256=next_head,
                operation_id="validation-next-head",
            )
            assert moved.generation_manifest_sha256 == next_head
            continue_validation.set()
            assert collection.result(timeout=20).status == "succeeded"
    finally:
        continue_validation.set()
        database.close()


def test_abandoned_collector_is_reconciled_by_the_next_operator_session(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    recovery_database: PostgresDatabase | None = None
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        head = _materialize(store, ordinal=1)
        retired = _materialize(store, ordinal=2)
        _install_head(lifecycle, head, operation_id="abandoned-head")
        original_delete = MountedGenerationStore.delete_file

        def crash_collector(
            self: MountedGenerationStore,
            reference: object,
        ) -> bool:
            del self, reference
            raise AssertionError("injected collector process loss")

        monkeypatch.setattr(MountedGenerationStore, "delete_file", crash_collector)
        with pytest.raises(AssertionError, match="process loss"):
            DataGarbageCollector(database, tmp_path).collect(idempotency_key="abandoned-collection")
        with database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT status, failure_code FROM data.collection_operations
                WHERE idempotency_key = 'abandoned-collection'
                """
            ).fetchone() == {"status": "running", "failure_code": None}

        monkeypatch.setattr(MountedGenerationStore, "delete_file", original_delete)
        recovery_database = PostgresDatabase(core_settings.database_url)
        recovery_database.open()
        recovered = DataGarbageCollector(recovery_database, tmp_path).collect(
            idempotency_key="post-crash-collection"
        )

        assert recovered.status == "succeeded"
        with recovery_database.transaction() as transaction:
            assert transaction.execute(
                """
                SELECT status, failure_code FROM data.collection_operations
                WHERE idempotency_key = 'abandoned-collection'
                """
            ).fetchone() == {
                "status": "failed",
                "failure_code": "COLLECTION_ABANDONED",
            }
        _assert_generation_missing(store, retired)
        lifecycle.protect_candidate(
            operation_id="post-crash-candidate",
            generation_manifest_sha256=head,
            lease_seconds=60,
        )
        lifecycle.release_candidate(operation_id="post-crash-candidate")
    finally:
        if recovery_database is not None:
            recovery_database.close()
        database.close()


def test_materialized_refresh_candidate_is_never_planned_before_registration(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    candidate_materialized = threading.Event()
    continue_refresh = threading.Event()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        current = build_minimal_canonical_fixture(price_offset=1)
        candidate = build_minimal_canonical_fixture(price_offset=2)
        with database.transaction() as transaction:
            transaction.execute(
                "DELETE FROM data.refresh_operations WHERE idempotency_key = %s",
                ("candidate-gap-refresh",),
            )
        head = store.materialize(
            current,
            prepared_at=datetime(2026, 8, 10, tzinfo=UTC),
            source_name="generation-collection-test",
            source_lineage={"ordinal": 1},
        ).manifest_sha256
        _install_head(lifecycle, head, operation_id="candidate-gap-head")
        refresh = DataRefreshService(database, tmp_path)
        refresh.submit(
            idempotency_key="candidate-gap-refresh",
            as_of=datetime(2026, 8, 10, 2, tzinfo=UTC),
        )
        original_materialize = MountedGenerationStore.materialize_refresh
        materialized: list[str] = []

        def pause_after_materialize(
            self: MountedGenerationStore,
            **kwargs: object,
        ) -> object:
            generation = original_materialize(self, **kwargs)
            materialized.append(generation.manifest_sha256)
            candidate_materialized.set()
            if not continue_refresh.wait(timeout=20):
                raise AssertionError("refresh candidate barrier was not released")
            return generation

        monkeypatch.setattr(
            MountedGenerationStore,
            "materialize_refresh",
            pause_after_materialize,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            processing = executor.submit(refresh.process_next, _StaticRefreshSource(candidate))
            assert candidate_materialized.wait(timeout=20)
            with pytest.raises(DataCollectionError) as rejected:
                DataGarbageCollector(database, tmp_path).collect(
                    idempotency_key="candidate-gap-collection"
                )
            assert rejected.value.code == "COLLECTION_DATA_WORK_ACTIVE"
            assert materialized
            assert store.open_generation(materialized[0]).manifest_sha256 == materialized[0]
            with database.transaction() as transaction:
                assert transaction.execute(
                    """
                    SELECT count(*) AS count FROM data.collection_targets
                    WHERE idempotency_key = 'candidate-gap-collection'
                    """
                ).fetchone() == {"count": 0}
            continue_refresh.set()
            assert processing.result(timeout=20) is True
        assert lifecycle.current_head().generation_manifest_sha256 == materialized[0]
    finally:
        continue_refresh.set()
        database.close()


def _materialize(store: MountedGenerationStore, *, ordinal: int) -> str:
    return store.materialize(
        build_minimal_canonical_fixture(price_offset=ordinal),
        prepared_at=datetime(2026, 8, 10, tzinfo=UTC) + timedelta(minutes=ordinal),
        source_name="generation-collection-test",
        source_lineage={"ordinal": ordinal},
    ).manifest_sha256


def _install_head(lifecycle: DatasetLifecycle, manifest: str, *, operation_id: str) -> None:
    lifecycle.protect_candidate(
        operation_id=operation_id,
        generation_manifest_sha256=manifest,
        lease_seconds=60,
    )
    lifecycle.compare_and_swap_head(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=manifest,
        operation_id=operation_id,
    )


def _move_head(
    lifecycle: DatasetLifecycle,
    *,
    expected: str,
    candidate: str,
    operation_id: str,
) -> None:
    lifecycle.protect_candidate(
        operation_id=operation_id,
        generation_manifest_sha256=candidate,
        lease_seconds=60,
    )
    lifecycle.compare_and_swap_head(
        expected_generation_manifest_sha256=expected,
        candidate_generation_manifest_sha256=candidate,
        operation_id=operation_id,
    )


def _assert_generation_missing(store: MountedGenerationStore, manifest: str) -> None:
    with pytest.raises(GenerationStoreError, match="missing"):
        store.open_generation(manifest)


def _clear_collection_state(database: PostgresDatabase) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            """
            TRUNCATE data.collection_roots, data.collection_targets,
                     data.collection_operations,
                     data.generation_pins, data.generation_candidates
            """
        )


def _pending_count(database: PostgresDatabase, key: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT count(*) AS count
            FROM data.collection_targets
            WHERE idempotency_key = %s AND status <> 'deleted'
            """,
            (key,),
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _collection_progress(database: PostgresDatabase, key: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT operation.status,
                   count(*) FILTER (WHERE target.status = 'deleted') AS deleted_count,
                   count(*) FILTER (WHERE target.status <> 'deleted') AS pending_count
            FROM data.collection_operations AS operation
            LEFT JOIN data.collection_targets AS target
              ON target.idempotency_key = operation.idempotency_key
            WHERE operation.idempotency_key = %s
            GROUP BY operation.status
            """,
            (key,),
        ).fetchone()
    assert row is not None
    return {
        "status": row["status"],
        "deleted_count": int(row["deleted_count"]),
        "pending_count": int(row["pending_count"]),
    }


class _StaticRefreshSource:
    def __init__(self, candidate: dict[str, object]) -> None:
        self._candidate = candidate

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        del plan
        calendar = self._candidate["research_calendar"]
        assert isinstance(calendar, list)
        return CanonicalSourceBatch(
            source_name="generation-collection-test",
            collection_kind="refresh",
            source_lineage={"candidate_gap": True},
            canonical=copy.deepcopy(self._candidate),
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )
