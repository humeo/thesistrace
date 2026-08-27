from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from benchmark_support import FixtureBenchmarkSource, benchmark_mount_for_data_mount
from psycopg.errors import CheckViolation

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data import (
    CanonicalSourceBatch,
    DataCollectionError,
    DataGarbageCollector,
    DataRefreshService,
    DatasetLifecycle,
    DatasetOverviewService,
    FinancialCandidateError,
    FinancialCandidateStore,
    FinancialFamilyCandidate,
    FinancialRefreshError,
    FinancialRefreshOutcome,
    FinancialRefreshService,
    MountedDatasetHeadStore,
    MountedGenerationStore,
)
from thesistrace.data.daily_financial_refresh import DailyFinancialRefreshService
from thesistrace.data.financial_announcements import (
    FINANCIAL_ANNOUNCEMENT_CATEGORIES,
    FinancialAnnouncement,
    FinancialAnnouncementDiscovery,
    FinancialDiscoveryGap,
)
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FinancialCollectionContract,
    FinancialCollectionError,
    FinancialCollectionService,
    FinancialDateShard,
    RawFinancialBatchStore,
)
from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.source import RawSourceError, RawSourceResponse
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture

COLLECTED_AT = datetime(2026, 8, 13, 5, tzinfo=UTC)
FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "revenue",
    "update_flag",
)

EXECUTABLE_FIELDS = {
    "income": (*FIELDS[:7], "total_revenue", "n_income_attr_p", "update_flag"),
    "balancesheet": (
        *FIELDS[:7],
        "total_assets",
        "total_liab",
        "total_hldr_eqy_exc_min_int",
        "update_flag",
    ),
    "cashflow": (*FIELDS[:7], "n_cashflow_act", "update_flag"),
}


class StatementSource:
    def __init__(self, *, interrupt_after: int | None = None) -> None:
        self.requests: list[tuple[str, str, str]] = []
        self.interrupt_after = interrupt_after

    def query_raw(
        self,
        endpoint: str,
        *,
        params: dict[str, object],
        fields: tuple[str, ...],
    ) -> RawSourceResponse:
        if self.interrupt_after is not None and len(self.requests) == self.interrupt_after:
            self.interrupt_after = None
            raise KeyboardInterrupt
        assert fields == FIELDS
        ts_code = str(params["ts_code"])
        shard = str(params.get("start_date", "complete-history"))
        self.requests.append((endpoint, ts_code, shard))
        return RawSourceResponse(
            FIELDS,
            (
                (ts_code, "20260425", "", "20260331", "1", "1", "1", None, "0"),
                (ts_code, "20260425", "", "20260331", "1", "1", "1", None, "0"),
            ),
        )


class ExecutableStatementSource(StatementSource):
    def query_raw(
        self,
        endpoint: str,
        *,
        params: dict[str, object],
        fields: tuple[str, ...],
    ) -> RawSourceResponse:
        assert fields == EXECUTABLE_FIELDS[endpoint]
        ts_code = str(params["ts_code"])
        self.requests.append((endpoint, ts_code, "complete-history"))
        values = {
            "income": ("10", "4"),
            "balancesheet": ("20", "8", "12"),
            "cashflow": ("6",),
        }[endpoint]
        return RawSourceResponse(
            fields,
            (
                (
                    ts_code,
                    "20100420",
                    "",
                    "20091231",
                    "1",
                    "1",
                    "4",
                    *values,
                    "0",
                ),
            ),
        )


def test_collection_uses_historical_identities_and_reuses_raw_evidence(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = StatementSource()
        progress: list[dict[str, object]] = []
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
            progress=progress.append,
        )

        first = service.collect(
            idempotency_key="financial-bootstrap",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )
        repeated = service.collect(
            idempotency_key="financial-bootstrap",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )

        assert first == repeated
        assert first.status == "succeeded"
        assert first.target_count == first.completed_count == 6
        assert {request[1] for request in source.requests} == {"000001.SZ", "000002.SZ"}
        assert len(source.requests) == 6
        checkpoints = service.inspect("financial-bootstrap")
        assert len(checkpoints) == 6
        assert all(item.status == "completed" for item in checkpoints)
        assert len({item.batch_sha256 for item in checkpoints}) == 6
        assert checkpoints[0].batch_sha256 is not None
        batch = service.read_batch(checkpoints[0].batch_sha256)
        assert batch["returned_fields"] == list(FIELDS)
        assert batch["items"][0][-2] is None
        assert batch["items"][0] == batch["items"][1]
        assert batch["collected_at"] == COLLECTED_AT.isoformat()
        assert batch["row_count"] == 2
        assert batch["source_date_extent"] == ["20260425", "20260425"]
        assert all("token" not in repr(event).lower() for event in progress)
        assert progress[-1] | {"duration_seconds": 0.0} == {
            "event": "financial_collection",
            "phase": "collection",
            "status": "completed",
            "idempotency_key": "financial-bootstrap",
            "target_count": 6,
            "completed_count": 6,
            "failed_count": 0,
            "resumed_count": 0,
            "duration_seconds": 0.0,
        }
        assert float(progress[-1]["duration_seconds"]) >= 0
        snapshot = service.completed_snapshot("financial-bootstrap")
        assert snapshot.idempotency_key == "financial-bootstrap"
        assert snapshot.generation_manifest_sha256 == manifest
        assert snapshot.contract == _contract()
        assert snapshot.target_count == 6
        assert (
            tuple(item.first_observed_at for item in snapshot.shards)
            == (COLLECTED_AT.isoformat(),) * 6
        )

        later_service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT + timedelta(days=1),
        )
        replayed = later_service.collect(
            idempotency_key="financial-bootstrap-exact-replay",
            generation_manifest_sha256=manifest,
            contract=_contract(capability_sha256="b" * 64),
        )
        replayed_checkpoints = service.inspect("financial-bootstrap-exact-replay")
        replayed_snapshot = later_service.completed_snapshot("financial-bootstrap-exact-replay")
        assert replayed.status == "succeeded"
        assert len(source.requests) == 12
        assert {item.batch_sha256 for item in replayed_checkpoints} == {
            item.batch_sha256 for item in checkpoints
        }
        assert (
            tuple(item.collected_at for item in replayed_snapshot.shards)
            == ((COLLECTED_AT + timedelta(days=1)).isoformat(),) * 6
        )
        assert (
            tuple(item.first_observed_at for item in replayed_snapshot.shards)
            == (COLLECTED_AT.isoformat(),) * 6
        )
        assert len(tuple((tmp_path / "financial" / "raw").rglob("*.json"))) == 6
        assert MountedGenerationStore(tmp_path).inspect_root(manifest).manifest_sha256 == manifest
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


