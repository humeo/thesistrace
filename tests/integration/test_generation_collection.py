from __future__ import annotations

import copy
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from canonical_store import open_complete_refresh_basis

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
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.financial_collection import (
    CompletedFinancialCollection,
    FinancialCollectionContract,
    FinancialDateShard,
    FinancialShardCheckpoint,
    RawFinancialBatchStore,
)
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.io_metrics import measure_data_io
from thesistrace.data.source import CollectionPlan
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication.serialization import canonical_json_bytes


def test_financial_generation_pin_protects_transitive_evidence_until_release(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    initialize_core(core_settings.database_url)
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        _clear_collection_state(database)
        store = MountedGenerationStore(tmp_path)
        lifecycle = DatasetLifecycle(database, tmp_path)
        market = _financial_market_generation(store)
        generation_a = _financial_generation(tmp_path, market, value="100", ordinal=1)
        generation_b = _financial_generation(tmp_path, market, value="200", ordinal=2)
        references_a = store.referenced_files(generation_a)
        references_b = store.referenced_files(generation_b)
        a_only = references_a - references_b
        assert {reference.kind for reference in a_only} >= {
            "manifest",
            "object",
            "raw_financial",
        }

        _install_head(lifecycle, generation_a, operation_id="financial-a-head")
        with measure_data_io() as pin_io:
            pin = lifecycle.pin_current(
                owner_kind="research_run_attempt",
                owner_id="financial-a-attempt",
                lease_seconds=60,
            ).pin
        assert pin_io.parquet_object_opens == 0
        assert pin_io.raw_financial_batch_opens == 0
        assert pin_io.rows_scanned == 0
        result_a = _financial_value(store, generation_a)
        _move_head(
            lifecycle,
            expected=generation_a,
            candidate=generation_b,
            operation_id="financial-b-head",
        )

        first = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="financial-a-pinned"
        )

        assert first.status == "succeeded"
        assert references_a <= store.inventory()
        assert _financial_value(store, generation_a) == result_a == "100"
        assert _financial_value(store, generation_b) == "200"

        lifecycle.release_pin(pin.id, owner_id=pin.owner_id)
        second = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="financial-a-released"
        )

        assert second.status == "succeeded"
        assert second.deleted_file_count >= len(a_only)
        assert a_only.isdisjoint(store.inventory())
        assert store.validate_generation(generation_b).manifest_sha256 == generation_b
        assert _financial_value(store, generation_b) == "200"
    finally:
        _clear_collection_state(database)
        database.close()


def test_collection_retains_every_live_root_and_shared_object_then_converges(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    initialize_core(core_settings.database_url)
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
        ).pin
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
        ).pin
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
            assert store.validate_generation(retained).manifest_sha256 == retained
        _assert_generation_missing(store, retired)
        _assert_generation_missing(store, shared_retired)
        assert open_complete_refresh_basis(store, current) == build_minimal_canonical_fixture(
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
        assert store.validate_generation(current).manifest_sha256 == current
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
    initialize_core(core_settings.database_url)
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
        assert store.validate_generation(retired).manifest_sha256 == retired
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
    initialize_core(core_settings.database_url)
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
        assert store.validate_generation(new_orphan).manifest_sha256 == new_orphan
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
    initialize_core(core_settings.database_url)
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
        ).pin
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
            selected = pin.result(timeout=2).descriptor.manifest_sha256
            release.result(timeout=2)
            assert move.result(timeout=2).generation_manifest_sha256 == next_head
            assert not collection.done()
            continue_deletion.set()
            assert collection.result(timeout=20).status == "succeeded"
        finally:
            continue_deletion.set()
            executor.shutdown(wait=True)

        assert selected in {head, next_head}
        assert store.validate_generation(selected).manifest_sha256 == selected
        assert lifecycle.current_pointer().generation_manifest_sha256 == next_head
    finally:
        _clear_collection_state(database)
        database.close()


def test_retained_generation_validation_does_not_hold_the_lifecycle_fence(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_core(core_settings.database_url)
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
            ).pin
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
    initialize_core(core_settings.database_url)
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
    initialize_core(core_settings.database_url)
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
            assert store.validate_generation(materialized[0]).manifest_sha256 == materialized[0]
            with database.transaction() as transaction:
                assert transaction.execute(
                    """
                    SELECT count(*) AS count FROM data.collection_targets
                    WHERE idempotency_key = 'candidate-gap-collection'
                    """
                ).fetchone() == {"count": 0}
            continue_refresh.set()
            assert processing.result(timeout=20) is True
        assert lifecycle.current_pointer().generation_manifest_sha256 == materialized[0]
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