def test_interrupted_collection_resumes_only_unfinished_shards(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = StatementSource(interrupt_after=2)
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(KeyboardInterrupt):
            service.collect(
                idempotency_key="resume-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
        assert len(source.requests) == 2

        outcome = service.collect(
            idempotency_key="resume-financial",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )

        assert outcome.status == "succeeded"
        assert len(source.requests) == 6
        assert len(set(source.requests)) == 6
    finally:
        database.close()


def test_gc_cannot_delete_raw_evidence_while_financial_collection_is_active(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    raw_written = threading.Event()
    continue_collection = threading.Event()

    def progress(event: dict[str, object]) -> None:
        if (
            event.get("event") == "financial_collection"
            and event.get("phase") == "source_request"
            and event.get("status") == "completed"
            and not raw_written.is_set()
        ):
            raw_written.set()
            if not continue_collection.wait(timeout=20):
                raise AssertionError("financial collection barrier was not released")

    try:
        manifest = _market_generation(tmp_path)
        service = FinancialCollectionService(
            database,
            tmp_path,
            StatementSource(),
            clock=lambda: COLLECTED_AT,
            progress=progress,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            collecting = executor.submit(
                service.collect,
                idempotency_key="gc-fenced-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
            assert raw_written.wait(timeout=20)
            raw_files = tuple((tmp_path / "financial" / "raw").rglob("*.json"))
            assert raw_files

            with pytest.raises(DataCollectionError) as rejected:
                DataGarbageCollector(database, tmp_path).collect(
                    idempotency_key="gc-during-financial"
                )

            assert rejected.value.code == "COLLECTION_DATA_WORK_ACTIVE"
            assert all(path.exists() for path in raw_files)
            continue_collection.set()
            assert collecting.result(timeout=20).status == "succeeded"
    finally:
        continue_collection.set()
        database.close()


def test_successful_collection_retains_raw_evidence_until_explicit_release(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        service = FinancialCollectionService(
            database,
            tmp_path,
            StatementSource(),
            clock=lambda: COLLECTED_AT,
        )
        service.collect(
            idempotency_key="retained-financial",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )
        raw_files = tuple((tmp_path / "financial" / "raw").rglob("*.json"))
        assert raw_files

        DataGarbageCollector(database, tmp_path).collect(idempotency_key="gc-retained-financial")

        assert all(path.exists() for path in raw_files)
        assert service.completed_snapshot("retained-financial").target_count == 6
        service.release("retained-financial")
        DataGarbageCollector(database, tmp_path).collect(idempotency_key="gc-released-financial")
        assert not any(path.exists() for path in raw_files)
    finally:
        database.close()


def test_gc_exclusive_lock_cannot_deadlock_a_financial_claim(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    deletion_started = threading.Event()
    continue_gc = threading.Event()
    original_delete = AddressedFileStore.delete

    def blocked_delete(store: AddressedFileStore, path: Path) -> bool:
        deletion_started.set()
        if not continue_gc.wait(timeout=20):
            raise AssertionError("GC deletion barrier was not released")
        return original_delete(store, path)

    try:
        manifest = _market_generation(tmp_path)
        DatasetLifecycle(database, tmp_path).protect_candidate(
            operation_id="retain-market-for-reverse-race",
            generation_manifest_sha256=manifest,
            lease_seconds=60,
        )
        RawFinancialBatchStore(tmp_path).store(b"{}")
        monkeypatch.setattr(AddressedFileStore, "delete", blocked_delete)
        with ThreadPoolExecutor(max_workers=3) as executor:
            collecting_garbage = executor.submit(
                DataGarbageCollector(database, tmp_path).collect,
                idempotency_key="gc-first-reverse-race",
            )
            assert deletion_started.wait(timeout=20)
            collecting_financial = executor.submit(
                FinancialCollectionService(
                    database,
                    tmp_path,
                    StatementSource(),
                    clock=lambda: COLLECTED_AT,
                ).collect,
                idempotency_key="financial-second-reverse-race",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
            collecting_second_writer = executor.submit(
                FinancialCollectionService(
                    database,
                    tmp_path,
                    StatementSource(),
                    clock=lambda: COLLECTED_AT,
                ).collect,
                idempotency_key="financial-third-reverse-race",
                generation_manifest_sha256=manifest,
                contract=_contract(capability_sha256="d" * 64),
            )
            assert not collecting_financial.done()
            assert not collecting_second_writer.done()
            continue_gc.set()
            assert collecting_garbage.result(timeout=20).status == "succeeded"
            assert collecting_financial.result(timeout=20).status == "succeeded"
            assert collecting_second_writer.result(timeout=20).status == "succeeded"
    finally:
        continue_gc.set()
        database.close()


def test_collection_preserves_rows_without_a_usable_publication_date(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class MissingPublicationSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            self.requests.append((endpoint, str(params["ts_code"]), "complete-history"))
            return RawSourceResponse(
                FIELDS,
                (
                    (
                        str(params["ts_code"]),
                        None,
                        None,
                        "20260331",
                        "1",
                        "1",
                        "1",
                        12,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = MissingPublicationSource()
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        outcome = service.collect(
            idempotency_key="missing-publication-raw",
            generation_manifest_sha256=manifest,
            contract=_contract(),
        )

        assert outcome.status == "succeeded"
        checkpoint = service.inspect("missing-publication-raw")[0]
        assert checkpoint.batch_sha256 is not None
        batch = service.read_batch(checkpoint.batch_sha256)
        assert batch["items"][0][1:3] == [None, None]
        assert batch["source_date_extent"] is None
    finally:
        database.close()


def test_concurrent_duplicate_collection_accepts_each_shard_once(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = StatementSource()
        start = threading.Barrier(2)

        def collect() -> object:
            start.wait(timeout=5)
            return FinancialCollectionService(
                database,
                tmp_path,
                source,
                clock=lambda: COLLECTED_AT,
            ).collect(
                idempotency_key="concurrent-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(lambda _ordinal: collect(), range(2)))

        assert outcomes[0] == outcomes[1]
        assert len(source.requests) == 6
        assert len(set(source.requests)) == 6
        checkpoints = FinancialCollectionService(
            database,
            tmp_path,
            source,
        ).inspect("concurrent-financial")
        assert len(checkpoints) == 6
        assert all(checkpoint.status == "completed" for checkpoint in checkpoints)
    finally:
        database.close()


def test_partial_endpoint_failure_keeps_evidence_but_never_completes(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class PartialFailureSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            if endpoint == "balancesheet":
                self.requests.append((endpoint, str(params["ts_code"]), "complete-history"))
                raise TushareSourceError("UPSTREAM_RATE_LIMITED", source_code=40203)
            return super().query_raw(endpoint, params=params, fields=fields)

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        source = PartialFailureSource()
        service = FinancialCollectionService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCollectionError, match="UPSTREAM_RATE_LIMITED"):
            service.collect(
                idempotency_key="partial-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
        first_checkpoints = service.inspect("partial-financial")
        assert [checkpoint.status for checkpoint in first_checkpoints] == [
            "completed",
            "completed",
            "pending",
            "pending",
            "pending",
            "pending",
        ]
        accepted = [
            checkpoint.batch_sha256
            for checkpoint in first_checkpoints
            if checkpoint.batch_sha256 is not None
        ]
        assert len(accepted) == 2
        assert all(service.read_batch(batch)["endpoint"] == "income" for batch in accepted)

        with pytest.raises(FinancialCollectionError, match="UPSTREAM_RATE_LIMITED"):
            service.collect(
                idempotency_key="partial-financial",
                generation_manifest_sha256=manifest,
                contract=_contract(),
            )
        assert len(source.requests) == 3
        assert service.inspect("partial-financial") == first_checkpoints
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


def test_refresh_rebuild_retains_absent_versions_and_reports_progress(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class ValueSource(StatementSource):
        def __init__(self, value: int) -> None:
            super().__init__()
            self.value = value

        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            ts_code = str(params["ts_code"])
            self.requests.append((endpoint, ts_code, "complete-history"))
            return RawSourceResponse(
                fields,
                (
                    (
                        ts_code,
                        "20260425",
                        "",
                        "20260331",
                        "1",
                        "1",
                        "1",
                        self.value,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        first = _initial_candidate(
            database,
            tmp_path,
            ValueSource(10),
            manifest,
            idempotency_key="initial-financial-family",
        )
        lifecycle_events: list[dict[str, object]] = []
        refresh_source = ValueSource(11)
        refresh_service = FinancialRefreshService(
            database,
            tmp_path,
            refresh_source,
            clock=lambda: COLLECTED_AT + timedelta(days=1),
            monotonic=lambda: 2.0,
            lifecycle_event=lifecycle_events.append,
        )
        refreshed = refresh_service.rebuild(
            idempotency_key="refresh-financial-family",
            generation_manifest_sha256=manifest,
            contract=_contract(capability_sha256="b" * 64),
            prior_candidate_manifest_sha256=first.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        assert refreshed.expected_shard_count == refreshed.completed_shard_count == 6
        assert refreshed.resumed_shard_count == 0
        income = FinancialCandidateStore(tmp_path).read_table(
            refreshed.candidate.manifest_sha256,
            "income_statement_versions",
        )
        assert {row["revenue"] for row in income} == {"10", "11"}
        assert (
            next(row for row in income if row["revenue"] == "11")["revision_basis"]
            == "observed_correction"
        )
        assert [event["phase"] for event in lifecycle_events] == [
            "financial",
            "validation",
        ]
        assert all(event["duration_ms"] == 0 for event in lifecycle_events)
        assert all("token" not in repr(event).lower() for event in lifecycle_events)
        assert not (tmp_path / "HEAD.json").exists()
        assert (
            refresh_service.rebuild(
                idempotency_key="refresh-financial-family",
                generation_manifest_sha256=manifest,
                contract=_contract(capability_sha256="b" * 64),
                prior_candidate_manifest_sha256=first.manifest_sha256,
                observation_through_session="2026-08-13",
            )
            == refreshed
        )
        assert len(refresh_source.requests) == 6
        with pytest.raises(
            FinancialRefreshError,
            match="FINANCIAL_REFRESH_IDEMPOTENCY_KEY_REUSED",
        ):
            refresh_service.rebuild(
                idempotency_key="refresh-financial-family",
                generation_manifest_sha256=manifest,
                contract=_contract(capability_sha256="b" * 64),
                prior_candidate_manifest_sha256=first.manifest_sha256,
                observation_through_session="2026-08-07",
            )
    finally:
        database.close()


def test_financial_refresh_publishes_executable_family_under_the_one_dataset_head(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market, operation_id="financial-publish-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="financial-publish-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="financial-publish-source",
            expected=market,
        )
        lifecycle_events: list[dict[str, object]] = []
        published_heads: list[str] = []

        def lossy_lifecycle(event: dict[str, object]) -> None:
            lifecycle_events.append(event)
            if event.get("phase") == "publication":
                pointer = MountedDatasetHeadStore(tmp_path).current_pointer()
                assert pointer is not None
                published_heads.append(pointer.generation_manifest_sha256)
            if event.get("phase") in {"financial", "publication"}:
                raise RuntimeError(
                    "simulated financial telemetry loss canary-secret /private/financial"
                )

        service = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
            lifecycle_event=lossy_lifecycle,
        )

        published = service.publish(
            idempotency_key="financial-publish",
            generation_manifest_sha256=source_generation,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        pointer = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert pointer is not None
        assert pointer.generation_manifest_sha256 == published.generation_manifest_sha256
        generation = MountedGenerationStore(tmp_path).validate_generation(
            pointer.generation_manifest_sha256
        )
        assert generation.financial_candidate_manifest_sha256 == (
            published.candidate.manifest_sha256
        )
        assert tuple(family.manifest_sha256 for family in generation.families[:-1]) == tuple(
            family.manifest_sha256
            for family in MountedGenerationStore(tmp_path).inspect_root(market).families
        )

        def reject_parquet(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("Data Overview opened Parquet")

        monkeypatch.setattr("thesistrace.data.generation_store.pq.read_table", reject_parquet)
        overview = DatasetOverviewService(database, tmp_path).overview()
        assert overview.market_coverage.model_dump(mode="json") == {
            "start": "2010-01-04",
            "end": "2026-08-13",
        }
        assert overview.financial_coverage is not None
        assert overview.financial_coverage.model_dump(mode="json") == {
            "start": "2010-01-04",
            "discovery_baseline_session": "2026-08-13",
            "discovery_attempted_through_session": "2026-08-13",
            "discovery_complete_through_session": "2026-08-13",
            "historical_reconciliation_watermark": "2026-08-13",
            "revision_coverage": "source-dated-and-first-observed-corrections",
            "seed_policy": "latest-pre-start-annual-flow-and-balance-facts",
            "readiness_status": "ready",
            "pending_instrument_count": 0,
            "discovery_gap_count": 0,
            "earliest_unresolved_date": None,
            "sparse_facts": True,
        }
        assert overview.last_financial_refresh_at == COLLECTED_AT + timedelta(days=1)
        assert overview.financial_research_readiness == "ready"
        assert [event["event"] for event in lifecycle_events] == [
            "data_refresh_started",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_succeeded",
        ]
        assert [
            event["phase"]
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
        ] == ["financial", "validation", "publication"]
        assert {event["operation_id"] for event in lifecycle_events} == {
            lifecycle_events[0]["operation_id"]
        }
        assert str(lifecycle_events[0]["operation_id"]).startswith("financial-refresh:")
        assert published_heads == [published.generation_manifest_sha256]
        assert "canary-secret" not in json.dumps(lifecycle_events)
        assert "/private/financial" not in json.dumps(lifecycle_events)
        monkeypatch.undo()
        assert service.publish(
            idempotency_key="financial-publish",
            generation_manifest_sha256=source_generation,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        ) == published
    finally:
        database.close()


def test_daily_financial_refresh_discovers_one_stock_and_moves_the_one_head(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class AnnouncementSource:
        def discover(
            self,
            *,
            start_date: str,
            end_date: str,
            allowed_ts_codes: set[str] | frozenset[str],
        ) -> FinancialAnnouncementDiscovery:
            assert (start_date, end_date) == ("2026-08-07", "2026-08-14")
            assert allowed_ts_codes == {"000001.SZ"}
            return FinancialAnnouncementDiscovery(
                start_date=start_date,
                end_date=end_date,
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=(
                    FinancialAnnouncement(
                        announcement_id="a" * 64,
                        category="半年报",
                        ts_code="000001.SZ",
                        name="平安银行",
                        title="平安银行2026年半年度报告",
                        source_published_date="2026-08-14",
                        report_period=None,
                        url="https://example.test/announcement/a",
                    ),
                    FinancialAnnouncement(
                        announcement_id="b" * 64,
                        category="补充更正",
                        ts_code="000001.SZ",
                        name="平安银行",
                        title="平安银行2026年半年度报告更正公告",
                        source_published_date="2026-08-13",
                        report_period="2026-06-30",
                        url="https://example.test/announcement/b",
                    ),
                ),
                gaps=(),
                source_lineage_sha256="b" * 64,
            )

    class DailyStatementSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            assert fields == EXECUTABLE_FIELDS[endpoint]
            ts_code = str(params["ts_code"])
            self.requests.append((endpoint, ts_code, "complete-history"))
            values = {
                "income": ("11", "5"),
                "balancesheet": ("21", "8", "13"),
                "cashflow": ("7",),
            }[endpoint]
            return RawSourceResponse(
                fields,
                (
                    (
                        ts_code,
                        "20260814",
                        "",
                        "20260630",
                        "1",
                        "1",
                        "2",
                        *values,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-13", "2026-08-14"),
        )
        _establish_head(database, tmp_path, market, operation_id="daily-financial-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="daily-financial-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="daily-financial-source",
            expected=market,
        )
        statement_source = DailyStatementSource()
        service = DailyFinancialRefreshService(
            database,
            tmp_path,
            AnnouncementSource(),
            statement_source,
            clock=lambda: datetime(2026, 8, 14, 10, tzinfo=UTC),
        )

        published = service.publish(
            idempotency_key="daily-financial-publish",
            observation_through_session="2026-08-14",
        )

        assert published.status == "succeeded"
        assert published.attempted_through_session == "2026-08-14"
        assert published.complete_through_session == "2026-08-14"
        assert published.accepted_instrument_count == 1
        assert published.failed_instrument_count == 0
        inspection = service.inspect("daily-financial-publish")
        assert inspection["matched_trigger_count"] == 2
        assert inspection["checked_no_structured_change_count"] == 0
        assert inspection["pending_trigger_count"] == 0
        assert statement_source.requests == [
            (endpoint, "000001.SZ", "complete-history")
            for endpoint in FINANCIAL_ENDPOINTS
        ]
        pointer = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert pointer is not None
        assert pointer.generation_manifest_sha256 == published.generation_manifest_sha256
        generation = MountedGenerationStore(tmp_path).validate_generation(
            pointer.generation_manifest_sha256
        )
        assert generation.financial_candidate_manifest_sha256 == (
            published.candidate.manifest_sha256
        )
        assert published.candidate.readiness_status == "ready"
        assert published.candidate.discovery_baseline_session == "2026-08-13"
        overview = DatasetOverviewService(database, tmp_path).overview()
        assert overview.financial_research_readiness == "ready"
        assert overview.financial_coverage is not None
        assert overview.financial_coverage.model_dump(mode="json") == {
            "start": "2010-01-04",
            "discovery_baseline_session": "2026-08-13",
            "discovery_attempted_through_session": "2026-08-14",
            "discovery_complete_through_session": "2026-08-14",
            "historical_reconciliation_watermark": "2026-08-13",
            "revision_coverage": "cninfo-announcement-driven-tushare-observed",
            "seed_policy": "latest-pre-start-annual-flow-and-balance-facts",
            "readiness_status": "ready",
            "pending_instrument_count": 0,
            "discovery_gap_count": 0,
            "earliest_unresolved_date": None,
            "sparse_facts": True,
        }
        assert service.publish(
            idempotency_key="daily-financial-publish",
            observation_through_session="2026-08-14",
        ) == published
        assert len(statement_source.requests) == 3
    finally:
        database.close()


def test_daily_financial_refresh_closes_unchanged_trigger_and_reuses_tables(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class AnnouncementSource:
        def discover(
            self,
            *,
            start_date: str,
            end_date: str,
            allowed_ts_codes: set[str] | frozenset[str],
        ) -> FinancialAnnouncementDiscovery:
            assert (start_date, end_date) == ("2026-08-07", "2026-08-13")
            assert allowed_ts_codes == {"000001.SZ"}
            return FinancialAnnouncementDiscovery(
                start_date=start_date,
                end_date=end_date,
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=(
                    FinancialAnnouncement(
                        announcement_id="c" * 64,
                        category="半年报",
                        ts_code="000001.SZ",
                        name="平安银行",
                        title="平安银行2026年半年度报告",
                        source_published_date="2026-08-12",
                        report_period="2026-06-30",
                        url="https://example.test/announcement/unchanged",
                    ),
                ),
                gaps=(),
                source_lineage_sha256="d" * 64,
            )

    class StableStatementSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            assert fields == EXECUTABLE_FIELDS[endpoint]
            ts_code = str(params["ts_code"])
            self.requests.append((endpoint, ts_code, "complete-history"))
            values = {
                "income": ("10", "4"),
                "balancesheet": ("20", "8", "12"),
                "cashflow": ("6",),
            }[endpoint]
            return RawSourceResponse(
                fields,
                (
                    (
                        ts_code,
                        "20260812",
                        "",
                        "20260630",
                        "1",
                        "1",
                        "2",
                        *values,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-12", "2026-08-13"),
        )
        _establish_head(database, tmp_path, market, operation_id="unchanged-daily-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            StableStatementSource(),
            market,
            idempotency_key="unchanged-daily-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="unchanged-daily-source",
            expected=market,
        )
        statement_source = StableStatementSource()
        service = DailyFinancialRefreshService(
            database,
            tmp_path,
            AnnouncementSource(),
            statement_source,
            clock=lambda: datetime(2026, 8, 13, 10, tzinfo=UTC),
        )

        published = service.publish(
            idempotency_key="unchanged-daily-publish",
            observation_through_session="2026-08-13",
        )

        assert published.status == "succeeded"
        assert published.accepted_instrument_count == 1
        assert published.pending_instrument_count == 0
        inspection = service.inspect("unchanged-daily-publish")
        assert inspection["matched_trigger_count"] == 0
        assert inspection["checked_no_structured_change_count"] == 1
        assert inspection["pending_trigger_count"] == 0
        assert statement_source.requests == [
            (endpoint, "000001.SZ", "complete-history")
            for endpoint in FINANCIAL_ENDPOINTS
        ]

        def family_manifest(manifest_sha256: str) -> dict[str, object]:
            return json.loads(
                (
                    tmp_path
                    / "manifests"
                    / "sha256"
                    / manifest_sha256[:2]
                    / f"{manifest_sha256}.json"
                ).read_bytes()
            )

        assert family_manifest(published.candidate.manifest_sha256)["tables"] == (
            family_manifest(prior.manifest_sha256)["tables"]
        )
    finally:
        database.close()


@pytest.mark.parametrize(
    ("has_gap", "expected_status", "expected_complete", "expected_readiness"),
    (
        (False, "succeeded", "2026-08-14", "ready"),
        (True, "succeeded_with_gaps", "2026-08-13", "ready_with_gaps"),
    ),
)
def test_daily_financial_refresh_publishes_zero_trigger_discovery_state(
    core_settings: CoreSettings,
    tmp_path: Path,
    *,
    has_gap: bool,
    expected_status: str,
    expected_complete: str,
    expected_readiness: str,
) -> None:
    class AnnouncementSource:
        def discover(
            self,
            *,
            start_date: str,
            end_date: str,
            allowed_ts_codes: set[str] | frozenset[str],
        ) -> FinancialAnnouncementDiscovery:
            assert start_date == "2026-08-07"
            assert end_date == "2026-08-14"
            assert allowed_ts_codes == {"000001.SZ"}
            failed_category = FINANCIAL_ANNOUNCEMENT_CATEGORIES[-1]
            return FinancialAnnouncementDiscovery(
                start_date=start_date,
                end_date=end_date,
                completed_categories=(
                    FINANCIAL_ANNOUNCEMENT_CATEGORIES[:-1]
                    if has_gap
                    else FINANCIAL_ANNOUNCEMENT_CATEGORIES
                ),
                announcements=(),
                gaps=(
                    (
                        FinancialDiscoveryGap(
                            category=failed_category,
                            start_date=start_date,
                            end_date=end_date,
                            failure_code="CNINFO_DISCOVERY_UNAVAILABLE",
                        ),
                    )
                    if has_gap
                    else ()
                ),
                source_lineage_sha256="c" * 64,
            )

    class UnexpectedStatementSource(ExecutableStatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            del endpoint, params, fields
            raise AssertionError("zero-trigger refresh must not call Tushare")

    database = _database(core_settings)
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-13", "2026-08-14"),
        )
        _establish_head(database, tmp_path, market, operation_id=f"zero-trigger-market-{has_gap}")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key=f"zero-trigger-prior-{has_gap}",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id=f"zero-trigger-source-{has_gap}",
            expected=market,
        )

        published = DailyFinancialRefreshService(
            database,
            tmp_path,
            AnnouncementSource(),
            UnexpectedStatementSource(),
            clock=lambda: datetime(2026, 8, 14, 10, tzinfo=UTC),
        ).publish(
            idempotency_key=f"zero-trigger-publish-{has_gap}",
            observation_through_session="2026-08-14",
        )

        assert published.status == expected_status
        assert published.accepted_instrument_count == 0
        assert published.failed_instrument_count == 0
        assert published.pending_instrument_count == 0
        assert published.discovery_gap_count == int(has_gap)
        assert published.complete_through_session == expected_complete
        assert published.candidate.readiness_status == expected_readiness
        head = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == published.generation_manifest_sha256
    finally:
        database.close()


@pytest.mark.parametrize("failure_mode", ("source", "undated_source_row"))
def test_daily_financial_refresh_publishes_other_stocks_when_one_stock_fails(
    core_settings: CoreSettings,
    tmp_path: Path,
    failure_mode: str,
) -> None:
    class AnnouncementSource:
        def discover(
            self,
            *,
            start_date: str,
            end_date: str,
            allowed_ts_codes: set[str] | frozenset[str],
        ) -> FinancialAnnouncementDiscovery:
            assert allowed_ts_codes == {"000001.SZ", "000002.SZ"}
            return FinancialAnnouncementDiscovery(
                start_date=start_date,
                end_date=end_date,
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=tuple(
                    FinancialAnnouncement(
                        announcement_id=character * 64,
                        category="半年报",
                        ts_code=ts_code,
                        name=ts_code,
                        title=f"{ts_code} 2026年半年度报告",
                        source_published_date="2026-08-14",
                        report_period="2026-06-30",
                        url=f"https://example.test/{ts_code}",
                    )
                    for character, ts_code in (
                        ("a", "000001.SZ"),
                        ("b", "000002.SZ"),
                    )
                ),
                gaps=(),
                source_lineage_sha256="c" * 64,
            )

    class PartiallyInvalidStatementSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            ts_code = str(params["ts_code"])
            self.requests.append((endpoint, ts_code, "complete-history"))
            if (
                failure_mode == "source"
                and ts_code == "000002.SZ"
                and endpoint == "balancesheet"
            ):
                raise RawSourceError("upstream unavailable")
            values = {
                "income": ("11", "5"),
                "balancesheet": ("21", "8", "13"),
                "cashflow": ("7",),
            }[endpoint]
            return RawSourceResponse(
                fields,
                (
                    (
                        ts_code,
                        (
                            ""
                            if failure_mode == "undated_source_row"
                            and ts_code == "000002.SZ"
                            else "20260814"
                        ),
                        "",
                        "20260630",
                        "1",
                        "1",
                        "2",
                        *values,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        market = _market_generation(
            tmp_path,
            sessions=(
                "2010-01-04",
                "2026-08-07",
                "2026-08-13",
                "2026-08-14",
                "2026-08-17",
            ),
            second_listed_to="",
        )
        _establish_head(
            database,
            tmp_path,
            market,
            operation_id=f"partial-daily-market-{failure_mode}",
        )
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key=f"partial-daily-prior-{failure_mode}",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id=f"partial-daily-source-{failure_mode}",
            expected=market,
        )
        source = PartiallyInvalidStatementSource()

        published = DailyFinancialRefreshService(
            database,
            tmp_path,
            AnnouncementSource(),
            source,
            clock=lambda: datetime(2026, 8, 17, 10, tzinfo=UTC),
        ).publish(
            idempotency_key=f"partial-daily-publish-{failure_mode}",
            observation_through_session="2026-08-17",
        )

        assert published.status == "succeeded_with_pending"
        assert published.accepted_instrument_count == 1
        assert published.failed_instrument_count == 1
        assert published.pending_instrument_count == 1
        assert published.discovery_gap_count == 0
        assert published.complete_through_session == "2026-08-17"
        assert published.candidate.readiness_status == "ready_with_pending"
        assert source.requests == [
            *((endpoint, "000001.SZ", "complete-history") for endpoint in FINANCIAL_ENDPOINTS),
            *(
                (("income", "000002.SZ", "complete-history"),
                 ("balancesheet", "000002.SZ", "complete-history"))
                if failure_mode == "source"
                else tuple(
                    (endpoint, "000002.SZ", "complete-history")
                    for endpoint in FINANCIAL_ENDPOINTS
                )
            ),
        ]
        candidate_rows = FinancialCandidateStore(tmp_path).read_financial_rows(
            published.candidate.manifest_sha256,
            "income",
            ("instrument_id", "source_report_period", "total_revenue"),
            ("2026-08-13", "2026-08-17"),
            frozenset({"equity:000001.SZ", "equity:000002.SZ"}),
        )
        assert any(
            row["instrument_id"] == "equity:000001.SZ"
            and row["source_report_period"] == "20260630"
            and row["total_revenue"] == "11"
            for row in candidate_rows
        ), candidate_rows
        assert any(
            row["instrument_id"] == "equity:000002.SZ"
            and row["source_report_period"] == "20091231"
            and row["total_revenue"] == "10"
            for row in candidate_rows
        ), candidate_rows
    finally:
        database.close()


def test_daily_financial_refresh_resumes_after_each_durable_stock_checkpoint(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class AnnouncementSource:
        def discover(
            self,
            *,
            start_date: str,
            end_date: str,
            allowed_ts_codes: set[str] | frozenset[str],
        ) -> FinancialAnnouncementDiscovery:
            assert allowed_ts_codes == {"000001.SZ", "000002.SZ"}
            return FinancialAnnouncementDiscovery(
                start_date=start_date,
                end_date=end_date,
                completed_categories=FINANCIAL_ANNOUNCEMENT_CATEGORIES,
                announcements=tuple(
                    FinancialAnnouncement(
                        announcement_id=character * 64,
                        category="半年报",
                        ts_code=ts_code,
                        name=ts_code,
                        title=f"{ts_code} 2026年半年度报告",
                        source_published_date="2026-08-14",
                        report_period="2026-06-30",
                        url=f"https://example.test/{ts_code}",
                    )
                    for character, ts_code in (
                        ("a", "000001.SZ"),
                        ("b", "000002.SZ"),
                    )
                ),
                gaps=(),
                source_lineage_sha256="c" * 64,
            )

    class DailyStatementSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            ts_code = str(params["ts_code"])
            self.requests.append((endpoint, ts_code, "complete-history"))
            values = {
                "income": ("11", "5"),
                "balancesheet": ("21", "8", "13"),
                "cashflow": ("7",),
            }[endpoint]
            return RawSourceResponse(
                fields,
                (
                    (
                        ts_code,
                        "20260814",
                        "",
                        "20260630",
                        "1",
                        "1",
                        "2",
                        *values,
                        "0",
                    ),
                ),
            )

    database = _database(core_settings)
    try:
        market = _market_generation(
            tmp_path,
            sessions=("2010-01-04", "2026-08-07", "2026-08-13", "2026-08-14"),
            second_listed_to="",
        )
        _establish_head(database, tmp_path, market, operation_id="daily-resume-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="daily-resume-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="daily-resume-source",
            expected=market,
        )
        statement_source = DailyStatementSource()
        interrupted = False

        def interrupt_after_first(event: dict[str, object]) -> None:
            nonlocal interrupted
            if event.get("phase") == "instrument_checkpoint" and not interrupted:
                interrupted = True
                raise RuntimeError("interrupt after first stock checkpoint")

        service = DailyFinancialRefreshService(
            database,
            tmp_path,
            AnnouncementSource(),
            statement_source,
            clock=lambda: datetime(2026, 8, 14, 10, tzinfo=UTC),
            progress=interrupt_after_first,
        )
        with pytest.raises(RuntimeError, match="interrupt after first stock checkpoint"):
            service.publish(
                idempotency_key="daily-resume-publish",
                observation_through_session="2026-08-14",
            )
        assert statement_source.requests == [
            (endpoint, "000001.SZ", "complete-history")
            for endpoint in FINANCIAL_ENDPOINTS
        ]

        outcome = DailyFinancialRefreshService(
            database,
            tmp_path,
            AnnouncementSource(),
            statement_source,
            clock=lambda: datetime(2026, 8, 14, 10, tzinfo=UTC),
        ).publish(
            idempotency_key="daily-resume-publish",
            observation_through_session="2026-08-14",
        )

        assert outcome.status == "succeeded"
        assert statement_source.requests == [
            *((endpoint, "000001.SZ", "complete-history") for endpoint in FINANCIAL_ENDPOINTS),
            *((endpoint, "000002.SZ", "complete-history") for endpoint in FINANCIAL_ENDPOINTS),
        ]
    finally:
        database.close()


def test_financial_refresh_rejects_prior_identity_mismatch_before_collection(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="financial-prior-identity",
            contract=contract,
        )
        financial = _financial_generation(tmp_path, market, prior)
        source = ExecutableStatementSource()
        lifecycle_events: list[dict[str, object]] = []
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            lifecycle_event=lifecycle_events.append,
        )

        for generation, supplied_prior in (
            (market, prior.manifest_sha256),
            (financial, None),
            (financial, "0" * 64),
        ):
            with pytest.raises(
                FinancialRefreshError,
                match="FINANCIAL_PRIOR_CANDIDATE_MISMATCH",
            ):
                service.publish(
                    idempotency_key=f"invalid-prior-{supplied_prior}",
                    generation_manifest_sha256=generation,
                    contract=contract,
                    prior_candidate_manifest_sha256=supplied_prior,
                    observation_through_session="2026-08-13",
                )

        assert source.requests == []
        failures = [
            event for event in lifecycle_events if event["event"] == "data_refresh_failed"
        ]
        assert len(failures) == 3
        assert all(event["level"] == "ERROR" for event in failures)
        assert all(
            event["failure_code"] == "FINANCIAL_PRIOR_CANDIDATE_MISMATCH"
            for event in failures
        )
        assert not [
            event for event in lifecycle_events if event["event"] == "data_refresh_succeeded"
        ]
        with database.transaction() as transaction:
            assert transaction.execute(
                "SELECT 1 FROM data.financial_refresh_operations"
            ).fetchone() is None
    finally:
        database.close()


def test_financial_publication_recomposes_against_a_newer_market_head(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    moved = False
    try:
        first_market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, first_market, operation_id="financial-rebase-first")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            first_market,
            idempotency_key="financial-rebase-prior",
            contract=contract,
        )
        store = MountedGenerationStore(tmp_path)
        source_generation = _financial_generation(tmp_path, first_market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="financial-rebase-source",
            expected=first_market,
        )
        second_market = store.materialize_refresh(
            predecessor_manifest_sha256=source_generation,
            replacement_canonical=store.open_refresh_base(
                source_generation,
                overlap_session_count=3,
                universe_lookback_session_count=0,
            ).canonical,
            replace_from_session="2010-01-04",
            prepared_at=COLLECTED_AT + timedelta(hours=1),
            source_name="concurrent-market-refresh",
            source_lineage={"fixture": "same-market-content-new-root"},
        ).manifest_sha256

        def move_market_head(event: dict[str, object]) -> None:
            nonlocal moved
            if (
                not moved
                and event.get("event") == "data_refresh_phase_completed"
                and event.get("phase") == "validation"
            ):
                moved = True
                _establish_head(
                    database,
                    tmp_path,
                    second_market,
                    operation_id="financial-rebase-second",
                    expected=source_generation,
                )

        published = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
            lifecycle_event=move_market_head,
        ).publish(
            idempotency_key="financial-rebase",
            generation_manifest_sha256=source_generation,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        assert moved is True
        pointer = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert pointer is not None
        assert pointer.generation_manifest_sha256 == published.generation_manifest_sha256
        final = store.validate_generation(pointer.generation_manifest_sha256)
        newest_market = store.inspect_root(second_market)
        assert tuple(family.manifest_sha256 for family in final.families[:-1]) == tuple(
            family.manifest_sha256 for family in newest_market.families[:-1]
        )
        assert FinancialCandidateStore(tmp_path).source_generation_manifest_sha256(
            final.financial_candidate_manifest_sha256 or ""
        ) == first_market

        with database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'financial-rebase'
                """
            ).fetchone()
        assert operation is not None
        original_candidate = str(operation["candidate_manifest_sha256"])
        assert original_candidate == final.financial_candidate_manifest_sha256
        original_path = (
            tmp_path
            / "manifests"
            / "sha256"
            / original_candidate[:2]
            / f"{original_candidate}.json"
        )
        assert original_path.exists()
        published_root = str(published.generation_manifest_sha256)
        published_root_path = (
            tmp_path
            / "manifests"
            / "sha256"
            / published_root[:2]
            / f"{published_root}.json"
        )
        assert published_root_path.exists()

        successor_base = store.open_refresh_base(published.generation_manifest_sha256)
        successor = store.materialize_refresh(
            predecessor_manifest_sha256=published.generation_manifest_sha256,
            replacement_canonical=successor_base.canonical,
            replace_from_session="2026-08-07",
            prepared_at=COLLECTED_AT + timedelta(days=2),
            source_name="later-market-refresh",
            source_lineage={"fixture": "later-market-refresh"},
        )
        _establish_head(
            database,
            tmp_path,
            successor.manifest_sha256,
            operation_id="financial-rebase-successor",
            expected=published.generation_manifest_sha256,
        )

        collection = DataGarbageCollector(database, tmp_path).collect(
            idempotency_key="financial-rebase-gc"
        )
        assert collection.status == "succeeded"
        assert original_path.exists()
        assert not published_root_path.exists()
        source_root_path = (
            tmp_path
            / "manifests"
            / "sha256"
            / source_generation[:2]
            / f"{source_generation}.json"
        )
        assert not source_root_path.exists()

        replay_source = ExecutableStatementSource()
        replayed = FinancialRefreshService(
            database,
            tmp_path,
            replay_source,
            clock=lambda: COLLECTED_AT + timedelta(days=2),
        ).publish(
            idempotency_key="financial-rebase",
            generation_manifest_sha256=source_generation,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )
        assert replayed == published
        assert replay_source.requests == []
    finally:
        database.close()


def test_market_refresh_completes_while_financial_collection_is_blocked(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingFinancialSource(ExecutableStatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            started.set()
            assert release.wait(timeout=20)
            return super().query_raw(endpoint, params=params, fields=fields)

    class MarketSource:
        def __init__(self, canonical: dict[str, object]) -> None:
            self.canonical = canonical

        def collect(self, _plan: object) -> CanonicalSourceBatch:
            calendar = self.canonical["research_calendar"]
            assert isinstance(calendar, list)
            return CanonicalSourceBatch(
                source_name="concurrent-market-refresh",
                collection_kind="refresh",
                source_lineage={"fixture": "financial-collection-blocked"},
                canonical=self.canonical,
                covered_session_range=(str(calendar[0]), str(calendar[-1])),
            )

    database = _database(core_settings)
    try:
        initial_market = _market_generation(tmp_path)
        initial_canonical = MountedGenerationStore(tmp_path).open_refresh_base(
            initial_market
        ).canonical
        instruments = initial_canonical["instruments"]
        assert isinstance(instruments, list)
        initial_canonical["instruments"] = [
            row
            for row in instruments
            if isinstance(row, dict) and row["instrument_id"] == "equity:000001.SZ"
        ]
        market = (
            MountedGenerationStore(tmp_path)
            .materialize(
                initial_canonical,
                prepared_at=COLLECTED_AT,
                source_name="concurrent-market-base",
                source_lineage={"fixture": "single-instrument"},
            )
            .manifest_sha256
        )
        _establish_head(database, tmp_path, market, operation_id="concurrent-market-head")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="concurrent-market-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="concurrent-financial-source",
            expected=market,
        )
        financial = FinancialRefreshService(
            database,
            tmp_path,
            BlockingFinancialSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
        )

        market_canonical = MountedGenerationStore(tmp_path).open_refresh_base(
            source_generation
        ).canonical
        prices = market_canonical["prices"]
        assert isinstance(prices, list)
        corrected = next(
            row
            for row in prices
            if isinstance(row, dict) and row["session"] == "2026-08-13"
        )
        corrected["turnover_cny"] = "100001.00"
        market_refresh = DataRefreshService(
            database,
            tmp_path,
            benchmark_mount_root=benchmark_mount_for_data_mount(tmp_path),
            clock=lambda: COLLECTED_AT + timedelta(days=1, hours=12),
            heartbeat_seconds=1,
        )
        market_refresh.submit(
            idempotency_key="market-during-financial",
            as_of=COLLECTED_AT + timedelta(days=1, hours=12),
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                financial.publish,
                idempotency_key="blocked-financial",
                generation_manifest_sha256=source_generation,
                contract=contract,
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )
            assert started.wait(timeout=20)
            assert market_refresh.process_next(
                MarketSource(market_canonical),
                benchmark_source=FixtureBenchmarkSource(),
            ) is True
            market_outcome = market_refresh.inspect("market-during-financial")
            assert market_outcome.status == "succeeded"
            release.set()
            published = future.result(timeout=30)

        assert published.generation_manifest_sha256 is not None
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == published.generation_manifest_sha256
    finally:
        release.set()
        database.close()


def test_financial_publication_reconciles_a_post_cas_completion_failure(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market, operation_id="financial-reconcile-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="financial-reconcile-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="financial-reconcile-source",
            expected=market,
        )
        service = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
        )
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION data.reject_financial_freshness() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'completion failed'; END $$
                """
            )
            transaction.execute(
                """
                CREATE TRIGGER reject_financial_freshness
                BEFORE UPDATE OF last_financial_refresh_at ON data.current_dataset_state
                FOR EACH ROW EXECUTE FUNCTION data.reject_financial_freshness()
                """
            )

        with pytest.raises(Exception, match="completion failed"):
            service.publish(
                idempotency_key="financial-reconcile",
                generation_manifest_sha256=source_generation,
                contract=contract,
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )
        moved = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert moved is not None and moved.generation_manifest_sha256 != source_generation

        with database.transaction() as transaction:
            transaction.execute(
                "DROP TRIGGER reject_financial_freshness ON data.current_dataset_state"
            )
            transaction.execute("DROP FUNCTION data.reject_financial_freshness()")
        replayed = service.publish(
            idempotency_key="financial-reconcile",
            generation_manifest_sha256=source_generation,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        assert replayed.generation_manifest_sha256 == moved.generation_manifest_sha256
        assert MountedDatasetHeadStore(tmp_path).current_pointer() == moved
        assert DatasetOverviewService(database, tmp_path).overview().last_financial_refresh_at == (
            COLLECTED_AT + timedelta(days=1)
        )
    finally:
        database.close()


def test_financial_publication_recovers_head_move_before_receipt_commit(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market, operation_id="financial-receipt-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="financial-receipt-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="financial-receipt-source",
            expected=market,
        )
        lifecycle_events: list[dict[str, object]] = []
        service = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
            lifecycle_event=lifecycle_events.append,
        )
        prior_refresh_at = DatasetOverviewService(
            database, tmp_path
        ).overview().last_financial_refresh_at
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION data.reject_financial_publication_receipt() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'receipt commit failed'; END $$
                """
            )
            transaction.execute(
                """
                CREATE TRIGGER reject_financial_publication_receipt
                BEFORE UPDATE OF publication_head_moved_at
                ON data.financial_refresh_operations
                FOR EACH ROW
                WHEN (NEW.idempotency_key = 'financial-receipt-crash')
                EXECUTE FUNCTION data.reject_financial_publication_receipt()
                """
            )

        with pytest.raises(
            FinancialRefreshError,
            match="FINANCIAL_PUBLICATION_COMPLETION_PENDING",
        ):
            service.publish(
                idempotency_key="financial-receipt-crash",
                generation_manifest_sha256=source_generation,
                contract=contract,
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        failure_event = next(
            event for event in lifecycle_events if event["event"] == "data_refresh_failed"
        )
        assert failure_event["level"] == "ERROR"
        assert failure_event["failure_code"] == (
            "FINANCIAL_PUBLICATION_COMPLETION_PENDING"
        )

        moved = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert moved is not None and moved.generation_manifest_sha256 != source_generation
        with database.transaction() as transaction:
            state = transaction.execute(
                """
                SELECT publication_head_moved_at, published_generation_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'financial-receipt-crash'
                """
            ).fetchone()
            transaction.execute(
                """
                DROP TRIGGER reject_financial_publication_receipt
                ON data.financial_refresh_operations;
                DROP FUNCTION data.reject_financial_publication_receipt();
                """
            )
        assert state == {
            "publication_head_moved_at": None,
            "published_generation_manifest_sha256": None,
        }
        assert DatasetOverviewService(
            database, tmp_path
        ).overview().last_financial_refresh_at == prior_refresh_at

        store = MountedGenerationStore(tmp_path)
        successor_base = store.open_refresh_base(moved.generation_manifest_sha256)
        successor = store.materialize_refresh(
            predecessor_manifest_sha256=moved.generation_manifest_sha256,
            replacement_canonical=successor_base.canonical,
            replace_from_session="2026-08-07",
            prepared_at=COLLECTED_AT + timedelta(days=1, hours=1),
            source_name="market-after-receipt-loss",
            source_lineage={"fixture": "market-after-receipt-loss"},
        )
        _establish_head(
            database,
            tmp_path,
            successor.manifest_sha256,
            operation_id="financial-receipt-successor",
            expected=moved.generation_manifest_sha256,
        )
        successor_head = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert successor_head is not None
        assert successor_head.generation_manifest_sha256 == successor.manifest_sha256

        later_financial = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1, hours=2),
        ).publish(
            idempotency_key="financial-after-receipt-loss",
            generation_manifest_sha256=successor.manifest_sha256,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )
        assert later_financial.generation_manifest_sha256 is not None
        later_head = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert later_head is not None
        assert later_head.generation_manifest_sha256 == (
            later_financial.generation_manifest_sha256
        )

        replayed = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=2),
        ).publish(
            idempotency_key="financial-receipt-crash",
            generation_manifest_sha256=source_generation,
            contract=contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )
        assert replayed.generation_manifest_sha256 == moved.generation_manifest_sha256
        assert MountedDatasetHeadStore(tmp_path).current_pointer() == later_head
        with database.transaction() as transaction:
            recovered_operation = transaction.execute(
                """
                SELECT published_at FROM data.financial_refresh_operations
                WHERE idempotency_key = 'financial-receipt-crash'
                """
            ).fetchone()
        assert recovered_operation == {
            "published_at": COLLECTED_AT + timedelta(days=1)
        }
        assert DatasetOverviewService(
            database, tmp_path
        ).overview().last_financial_refresh_at == COLLECTED_AT + timedelta(
            days=1, hours=2
        )
        with database.transaction() as transaction:
            active_candidate = transaction.execute(
                """
                SELECT 1 FROM data.generation_candidates
                WHERE generation_manifest_sha256 = %s AND status = 'live'
                """,
                (moved.generation_manifest_sha256,),
            ).fetchone()
        assert active_candidate is None
    finally:
        database.close()


def test_stale_financial_target_cannot_overwrite_a_newer_financial_family(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class ChangedExecutableStatementSource(ExecutableStatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            response = super().query_raw(endpoint, params=params, fields=fields)
            row = list(response.items[0])
            row[7] = str(int(str(row[7])) + 1)
            return RawSourceResponse(response.fields, (tuple(row),))

    database = _database(core_settings)
    moved = False
    try:
        market = _market_generation(tmp_path)
        _establish_head(database, tmp_path, market, operation_id="financial-target-market")
        contract = _executable_contract()
        prior = _initial_candidate(
            database,
            tmp_path,
            ExecutableStatementSource(),
            market,
            idempotency_key="financial-target-prior",
            contract=contract,
        )
        source_generation = _financial_generation(tmp_path, market, prior)
        _establish_head(
            database,
            tmp_path,
            source_generation,
            operation_id="financial-target-source",
            expected=market,
        )

        def publish_other_financial_target(event: dict[str, object]) -> None:
            nonlocal moved
            if (
                not moved
                and event.get("event") == "data_refresh_phase_completed"
                and event.get("phase") == "validation"
            ):
                moved = True
                other = FinancialRefreshService(
                    database,
                    tmp_path,
                    ChangedExecutableStatementSource(),
                    clock=lambda: COLLECTED_AT + timedelta(hours=12),
                ).publish(
                    idempotency_key="financial-target-other",
                    generation_manifest_sha256=source_generation,
                    contract=contract,
                    prior_candidate_manifest_sha256=prior.manifest_sha256,
                    observation_through_session="2026-08-13",
                )
                assert other.generation_manifest_sha256 is not None

        stale = FinancialRefreshService(
            database,
            tmp_path,
            ExecutableStatementSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
            lifecycle_event=publish_other_financial_target,
        )
        with pytest.raises(FinancialRefreshError, match="FINANCIAL_TARGET_CHANGED"):
            stale.publish(
                idempotency_key="financial-target-stale",
                generation_manifest_sha256=source_generation,
                contract=contract,
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        head = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert moved is True and head is not None
        published = MountedGenerationStore(tmp_path).inspect_root(
            head.generation_manifest_sha256
        )
        assert published.financial_candidate_manifest_sha256 is not None
        assert published.financial_candidate_manifest_sha256 != prior.manifest_sha256
    finally:
        database.close()


def test_successful_refresh_candidate_survives_gc_until_composed_and_released(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    composable_fields = {
        "income": (*FIELDS[:7], "total_revenue", "n_income_attr_p", "update_flag"),
        "balancesheet": (
            *FIELDS[:7],
            "total_assets",
            "total_liab",
            "total_hldr_eqy_exc_min_int",
            "update_flag",
        ),
        "cashflow": (*FIELDS[:7], "n_cashflow_act", "update_flag"),
    }

    class ComposableSource(StatementSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            assert fields == composable_fields[endpoint]
            self.requests.append((endpoint, str(params["ts_code"]), "complete-history"))
            values = {
                "income": ("10", "4"),
                "balancesheet": ("20", "8", "12"),
                "cashflow": ("6",),
            }[endpoint]
            return RawSourceResponse(
                fields,
                (
                    (
                        str(params["ts_code"]),
                        "20100420",
                        "",
                        "20091231",
                        "1",
                        "1",
                        "4",
                        *values,
                        "0",
                    ),
                ),
            )

    composable_contract = FinancialCollectionContract(
        capability_sha256="c" * 64,
        endpoint_fields=tuple(
            (endpoint, composable_fields[endpoint]) for endpoint in FINANCIAL_ENDPOINTS
        ),
        suspected_truncation_row_counts=tuple((endpoint, None) for endpoint in FINANCIAL_ENDPOINTS),
        shards=(FinancialDateShard("complete-history"),),
    )
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            ComposableSource(),
            manifest,
            idempotency_key="retained-refresh-prior",
            contract=composable_contract,
        )
        service = FinancialRefreshService(
            database,
            tmp_path,
            ComposableSource(),
            clock=lambda: COLLECTED_AT + timedelta(days=1),
        )
        outcome = service.rebuild(
            idempotency_key="retained-refresh",
            generation_manifest_sha256=manifest,
            contract=composable_contract,
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        DataGarbageCollector(database, tmp_path).collect(idempotency_key="gc-retained-refresh")

        assert (
            service.rebuild(
                idempotency_key="retained-refresh",
                generation_manifest_sha256=manifest,
                contract=composable_contract,
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )
            == outcome
        )
        composite = MountedGenerationStore(tmp_path).compose_financial_candidate(
            manifest,
            outcome.candidate.manifest_sha256,
            prepared_at=COLLECTED_AT + timedelta(days=1),
        )
        DatasetLifecycle(database, tmp_path).protect_candidate(
            operation_id="retain-composed-financial",
            generation_manifest_sha256=composite.manifest_sha256,
            lease_seconds=60,
        )
        service.release("retained-refresh")
        DataGarbageCollector(database, tmp_path).collect(idempotency_key="gc-composed-financial")
        assert (
            MountedGenerationStore(tmp_path).validate_generation(composite.manifest_sha256)
            == composite
        )
    finally:
        database.close()


def test_refresh_resumes_durable_completed_shards(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="resume-prior",
        )
        source = StatementSource(interrupt_after=2)
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
            monotonic=lambda: 3.0,
        )

        with pytest.raises(KeyboardInterrupt):
            service.rebuild(
                idempotency_key="resumable-financial-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )
        outcome = service.rebuild(
            idempotency_key="resumable-financial-refresh",
            generation_manifest_sha256=manifest,
            contract=_contract(),
            prior_candidate_manifest_sha256=prior.manifest_sha256,
            observation_through_session="2026-08-13",
        )

        assert outcome.completed_shard_count == outcome.expected_shard_count == 6
        assert outcome.resumed_shard_count == 2
        assert len(source.requests) == 6
    finally:
        database.close()


def test_concurrent_duplicate_refresh_builds_one_candidate_attempt(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="concurrent-prior",
        )
        source = StatementSource()
        start = threading.Barrier(2)

        def rebuild() -> FinancialRefreshOutcome:
            start.wait(timeout=5)
            return FinancialRefreshService(
                database,
                tmp_path,
                source,
                clock=lambda: COLLECTED_AT,
            ).rebuild(
                idempotency_key="concurrent-financial-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(lambda _ordinal: rebuild(), range(2)))

        assert outcomes[0] == outcomes[1]
        assert len(source.requests) == 6
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'concurrent-financial-refresh'
                """
            ).fetchone()
        assert row is not None
        assert row["status"] == "succeeded"
        assert row["candidate_manifest_sha256"] == outcomes[0].candidate.manifest_sha256
    finally:
        database.close()


def test_checkpoint_conflict_marks_collection_and_refresh_failed(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="checkpoint-conflict-prior",
        )

        class DeleteClaimedShardSource(StatementSource):
            def query_raw(
                self,
                endpoint: str,
                *,
                params: dict[str, object],
                fields: tuple[str, ...],
            ) -> RawSourceResponse:
                with database.transaction() as transaction:
                    transaction.execute(
                        """
                        DELETE FROM data.financial_collection_shards
                        WHERE idempotency_key = 'checkpoint-conflict-refresh'
                          AND ordinal = 0
                        """
                    )
                return super().query_raw(endpoint, params=params, fields=fields)

        service = FinancialRefreshService(
            database,
            tmp_path,
            DeleteClaimedShardSource(),
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCollectionError, match="SHARD_CHECKPOINT_CONFLICT"):
            service.rebuild(
                idempotency_key="checkpoint-conflict-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            collection = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_collection_operations
                WHERE idempotency_key = 'checkpoint-conflict-refresh'
                """
            ).fetchone()
            refresh = transaction.execute(
                """
                SELECT status, failure_code, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'checkpoint-conflict-refresh'
                """
            ).fetchone()
        assert collection is not None and refresh is not None
        assert collection["status"] == refresh["status"] == "failed"
        assert (
            collection["failure_code"] == refresh["failure_code"] == ("SHARD_CHECKPOINT_CONFLICT")
        )
        assert refresh["candidate_manifest_sha256"] is None
    finally:
        database.close()


def test_invalid_market_generation_marks_refresh_failed(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="invalid-market-prior",
        )
        source = StatementSource()
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialRefreshError, match="FINANCIAL_MARKET_GENERATION_INVALID"):
            service.rebuild(
                idempotency_key="invalid-market-refresh",
                generation_manifest_sha256="f" * 64,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            refresh = transaction.execute(
                """
                SELECT status, failure_code, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'invalid-market-refresh'
                """
            ).fetchone()
        assert refresh is not None
        assert refresh["status"] == "failed"
        assert refresh["failure_code"] == "FINANCIAL_MARKET_GENERATION_INVALID"
        assert refresh["candidate_manifest_sha256"] is None
        assert source.requests == []
    finally:
        database.close()


def test_invalid_prior_fails_before_any_source_request(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="missing-prior-raw-evidence",
        )
        manifest_path = (
            tmp_path
            / "manifests"
            / "sha256"
            / prior.manifest_sha256[:2]
            / f"{prior.manifest_sha256}.json"
        )
        family = json.loads(manifest_path.read_bytes())
        evidence_sha256 = str(family["raw_evidence"]["manifest_sha256"])
        evidence_path = (
            tmp_path / "manifests" / "sha256" / evidence_sha256[:2] / f"{evidence_sha256}.json"
        )
        evidence = json.loads(evidence_path.read_bytes())
        chunk_sha256 = str(evidence["chunks"][0]["sha256"])
        chunk_path = tmp_path / "manifests" / "sha256" / chunk_sha256[:2] / f"{chunk_sha256}.json"
        chunk = json.loads(chunk_path.read_bytes())
        batch_sha256 = str(chunk["entries"][0]["batch_sha256"])
        (
            tmp_path / "financial" / "raw" / "sha256" / batch_sha256[:2] / f"{batch_sha256}.json"
        ).unlink()
        source = StatementSource()
        service = FinancialRefreshService(
            database,
            tmp_path,
            source,
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCandidateError, match="FINANCIAL_RAW_BATCH_INVALID"):
            service.rebuild(
                idempotency_key="missing-prior-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            refresh = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'missing-prior-refresh'
                """
            ).fetchone()
        assert refresh is not None
        assert refresh["status"] == "failed"
        assert refresh["failure_code"] == "FINANCIAL_RAW_BATCH_INVALID"
        assert source.requests == []
    finally:
        database.close()


def test_raw_batch_write_failure_marks_collection_and_refresh_failed(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="raw-write-prior",
        )
        raw_root = tmp_path / "financial" / "raw"
        preserved_raw = tmp_path / "financial" / "preserved-raw"

        class BlockRawWriteSource(StatementSource):
            def query_raw(
                self,
                endpoint: str,
                *,
                params: dict[str, object],
                fields: tuple[str, ...],
            ) -> RawSourceResponse:
                response = super().query_raw(endpoint, params=params, fields=fields)
                if not preserved_raw.exists():
                    raw_root.rename(preserved_raw)
                    raw_root.write_text("not-a-directory")
                return response

        service = FinancialRefreshService(
            database,
            tmp_path,
            BlockRawWriteSource(),
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCollectionError, match="RAW_BATCH_WRITE_FAILED"):
            service.rebuild(
                idempotency_key="raw-write-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        with database.transaction() as transaction:
            collection = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_collection_operations
                WHERE idempotency_key = 'raw-write-refresh'
                """
            ).fetchone()
            refresh = transaction.execute(
                """
                SELECT status, failure_code, candidate_manifest_sha256
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'raw-write-refresh'
                """
            ).fetchone()
        assert collection is not None and refresh is not None
        assert collection["status"] == refresh["status"] == "failed"
        assert collection["failure_code"] == refresh["failure_code"] == ("RAW_BATCH_WRITE_FAILED")
        assert refresh["candidate_manifest_sha256"] is None
    finally:
        database.close()


def test_refresh_failure_preserves_durable_collection_counts(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        prior = _initial_candidate(
            database,
            tmp_path,
            StatementSource(),
            manifest,
            idempotency_key="partial-failure-prior",
        )

        class FailAfterThreeSource(StatementSource):
            def query_raw(
                self,
                endpoint: str,
                *,
                params: dict[str, object],
                fields: tuple[str, ...],
            ) -> RawSourceResponse:
                if len(self.requests) == 3:
                    raise TushareSourceError("UPSTREAM_RATE_LIMITED", source_code=40203)
                return super().query_raw(endpoint, params=params, fields=fields)

        service = FinancialRefreshService(
            database,
            tmp_path,
            FailAfterThreeSource(),
            clock=lambda: COLLECTED_AT,
        )

        with pytest.raises(FinancialCollectionError, match="UPSTREAM_RATE_LIMITED"):
            service.rebuild(
                idempotency_key="partial-failure-refresh",
                generation_manifest_sha256=manifest,
                contract=_contract(),
                prior_candidate_manifest_sha256=prior.manifest_sha256,
                observation_through_session="2026-08-13",
            )

        collection_service = FinancialCollectionService(
            database,
            tmp_path,
            StatementSource(),
        )
        collection = collection_service.inspect_outcome("partial-failure-refresh")
        assert collection is not None
        assert collection.target_count == 6
        assert collection.completed_count == 3
        with database.transaction() as transaction:
            refresh = transaction.execute(
                """
                SELECT status, failure_code
                FROM data.financial_refresh_operations
                WHERE idempotency_key = 'partial-failure-refresh'
                """
            ).fetchone()
        assert refresh == {
            "status": "failed",
            "failure_code": "UPSTREAM_RATE_LIMITED",
        }
    finally:
        database.close()


def test_refresh_succeeded_state_requires_explicit_counts(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    try:
        with pytest.raises(CheckViolation), database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO data.financial_refresh_operations (
                    idempotency_key, fingerprint, generation_manifest_sha256,
                    prior_candidate_manifest_sha256, observation_through_session,
                    status, candidate_manifest_sha256, finished_at
                ) VALUES (%s, %s, %s, %s, %s, 'succeeded', %s, %s)
                """,
                (
                    "missing-success-counts",
                    "a" * 64,
                    "b" * 64,
                    "c" * 64,
                    "2026-08-13",
                    "d" * 64,
                    COLLECTED_AT,
                ),
            )
    finally:
        database.close()


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (RawSourceResponse(("ts_code", "unexpected"), (("000001.SZ", "x"),)), "SCHEMA_DRIFT"),
        (
            RawSourceResponse(
                FIELDS,
                tuple(
                    (
                        "000001.SZ",
                        "20260425",
                        "",
                        "20260331",
                        "1",
                        "1",
                        "1",
                        1,
                        "0",
                    )
                    for _ in range(10)
                ),
            ),
            "SUSPECTED_TRUNCATION",
        ),
        (TushareSourceError("MISSING_PERMISSION", source_code=2002), "MISSING_PERMISSION"),
        (
            RawSourceResponse(
                FIELDS,
                (
                    (
                        "000001.SZ",
                        "20261399",
                        "",
                        "20260331",
                        "1",
                        "1",
                        "1",
                        1,
                        "0",
                    ),
                ),
            ),
            "MALFORMED_FIELDS",
        ),
    ],
)
def test_collection_fails_closed_with_shard_diagnostics(
    core_settings: CoreSettings,
    tmp_path: Path,
    response: RawSourceResponse | TushareSourceError,
    expected_code: str,
) -> None:
    class FailingSource:
        def query_raw(self, *args: object, **kwargs: object) -> RawSourceResponse:
            if isinstance(response, TushareSourceError):
                raise response
            return response

    database = _database(core_settings)
    try:
        manifest = _market_generation(tmp_path)
        service = FinancialCollectionService(database, tmp_path, FailingSource())

        with pytest.raises(FinancialCollectionError) as failure:
            service.collect(
                idempotency_key=f"fail-{expected_code}",
                generation_manifest_sha256=manifest,
                contract=_contract(
                    suspected_truncation_row_count=(
                        10 if expected_code == "SUSPECTED_TRUNCATION" else None
                    )
                ),
            )

        assert failure.value.code == expected_code
        assert failure.value.endpoint == "income"
        assert failure.value.instrument == "000001.SZ"
        assert failure.value.shard == "complete-history"
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


def _contract(
    *,
    suspected_truncation_row_count: int | None = None,
    capability_sha256: str = "a" * 64,
) -> FinancialCollectionContract:
    return FinancialCollectionContract(
        capability_sha256=capability_sha256,
        endpoint_fields=tuple((endpoint, FIELDS) for endpoint in FINANCIAL_ENDPOINTS),
        suspected_truncation_row_counts=tuple(
            (endpoint, suspected_truncation_row_count) for endpoint in FINANCIAL_ENDPOINTS
        ),
        shards=(FinancialDateShard("complete-history"),),
    )


def _executable_contract() -> FinancialCollectionContract:
    return FinancialCollectionContract(
        capability_sha256="e" * 64,
        endpoint_fields=tuple(
            (endpoint, EXECUTABLE_FIELDS[endpoint]) for endpoint in FINANCIAL_ENDPOINTS
        ),
        suspected_truncation_row_counts=tuple(
            (endpoint, None) for endpoint in FINANCIAL_ENDPOINTS
        ),
        shards=(FinancialDateShard("complete-history"),),
    )


def _initial_candidate(
    database: PostgresDatabase,
    root: Path,
    source: StatementSource,
    generation_manifest_sha256: str,
    *,
    idempotency_key: str,
    contract: FinancialCollectionContract | None = None,
) -> FinancialFamilyCandidate:
    collection = FinancialCollectionService(
        database,
        root,
        source,
        clock=lambda: COLLECTED_AT,
    )
    collection.collect(
        idempotency_key=idempotency_key,
        generation_manifest_sha256=generation_manifest_sha256,
        contract=contract or _contract(),
    )
    return FinancialCandidateStore(root).materialize(
        collection.completed_snapshot(idempotency_key),
        observation_through_session="2026-08-13",
    )


def _market_generation(
    root: Path,
    *,
    sessions: tuple[str, ...] = ("2010-01-04", "2026-08-07", "2026-08-13"),
    second_listed_to: str = "2020-01-01",
) -> str:
    canonical = build_minimal_canonical_fixture()
    price = dict(canonical["prices"][0])
    state = dict(canonical["trading_states"][0])
    limits = dict(canonical["price_limits"][0])
    pool = dict(canonical["base_pool"][0])
    universes = {name: dict(rows[0]) for name, rows in canonical["liquidity_universes"].items()}
    canonical["research_calendar"] = list(sessions)
    canonical["prices"] = [dict(price, session=session) for session in sessions]
    canonical["trading_states"] = [dict(state, session=session) for session in sessions]
    canonical["price_limits"] = [dict(limits, session=session) for session in sessions]
    canonical["base_pool"] = [dict(pool, session=session) for session in sessions]
    canonical["liquidity_universes"] = {
        name: [dict(row, session=session) for session in sessions]
        for name, row in universes.items()
    }
    catalog = dict(canonical["field_catalog"][0])
    catalog["release_available_from"] = sessions[0]
    canonical["field_catalog"] = [catalog]
    instruments = list(canonical["instruments"])
    instruments.append(
        {
            "instrument_id": "equity:000002.SZ",
            "ts_code": "000002.SZ",
            "asset_type": "ordinary_a_share",
            "exchange": "SZSE",
            "board": "main",
            "listed_from": "1991-01-29",
            "listed_to": second_listed_to,
        }
    )
    canonical["instruments"] = instruments
    return (
        MountedGenerationStore(root)
        .materialize(
            canonical,
            prepared_at=datetime(2026, 8, 13, tzinfo=UTC),
            source_name="financial-collection-test",
            source_lineage={"fixture": "historical-identities"},
        )
        .manifest_sha256
    )


def _financial_generation(
    root: Path,
    market_generation_manifest_sha256: str,
    candidate: FinancialFamilyCandidate,
) -> str:
    return (
        MountedGenerationStore(root)
        .compose_financial_candidate(
            market_generation_manifest_sha256,
            candidate.manifest_sha256,
            prepared_at=COLLECTED_AT,
            publication_coordinate=candidate.manifest_sha256,
        )
        .manifest_sha256
    )


def _establish_head(
    database: PostgresDatabase,
    root: Path,
    generation_manifest_sha256: str,
    *,
    operation_id: str,
    expected: str | None = None,
) -> None:
    lifecycle = DatasetLifecycle(database, root)
    lifecycle.protect_candidate(
        operation_id=operation_id,
        generation_manifest_sha256=generation_manifest_sha256,
        lease_seconds=60,
    )
    lifecycle.compare_and_swap_head(
        expected_generation_manifest_sha256=expected,
        candidate_generation_manifest_sha256=generation_manifest_sha256,
        operation_id=operation_id,
    )


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    with database.transaction() as transaction:
        transaction.execute(
            "TRUNCATE data.financial_daily_refresh_operations, "
            "data.financial_refresh_operations, "
            "data.financial_collection_shards, "
            "data.financial_raw_batches, data.financial_collection_operations CASCADE"
        )
        transaction.execute(
            "UPDATE data.current_dataset_state SET last_financial_refresh_at = NULL "
            "WHERE singleton = 1"
        )
    return database