def _financial_market_generation(store: MountedGenerationStore) -> str:
    canonical = build_minimal_canonical_fixture()
    sessions = ("2010-01-04", "2010-04-21", "2026-08-07")
    instrument_id = str(canonical["instruments"][0]["instrument_id"])
    price = dict(canonical["prices"][0])
    state = dict(canonical["trading_states"][0])
    limit = dict(canonical["price_limits"][0])
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    canonical["research_calendar"] = list(sessions)
    canonical["prices"] = [dict(price, session=session) for session in sessions]
    canonical["trading_states"] = [dict(state, session=session) for session in sessions]
    canonical["price_limits"] = [dict(limit, session=session) for session in sessions]
    canonical["base_pool"] = [
        {"session": session, "instrument_ids": [instrument_id]} for session in sessions
    ]
    canonical["liquidity_universes"] = {
        name: [{"session": session, **universe} for session in sessions]
        for name in ("top300", "top1000", "top2000", "top3000")
    }
    field = dict(canonical["field_catalog"][0])
    field["release_available_from"] = sessions[0]
    canonical["field_catalog"] = [field]
    return store.materialize(
        canonical,
        prepared_at=datetime(2026, 8, 7, 9, tzinfo=UTC),
        source_name="financial-generation-collection-test",
        source_lineage={"fixture": "financial-market"},
    ).manifest_sha256


def _financial_generation(root: Path, market: str, *, value: str, ordinal: int) -> str:
    fields = {
        "income": (
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "total_revenue",
            "n_income_attr_p",
            "update_flag",
        ),
        "balancesheet": (
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "total_assets",
            "total_liab",
            "total_hldr_eqy_exc_min_int",
            "update_flag",
        ),
        "cashflow": (
            "ts_code",
            "ann_date",
            "f_ann_date",
            "end_date",
            "report_type",
            "comp_type",
            "end_type",
            "n_cashflow_act",
            "update_flag",
        ),
    }
    endpoint_values = {
        "income": (value, value),
        "balancesheet": (value, value, value),
        "cashflow": (value,),
    }
    raw = RawFinancialBatchStore(root)
    checkpoints: list[FinancialShardCheckpoint] = []
    for endpoint in ("income", "balancesheet", "cashflow"):
        item = [
            "000001.SZ",
            "20100420",
            "",
            "20091231",
            "1",
            "1",
            "4",
            *endpoint_values[endpoint],
            "0",
        ]
        payload_sha256 = hashlib.sha256(
            canonical_json_bytes({"fields": list(fields[endpoint]), "items": [item]})
        ).hexdigest()
        payload = {
            "format": "thesistrace-raw-financial-batch",
            "version": 1,
            "source_contract_version": "tushare-financial-ordinary-v2",
            "endpoint": endpoint,
            "parameters": {"ts_code": "000001.SZ"},
            "returned_fields": list(fields[endpoint]),
            "items": [item],
            "row_count": 1,
            "source_date_extent": ["20100420", "20100420"],
            "payload_sha256": payload_sha256,
        }
        checkpoints.append(
            FinancialShardCheckpoint(
                ordinal=len(checkpoints),
                endpoint=endpoint,
                instrument_id="equity:000001.SZ",
                ts_code="000001.SZ",
                shard="complete-history",
                status="completed",
                batch_sha256=raw.store(canonical_json_bytes(payload)),
                collected_at="2026-08-07T08:00:00+00:00",
                first_observed_at="2026-08-07T08:00:00+00:00",
            )
        )
    contract = FinancialCollectionContract(
        capability_sha256=str(ordinal) * 64,
        endpoint_fields=tuple((endpoint, fields[endpoint]) for endpoint in fields),
        suspected_truncation_row_counts=tuple(
            (endpoint, None) for endpoint in ("income", "balancesheet", "cashflow")
        ),
        shards=(FinancialDateShard("complete-history"),),
    )
    candidate = FinancialCandidateStore(root).materialize(
        CompletedFinancialCollection(
            idempotency_key=f"financial-generation-{ordinal}",
            generation_manifest_sha256=market,
            contract=contract,
            finished_at="2026-08-07T09:00:00+00:00",
            target_count=3,
            shards=tuple(checkpoints),
        ),
        observation_through_session="2026-08-07",
    )
    return (
        MountedGenerationStore(root)
        .compose_financial_candidate(
            market,
            candidate.manifest_sha256,
            prepared_at=datetime(2026, 8, 7, 10, tzinfo=UTC) + timedelta(minutes=ordinal),
        )
        .manifest_sha256
    )


def _financial_value(store: MountedGenerationStore, generation: str) -> str:
    data = store.read_composite_slice(
        generation,
        sessions=["2026-08-07"],
        universe_name="top300",
        neutralization="none",
        field_bindings={
            "financial.income.total_revenue.latest_fy": "total_revenue_latest_fy"
        },
    ).research_data
    return str(
        data.fields["financial.income.total_revenue.latest_fy"][
            ("2026-08-07", "equity:000001.SZ")
        ]
    )


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
        store.validate_generation(manifest)


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
