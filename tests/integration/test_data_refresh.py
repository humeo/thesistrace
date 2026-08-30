from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Inexact, localcontext
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest
from benchmark_support import FixtureBenchmarkSource, benchmark_mount_for_data_mount
from canonical_store import open_complete_refresh_basis
from psycopg.errors import CheckViolation

import thesistrace.data.refresh as refresh_module
from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import _append_session
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import normalize_tushare_snapshot
from thesistrace.benchmark import (
    BenchmarkLevel,
    BenchmarkLevelSource,
    BenchmarkSnapshotStore,
)
from thesistrace.data import (
    CanonicalSourceBatch,
    CollectionPlan,
    DataRefreshError,
    DataRefreshService,
    DatasetLifecycle,
    DatasetOperationalStatusService,
    DatasetOverviewService,
    MountedGenerationStore,
    RefreshOutcome,
)
from thesistrace.data.head_store import MountedDatasetHeadStore
from thesistrace.data.source import DataSourceError
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture

AS_OF = datetime(2026, 9, 7, 9, tzinfo=UTC)
CORRECTION_AS_OF = datetime(2026, 7, 28, 10, tzinfo=UTC)
REPLAY_AS_OF = datetime(2026, 8, 3, 9, tzinfo=UTC)
FIRST_PREPARED_AT = datetime(2026, 9, 7, 9, 30, tzinfo=UTC)
FIRST_BENCHMARK_PUBLISHED_AT = datetime(2026, 9, 7, 9, 45, tzinfo=UTC)
FIRST_REFRESH_AT = datetime(2026, 9, 7, 10, tzinfo=UTC)
SECOND_REFRESH_AT = datetime(2026, 9, 7, 11, tzinfo=UTC)


class RecordingRefreshSource:
    def __init__(self, candidate: dict[str, object]) -> None:
        self.candidate = candidate
        self.plans: list[CollectionPlan] = []

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        self.plans.append(plan)
        calendar = self.candidate["research_calendar"]
        assert isinstance(calendar, list)
        return CanonicalSourceBatch(
            source_name="recording-refresh-source",
            collection_kind="refresh",
            source_lineage={"fixture": "refresh-v1"},
            canonical=copy.deepcopy(self.candidate),
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


class UnavailableRefreshSource:
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        error = DataSourceError("unavailable", detail_code="UPSTREAM_UNAVAILABLE")
        error.args = ("canary-secret dependency at /private/data-source",)
        raise error


class ReplayRefreshProvider:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]:
        return copy.deepcopy(self.snapshot)  # type: ignore[return-value]


def _refresh_service(
    database: PostgresDatabase,
    mount_root: Path,
    **options: object,
) -> DataRefreshService:
    return DataRefreshService(
        database,
        mount_root,
        benchmark_mount_root=benchmark_mount_for_data_mount(mount_root),
        **options,
    )


def _overview_service(
    database: PostgresDatabase,
    mount_root: Path,
) -> DatasetOverviewService:
    return DatasetOverviewService(
        database,
        mount_root,
        benchmark_mount_for_data_mount(mount_root),
    )


def _process_next(
    service: DataRefreshService,
    source: object,
    benchmark_source: BenchmarkLevelSource | None = None,
) -> bool:
    return service.process_next(  # type: ignore[arg-type]
        source,
        benchmark_source=benchmark_source or FixtureBenchmarkSource(),
    )


def test_private_refresh_is_async_moves_head_and_records_successful_freshness(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original_manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        source = RecordingRefreshSource(candidate)
        operator_times = iter((FIRST_PREPARED_AT, FIRST_BENCHMARK_PUBLISHED_AT, FIRST_REFRESH_AT))
        lifecycle_events: list[dict[str, object]] = []
        published_sessions: list[str] = []

        def lossy_lifecycle(event: dict[str, object]) -> None:
            lifecycle_events.append(event)
            if event.get("phase") == "publication":
                pointer = DatasetLifecycle(database, tmp_path).current_pointer()
                assert pointer is not None
                published_sessions.append(pointer.data_through_session)
            if event.get("phase") in {"market", "publication"}:
                raise RuntimeError("simulated telemetry loss with canary-secret at /private/source")

        refresh = _refresh_service(
            database,
            tmp_path,
            clock=lambda: next(operator_times),
            lifecycle_event=lossy_lifecycle,
        )

        def reject_revalidation(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("refresh revalidated its producer-validated Candidate")

        monkeypatch.setattr(
            MountedGenerationStore,
            "validate_generation",
            reject_revalidation,
        )

        accepted = _operator_command(
            core_settings,
            tmp_path,
            ["refresh", "--idempotency-key", "refresh-once", "--as-of", AS_OF.isoformat()],
        )

        assert accepted["status"] == "accepted"
        assert source.plans == []
        assert refresh.inspect("refresh-once").__dict__ == accepted
        benchmark_source = FixtureBenchmarkSource()
        assert _process_next(refresh, source, benchmark_source) is True

        terminal = _operator_command(
            core_settings,
            tmp_path,
            ["inspect-refresh", "--idempotency-key", "refresh-once"],
        )
        assert terminal["status"] == "succeeded"
        assert terminal["outcome"] == "published"
        assert terminal["last_refresh_at"] == FIRST_REFRESH_AT.isoformat()
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 != original_manifest
        assert (
            open_complete_refresh_basis(
                MountedGenerationStore(tmp_path), head.generation_manifest_sha256
            )
            == candidate
        )
        assert head.prepared_at == FIRST_PREPARED_AT.isoformat()
        snapshot = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read()
        assert snapshot is not None
        assert snapshot.coverage_end_session == candidate["research_calendar"][-1]
        assert snapshot.published_at == "2026-09-07T09:45:00Z"
        assert benchmark_source.requests == [("2010-01-04", candidate["research_calendar"][-1])]
        assert len(source.plans) == 1
        plan = source.plans[0]
        assert plan.kind == "refresh"
        assert plan.overlap_start_session == current["research_calendar"][-20]
        assert plan.after_session == current["research_calendar"][-1]
        assert plan.completed_through_date.isoformat() == "2026-09-07"
        overview = _overview_service(database, tmp_path).overview()
        assert overview.last_market_refresh_at == FIRST_REFRESH_AT
        assert overview.data_through_session.isoformat() == candidate["research_calendar"][-1]
        assert overview.benchmark_coverage is not None
        assert overview.benchmark_coverage.model_dump(mode="json") == {
            "start": "2010-01-04",
            "end": candidate["research_calendar"][-1],
        }
        assert overview.benchmark_snapshot_sha256 == snapshot.sha256
        assert overview.benchmark_last_published_at == FIRST_BENCHMARK_PUBLISHED_AT
        assert overview.benchmark_research_readiness is True
        assert [event["event"] for event in lifecycle_events] == [
            "data_refresh_started",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_succeeded",
        ]
        operation_ids = {str(event["operation_id"]) for event in lifecycle_events}
        assert len(operation_ids) == 1
        assert next(iter(operation_ids)).startswith("refresh:")
        assert [
            event["phase"]
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
        ] == [
            "current_head",
            "market",
            "validation",
            "materialization",
            "benchmark",
            "candidate_validation",
            "publication",
        ]
        assert all(
            isinstance(event["duration_ms"], int) and event["duration_ms"] >= 0
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
        )
        assert published_sessions == [candidate["research_calendar"][-1]]
        assert "canary-secret" not in json.dumps(lifecycle_events)
        assert "/private/source" not in json.dumps(lifecycle_events)
    finally:
        database.close()


def test_data_overview_reports_a_lagging_benchmark_snapshot_as_not_ready(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        prior_session = str(current["research_calendar"][-2])
        snapshot = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).publish(
            (
                BenchmarkLevel("2010-01-04", "1"),
                BenchmarkLevel(prior_session, "2"),
            ),
            published_at=FIRST_BENCHMARK_PUBLISHED_AT,
        )

        overview = _overview_service(database, tmp_path).overview()

        assert overview.benchmark_coverage is not None
        assert overview.benchmark_coverage.model_dump(mode="json") == {
            "start": "2010-01-04",
            "end": prior_session,
        }
        assert overview.benchmark_snapshot_sha256 == snapshot.sha256
        assert overview.benchmark_last_published_at == FIRST_BENCHMARK_PUBLISHED_AT
        assert overview.benchmark_research_readiness is False
    finally:
        database.close()


def test_market_refresh_without_industry_input_reuses_industry_family_manifest(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original_manifest = _establish_head(database, tmp_path, current)
        original = MountedGenerationStore(tmp_path).inspect_root(original_manifest)
        original_industry = next(
            family
            for family in original.families
            if family.family_id == "equity.industry_membership"
        )
        market_candidate = copy.deepcopy(current)
        _append_session(market_candidate)
        del market_candidate["industry_membership"]
        refresh = _refresh_service(
            database,
            tmp_path,
            clock=iter(
                (FIRST_PREPARED_AT, FIRST_BENCHMARK_PUBLISHED_AT, FIRST_REFRESH_AT)
            ).__next__,
        )
        refresh.submit(idempotency_key="market-only-refresh", as_of=AS_OF)

        assert _process_next(refresh, RecordingRefreshSource(market_candidate)) is True

        pointer = DatasetLifecycle(database, tmp_path).current_pointer()
        assert pointer is not None
        published = MountedGenerationStore(tmp_path).validate_generation(
            pointer.generation_manifest_sha256
        )
        published_industry = next(
            family
            for family in published.families
            if family.family_id == "equity.industry_membership"
        )
        assert published.data_through_session == market_candidate["research_calendar"][-1]
        assert published_industry.manifest_sha256 == original_industry.manifest_sha256
        assert published_industry.dataset_coverage == original_industry.dataset_coverage
    finally:
        database.close()


def test_refresh_reports_only_canonical_phase_timings(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        lifecycle_events: list[dict[str, object]] = []
        timestamps = iter(float(value) for value in range(16))
        operator_times = iter((FIRST_PREPARED_AT, FIRST_BENCHMARK_PUBLISHED_AT, FIRST_REFRESH_AT))
        refresh = _refresh_service(
            database,
            tmp_path,
            clock=lambda: next(operator_times),
            lifecycle_event=lifecycle_events.append,
            monotonic=lambda: next(timestamps),
        )
        refresh.submit(idempotency_key="timed-refresh", as_of=AS_OF)

        assert _process_next(refresh, RecordingRefreshSource(candidate)) is True

        phase_events = [
            event for event in lifecycle_events if event["event"] == "data_refresh_phase_completed"
        ]
        assert [event["phase"] for event in phase_events] == [
            "current_head",
            "market",
            "validation",
            "materialization",
            "benchmark",
            "candidate_validation",
            "publication",
        ]
        assert [event["duration_ms"] for event in phase_events] == [1000] * 7
    finally:
        database.close()


def test_refresh_submission_reads_only_head_and_root_manifest(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        _establish_head(database, tmp_path, _twenty_session_canonical())

        def reject_table_manifest_read(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("refresh submission must not inspect table manifests")

        monkeypatch.setattr(
            MountedGenerationStore,
            "_read_table_manifest",
            reject_table_manifest_read,
        )

        accepted = _refresh_service(database, tmp_path).submit(
            idempotency_key="lightweight-submit",
            as_of=AS_OF,
        )

        assert accepted.status == "accepted"
    finally:
        with database.transaction() as transaction:
            transaction.execute(
                "DELETE FROM data.refresh_operations WHERE idempotency_key = %s",
                ("lightweight-submit",),
            )
        database.close()


def test_refresh_publishes_a_physically_valid_family_candidate(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        current_manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key="single-candidate-validation", as_of=AS_OF)

        assert _process_next(refresh, RecordingRefreshSource(candidate)) is True

        published = DatasetLifecycle(database, tmp_path).current_pointer()
        assert published is not None
        assert published.generation_manifest_sha256 != current_manifest
        descriptor = MountedGenerationStore(tmp_path).validate_generation(
            published.generation_manifest_sha256
        )
        assert descriptor.data_through_session == candidate["research_calendar"][-1]
    finally:
        database.close()


def test_identical_refresh_keeps_generation_and_advances_last_refresh_time(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        source = RecordingRefreshSource(current)
        lifecycle_events: list[dict[str, object]] = []
        refresh = _refresh_service(
            database,
            tmp_path,
            clock=lambda: SECOND_REFRESH_AT,
            lifecycle_event=lifecycle_events.append,
        )

        first = refresh.submit(idempotency_key="no-change", as_of=AS_OF)
        replay = refresh.submit(idempotency_key="no-change", as_of=AS_OF)
        assert replay == first
        benchmark_source = FixtureBenchmarkSource()
        assert _process_next(refresh, source, benchmark_source) is True

        terminal = refresh.inspect("no-change")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "no_change"
        assert terminal.last_refresh_at == SECOND_REFRESH_AT.isoformat()
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        snapshot = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read()
        assert snapshot is not None
        assert snapshot.coverage_end_session == current["research_calendar"][-1]
        assert benchmark_source.requests == [("2010-01-04", current["research_calendar"][-1])]
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            SECOND_REFRESH_AT
        )
        assert [
            event.get("phase")
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
        ] == ["current_head", "market", "validation", "benchmark"]
        assert lifecycle_events[-1]["event"] == "data_refresh_succeeded"
        assert lifecycle_events[-1]["outcome"] == "no_change"
    finally:
        database.close()


def test_refresh_no_change_detection_does_not_serialize_the_canonical_dataset(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path, clock=lambda: SECOND_REFRESH_AT)
        refresh.submit(idempotency_key="no-canonical-json", as_of=AS_OF)

        def reject_canonical_serialization(*_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("refresh processing must not serialize the Canonical dataset")

        monkeypatch.setattr(
            refresh_module,
            "canonical_json_bytes",
            reject_canonical_serialization,
        )

        assert _process_next(refresh, RecordingRefreshSource(current)) is True
        assert refresh.inspect("no-canonical-json").outcome == "no_change"
    finally:
        database.close()


def test_refresh_rejects_incomplete_benchmark_before_moving_head(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    class IncompleteBenchmarkSource:
        def collect_open_levels(
            self,
            *,
            start_session: str,
            end_session: str,
        ) -> tuple[BenchmarkLevel, ...]:
            assert start_session == "2010-01-04"
            return (BenchmarkLevel("2010-01-04", "3592.47"),)

    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original_manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key="incomplete-benchmark", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            _process_next(
                refresh,
                RecordingRefreshSource(candidate),
                IncompleteBenchmarkSource(),
            )

        assert failure.value.code == "BENCHMARK_COVERAGE_INSUFFICIENT"
        terminal = refresh.inspect("incomplete-benchmark")
        assert terminal.status == "failed"
        assert terminal.failure_code == "BENCHMARK_COVERAGE_INSUFFICIENT"
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == original_manifest
        assert BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read() is None
    finally:
        database.close()


def test_refresh_snapshot_can_lead_when_a_competing_head_wins(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original_manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        winner_canonical = copy.deepcopy(candidate)
        winner_prices = winner_canonical["prices"]
        assert isinstance(winner_prices, list)
        winner_price = winner_prices[-1]
        assert isinstance(winner_price, dict)
        winner_price["turnover_cny"] = "999999.00"
        winner = MountedGenerationStore(tmp_path).materialize(
            winner_canonical,
            prepared_at=FIRST_PREPARED_AT,
            source_name="competing-refresh",
            source_lineage={"winner": True},
        )
        winner_published = False

        def publish_competing_head_after_benchmark(event: dict[str, object]) -> None:
            nonlocal winner_published
            if event.get("phase") != "benchmark" or event.get("outcome") != "completed":
                return
            snapshot = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read()
            assert snapshot is not None
            assert snapshot.coverage_end_session == candidate["research_calendar"][-1]
            lifecycle = DatasetLifecycle(database, tmp_path)
            lifecycle.protect_candidate(
                operation_id="competing-refresh",
                generation_manifest_sha256=winner.manifest_sha256,
                lease_seconds=60,
            )
            lifecycle.compare_and_swap_head(
                expected_generation_manifest_sha256=original_manifest,
                candidate_generation_manifest_sha256=winner.manifest_sha256,
                operation_id="competing-refresh",
            )
            winner_published = True

        refresh = _refresh_service(
            database,
            tmp_path,
            max_attempts=1,
            lifecycle_event=publish_competing_head_after_benchmark,
            clock=iter((FIRST_PREPARED_AT, FIRST_BENCHMARK_PUBLISHED_AT)).__next__,
        )
        refresh.submit(idempotency_key="benchmark-before-head", as_of=AS_OF)

        with pytest.raises(DataRefreshError, match="HEAD_CHANGED"):
            _process_next(refresh, RecordingRefreshSource(candidate))

        assert winner_published is True
        snapshot = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read()
        assert snapshot is not None
        assert snapshot.coverage_end_session == candidate["research_calendar"][-1]
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == winner.manifest_sha256
        terminal = refresh.inspect("benchmark-before-head")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.last_failure_code == "HEAD_CHANGED"
    finally:
        database.close()


def test_invalid_refresh_candidate_leaves_the_current_head_and_freshness_unchanged(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        invalid = copy.deepcopy(current)
        invalid["prices"] = []
        lifecycle_events: list[dict[str, object]] = []
        refresh = _refresh_service(
            database,
            tmp_path,
            clock=lambda: FIRST_REFRESH_AT,
            lifecycle_event=lifecycle_events.append,
        )
        refresh.submit(idempotency_key="invalid-candidate", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            _process_next(refresh, RecordingRefreshSource(invalid))

        assert failure.value.code == "INVALID_CANONICAL_DATA"
        terminal = refresh.inspect("invalid-candidate")
        assert terminal.status == "failed"
        assert terminal.failure_code == "INVALID_CANONICAL_DATA"
        assert terminal.last_refresh_at is None
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        overview = _overview_service(database, tmp_path).overview()
        assert overview.last_market_refresh_at == prior_refresh_at
        failure_event = next(
            event for event in lifecycle_events if event["event"] == "data_refresh_failed"
        )
        assert failure_event["level"] == "ERROR"
        assert failure_event["phase"] == "validation"
        assert failure_event["failure_code"] == "INVALID_CANONICAL_DATA"
        assert not [
            event for event in lifecycle_events if event["event"] == "data_refresh_succeeded"
        ]
    finally:
        database.close()


def test_refresh_worker_command_processes_a_deterministic_replay(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        fixture_path = (
            Path(__file__).resolve().parents[1] / "fixtures" / "tushare-bootstrap-replay-v2.json"
        )
        replay = json.loads(fixture_path.read_text())
        _source, current = normalize_tushare_snapshot(replay["snapshot"])
        manifest = _establish_head(database, tmp_path, current)
        replay.update(
            {
                "format": "thesistrace-tushare-refresh-replay",
                "version": 3,
                "request_start": current["research_calendar"][0],
                "request_end": "2026-08-03",
                "financial": {},
                "financial_refresh": None,
            }
        )
        refresh_replay = tmp_path / "refresh-replay.json"
        refresh_replay.write_text(json.dumps(replay, sort_keys=True, separators=(",", ":")))
        _operator_command(
            core_settings,
            tmp_path,
            [
                "refresh",
                "--idempotency-key",
                "worker-replay",
                "--as-of",
                REPLAY_AS_OF.isoformat(),
            ],
        )

        processed, operator_events = _operator_command_with_events(
            core_settings,
            tmp_path,
            ["worker", "--once", "--replay", os.fspath(refresh_replay)],
        )

        assert processed == {"status": "processed"}
        assert [event["event"] for event in operator_events] == [
            "data_refresh_started",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_phase_completed",
            "data_refresh_succeeded",
        ]
        assert all(event["component"] == "data_operator" for event in operator_events)
        assert len({event["operation_id"] for event in operator_events}) == 1
        terminal = _operator_command(
            core_settings,
            tmp_path,
            ["inspect-refresh", "--idempotency-key", "worker-replay"],
        )
        assert terminal["status"] == "succeeded"
        assert terminal["outcome"] == "no_change"
        assert terminal["last_refresh_at"] is not None
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at is not None
    finally:
        database.close()


def test_concurrent_workers_publish_one_authoritative_refresh(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    started = threading.Event()
    release = threading.Event()

    class BlockingSource(RecordingRefreshSource):
        def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
            started.set()
            assert release.wait(timeout=10)
            return super().collect(plan)

    try:
        current = _twenty_session_canonical()
        original = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        source = BlockingSource(candidate)
        first = _refresh_service(database, tmp_path, heartbeat_seconds=1)
        second = _refresh_service(database, tmp_path, heartbeat_seconds=1)
        first.submit(idempotency_key="concurrent-workers", as_of=AS_OF)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                first.process_next,
                source,
                benchmark_source=FixtureBenchmarkSource(),
            )
            assert started.wait(timeout=10)
            with database.transaction() as transaction:
                running = transaction.execute(
                    """
                    SELECT phase, last_heartbeat_at
                    FROM data.refresh_operations
                    WHERE idempotency_key = 'concurrent-workers'
                    """
                ).fetchone()
                running_count = transaction.execute(
                    """
                    SELECT count(*) AS count
                    FROM data.refresh_operations
                    WHERE status = 'running'
                    """
                ).fetchone()
            assert running is not None
            assert running["phase"] == "market"
            assert running["last_heartbeat_at"] is not None
            assert running_count == {"count": 1}
            assert _process_next(second, source) is False
            release.set()
            assert future.result(timeout=10) is True

        terminal = first.inspect("concurrent-workers")
        assert terminal.status == "succeeded"
        assert terminal.attempt_count == 1
        with database.transaction() as transaction:
            terminal_state = transaction.execute(
                """
                SELECT phase, last_heartbeat_at
                FROM data.refresh_operations
                WHERE idempotency_key = 'concurrent-workers'
                """
            ).fetchone()
        assert terminal_state is not None
        assert terminal_state["phase"] == "publication"
        assert terminal_state["last_heartbeat_at"] is not None
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 != original
        assert (
            open_complete_refresh_basis(
                MountedGenerationStore(tmp_path), head.generation_manifest_sha256
            )
            == candidate
        )
    finally:
        release.set()
        database.close()


def test_refresh_submission_replay_and_fifo_cannot_duplicate_work(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)

        accepted = refresh.submit(idempotency_key="submission-replay", as_of=AS_OF)
        assert refresh.submit(idempotency_key="submission-replay", as_of=AS_OF) == accepted
        with pytest.raises(DataRefreshError) as conflicting_reuse:
            refresh.submit(
                idempotency_key="submission-replay",
                as_of=AS_OF.replace(hour=10),
            )
        assert conflicting_reuse.value.code == "IDEMPOTENCY_KEY_CONFLICT"
        queued = refresh.submit(idempotency_key="another-refresh", as_of=AS_OF)
        assert queued.status == "accepted"
        assert queued.kind == "market"
        assert queued.as_of == AS_OF.isoformat()

        assert _process_next(refresh, RecordingRefreshSource(current)) is True
        assert refresh.inspect("submission-replay").status == "succeeded"
        assert refresh.inspect("another-refresh").status == "accepted"
        assert _process_next(refresh, RecordingRefreshSource(current)) is True
        assert refresh.inspect("another-refresh").status == "succeeded"
        with database.transaction() as transaction:
            count = transaction.execute(
                """
                SELECT count(*) AS count FROM data.refresh_operations
                WHERE idempotency_key IN ('submission-replay', 'another-refresh')
                """
            ).fetchone()
        assert count == {"count": 2}
    finally:
        database.close()


def test_concurrent_identical_submission_returns_one_durable_receipt(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    barrier = threading.Barrier(3)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)

        def submit() -> RefreshOutcome:
            barrier.wait(timeout=10)
            return refresh.submit(idempotency_key="concurrent-replay", as_of=AS_OF)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit) for _ in range(2)]
            barrier.wait(timeout=10)
            receipts = [future.result(timeout=10) for future in futures]

        assert receipts[0] == receipts[1]
        with database.transaction() as transaction:
            count = transaction.execute(
                """
                SELECT count(*) AS count FROM data.refresh_operations
                WHERE idempotency_key = 'concurrent-replay'
                """
            ).fetchone()
        assert count == {"count": 1}
    finally:
        _delete_refresh_operations(database, "concurrent-replay")
        database.close()


def test_concurrent_conflicting_submission_admits_exactly_one_request(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    barrier = threading.Barrier(3)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)

        def submit(as_of: datetime) -> tuple[str, str]:
            barrier.wait(timeout=10)
            try:
                receipt = refresh.submit(
                    idempotency_key="concurrent-conflict",
                    as_of=as_of,
                )
            except DataRefreshError as error:
                return "rejected", error.code
            return "accepted", receipt.as_of

        targets = (AS_OF, AS_OF + timedelta(hours=1))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, target) for target in targets]
            barrier.wait(timeout=10)
            results = [future.result(timeout=10) for future in futures]

        assert sorted(result[0] for result in results) == ["accepted", "rejected"]
        assert ("rejected", "IDEMPOTENCY_KEY_CONFLICT") in results
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT as_of FROM data.refresh_operations
                WHERE idempotency_key = 'concurrent-conflict'
                """
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["as_of"] in targets
    finally:
        _delete_refresh_operations(database, "concurrent-conflict")
        database.close()


def test_concurrent_distinct_submissions_both_enter_the_fifo(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    barrier = threading.Barrier(3)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)

        def submit(key: str) -> RefreshOutcome:
            barrier.wait(timeout=10)
            return refresh.submit(idempotency_key=key, as_of=AS_OF)

        keys = ("concurrent-fifo-a", "concurrent-fifo-b")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, key) for key in keys]
            barrier.wait(timeout=10)
            receipts = [future.result(timeout=10) for future in futures]

        assert {receipt.idempotency_key for receipt in receipts} == set(keys)
        assert {receipt.status for receipt in receipts} == {"accepted"}
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT idempotency_key, status FROM data.refresh_operations
                WHERE idempotency_key = ANY(%s)
                """,
                (list(keys),),
            ).fetchall()
        assert {(row["idempotency_key"], row["status"]) for row in rows} == {
            ("concurrent-fifo-a", "accepted"),
            ("concurrent-fifo-b", "accepted"),
        }
    finally:
        _delete_refresh_operations(database, "concurrent-fifo-a", "concurrent-fifo-b")
        database.close()


def test_financial_and_industry_submission_share_exact_idempotency_and_the_market_fifo(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)

        market = refresh.submit(idempotency_key="fifo-market", as_of=AS_OF)
        financial = refresh.submit_financial(
            idempotency_key="fifo-financial",
            observation_through_session=current["research_calendar"][-1],
        )
        industry = refresh.submit_industry(
            idempotency_key="fifo-industry",
            observation_through_session=current["research_calendar"][-1],
        )

        assert market.kind == "market"
        assert market.as_of == AS_OF.isoformat()
        assert market.observation_through_session is None
        assert financial.kind == "financial"
        assert financial.as_of is None
        assert financial.observation_through_session == current["research_calendar"][-1]
        assert financial.status == "accepted"
        assert industry.kind == "industry"
        assert industry.as_of is None
        assert industry.observation_through_session == current["research_calendar"][-1]
        assert industry.status == "accepted"
        assert (
            refresh.submit_financial(
                idempotency_key="fifo-financial",
                observation_through_session=current["research_calendar"][-1],
            )
            == financial
        )
        with pytest.raises(DataRefreshError) as conflict:
            refresh.submit_financial(
                idempotency_key="fifo-financial",
                observation_through_session=current["research_calendar"][-2],
            )
        assert conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"
        assert (
            refresh.submit_industry(
                idempotency_key="fifo-industry",
                observation_through_session=current["research_calendar"][-1],
            )
            == industry
        )
        with pytest.raises(DataRefreshError) as industry_conflict:
            refresh.submit_industry(
                idempotency_key="fifo-industry",
                observation_through_session=current["research_calendar"][-2],
            )
        assert industry_conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"

        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT idempotency_key, kind, as_of, observation_through_session
                FROM data.refresh_operations
                WHERE idempotency_key IN (
                    'fifo-market', 'fifo-financial', 'fifo-industry'
                )
                ORDER BY created_at, idempotency_key
                """
            ).fetchall()
        assert [row["idempotency_key"] for row in rows] == [
            "fifo-market",
            "fifo-financial",
            "fifo-industry",
        ]
        assert rows[0]["as_of"] == AS_OF
        assert rows[0]["observation_through_session"] is None
        assert rows[1]["as_of"] is None
        assert (
            rows[1]["observation_through_session"].isoformat() == (current["research_calendar"][-1])
        )
        assert rows[2]["as_of"] is None
        assert (
            rows[2]["observation_through_session"].isoformat() == (current["research_calendar"][-1])
        )
    finally:
        _delete_refresh_operations(
            database,
            "fifo-market",
            "fifo-financial",
            "fifo-industry",
        )
        database.close()


def test_operational_status_has_safe_head_latest_kinds_and_stable_fifty_row_pages(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    created_at = datetime(2026, 8, 30, 8, tzinfo=UTC)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        pointer = MountedDatasetHeadStore(tmp_path).current_pointer()
        assert pointer is not None
        target = current["research_calendar"][-1]
        with database.transaction() as transaction:
            transaction.execute("DELETE FROM data.refresh_operations")
            for index in range(53):
                key = f"status-{index:03d}"
                kind = ("market", "financial", "industry")[index % 3]
                status = "cancelled" if index == 52 else "accepted"
                transaction.execute(
                    """
                    INSERT INTO data.refresh_operations (
                        idempotency_key, kind, fingerprint, status,
                        as_of, observation_through_session, created_at,
                        finished_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        CASE WHEN %s = 'market' THEN %s ELSE NULL END,
                        CASE WHEN %s = 'market' THEN NULL ELSE %s::date END,
                        %s,
                        CASE WHEN %s = 'cancelled' THEN %s ELSE NULL END
                    )
                    """,
                    (
                        key,
                        kind,
                        f"{index:064x}",
                        status,
                        kind,
                        AS_OF,
                        kind,
                        target,
                        created_at,
                        status,
                        created_at,
                    ),
                )

        service = DatasetOperationalStatusService(
            database,
            _overview_service(database, tmp_path),
        )
        first = service.status(cursor=None)

        assert first.head.data_identity == pointer.data_identity
        assert first.head.data_through_session.isoformat() == target
        assert first.head.market_research_readiness is True
        assert [item.idempotency_key for item in first.latest_by_kind] == [
            "status-051",
            "status-052",
            "status-050",
        ]
        assert first.latest_by_kind[1].status == "cancelled"
        assert len(first.operations) == 50
        assert first.operations[0].idempotency_key == "status-052"
        assert first.operations[-1].idempotency_key == "status-003"
        assert first.next_cursor is not None
        serialized = first.model_dump_json()
        for forbidden in (
            "generation_manifest_sha256",
            "owner_token",
            "lease_expires_at",
            "fingerprint",
        ):
            assert forbidden not in serialized

        with database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO data.refresh_operations (
                    idempotency_key, kind, fingerprint, status, as_of, created_at
                ) VALUES (%s, 'market', %s, 'accepted', %s, %s)
                """,
                (
                    "status-newest",
                    "f" * 64,
                    AS_OF,
                    created_at + timedelta(seconds=1),
                ),
            )

        second = service.status(cursor=first.next_cursor)
        assert [item.idempotency_key for item in second.operations] == [
            "status-002",
            "status-001",
            "status-000",
        ]
        assert second.next_cursor is None
        assert "status-newest" not in {
            item.idempotency_key for item in second.operations
        }
        reloaded = service.status(cursor=None)
        assert reloaded.operations[0].idempotency_key == "status-newest"
        assert reloaded.latest_by_kind[0].idempotency_key == "status-newest"
    finally:
        with database.transaction() as transaction:
            transaction.execute(
                "DELETE FROM data.refresh_operations WHERE idempotency_key LIKE 'status-%'"
            )
        database.close()


def test_refresh_receipt_schema_rejects_market_degraded_outcome(
    core_settings: CoreSettings,
) -> None:
    database = _database(core_settings)
    try:
        with pytest.raises(CheckViolation):
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    INSERT INTO data.refresh_operations (
                        idempotency_key, kind, fingerprint, status, attempt_count,
                        outcome, as_of, generation_manifest_sha256,
                        data_through_session, last_refresh_at, finished_at
                    ) VALUES (
                        'invalid-market-degraded', 'market', %s, 'succeeded', 1,
                        'degraded', %s, %s, '2026-08-14', now(), now()
                    )
                    """,
                    ("a" * 64, AS_OF, "b" * 64),
                )
    finally:
        database.close()


@pytest.mark.parametrize(
    ("key", "outcome", "pending_count", "gap_count"),
    (
        ("invalid-financial-empty-degraded", "degraded", 0, 0),
        ("invalid-financial-published-pending", "published", 1, 0),
        ("invalid-financial-no-change-gap", "no_change", 0, 1),
    ),
)
def test_refresh_receipt_schema_binds_financial_outcomes_to_unresolved_counts(
    core_settings: CoreSettings,
    *,
    key: str,
    outcome: str,
    pending_count: int,
    gap_count: int,
) -> None:
    database = _database(core_settings)
    try:
        with pytest.raises(CheckViolation):
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    INSERT INTO data.refresh_operations (
                        idempotency_key, kind, fingerprint, status, attempt_count,
                        outcome, observation_through_session,
                        generation_manifest_sha256, data_through_session,
                        last_refresh_at, financial_complete_through_session,
                        matched_trigger_count, checked_no_structured_change_count,
                        accepted_instrument_count, failed_instrument_count,
                        pending_instrument_count, discovery_gap_count, finished_at
                    ) VALUES (
                        %s, 'financial', %s, 'succeeded', 1,
                        %s, '2026-08-14', %s, '2026-08-14', now(), '2026-08-14',
                        0, 0, 0, 0, %s, %s, now()
                    )
                    """,
                    (key, "c" * 64, outcome, "d" * 64, pending_count, gap_count),
                )
    finally:
        database.close()


def test_shared_worker_dispatches_financial_and_persists_a_safe_degraded_receipt(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        target = current["research_calendar"][-1]
        refresh = _refresh_service(database, tmp_path)
        refresh.submit_financial(
            idempotency_key="financial-degraded",
            observation_through_session=target,
        )
        received: dict[str, object] = {}

        class FakeFinancialService:
            def __init__(
                self,
                selected_database: object,
                mount_root: object,
                announcement_source: object,
                financial_source: object,
                **options: object,
            ) -> None:
                received.update(
                    database=selected_database,
                    mount_root=mount_root,
                    announcement_source=announcement_source,
                    financial_source=financial_source,
                    options=options,
                )

            def publish(self, **arguments: object) -> object:
                received.update(arguments)
                return SimpleNamespace(
                    status="succeeded_with_pending",
                    generation_manifest_sha256=manifest,
                    attempted_through_session=target,
                    complete_through_session=target,
                    matched_trigger_count=2,
                    checked_no_structured_change_count=1,
                    accepted_instrument_count=1,
                    failed_instrument_count=1,
                    pending_instrument_count=1,
                    discovery_gap_count=0,
                    canonical_changed=True,
                )

        announcement_source = object()
        financial_source = object()
        monkeypatch.setattr(
            refresh_module,
            "DailyFinancialRefreshService",
            FakeFinancialService,
        )

        assert (
            refresh.process_next(
                RecordingRefreshSource(current),
                benchmark_source=FixtureBenchmarkSource(),
                financial_announcement_source=announcement_source,
                financial_source=financial_source,
            )
            is True
        )

        receipt = refresh.inspect("financial-degraded")
        assert received["announcement_source"] is announcement_source
        assert received["financial_source"] is financial_source
        assert received["idempotency_key"] == "financial-degraded"
        assert received["observation_through_session"] == target
        assert receipt.status == "succeeded"
        assert receipt.outcome == "degraded"
        assert receipt.data_through_session == current["research_calendar"][-1]
        assert receipt.financial_complete_through_session == target
        assert receipt.matched_trigger_count == 2
        assert receipt.checked_no_structured_change_count == 1
        assert receipt.accepted_instrument_count == 1
        assert receipt.failed_instrument_count == 1
        assert receipt.pending_instrument_count == 1
        assert receipt.discovery_gap_count == 0
    finally:
        _delete_refresh_operations(database, "financial-degraded")
        database.close()


@pytest.mark.parametrize(
    ("canonical_changed", "expected_outcome"),
    ((True, "published"), (False, "no_change")),
)
def test_shared_worker_distinguishes_clean_financial_terminal_outcomes(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    canonical_changed: bool,
    expected_outcome: str,
) -> None:
    database = _database(core_settings)
    key = f"financial-{expected_outcome}"
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        target = current["research_calendar"][-1]
        refresh = _refresh_service(database, tmp_path)
        refresh.submit_financial(
            idempotency_key=key,
            observation_through_session=target,
        )

        class FakeFinancialService:
            def __init__(self, *arguments: object, **options: object) -> None:
                del arguments, options

            def publish(self, **arguments: object) -> object:
                del arguments
                return SimpleNamespace(
                    status="succeeded",
                    generation_manifest_sha256=manifest,
                    complete_through_session=target,
                    matched_trigger_count=0,
                    checked_no_structured_change_count=0,
                    accepted_instrument_count=0,
                    failed_instrument_count=0,
                    pending_instrument_count=0,
                    discovery_gap_count=0,
                    canonical_changed=canonical_changed,
                )

        monkeypatch.setattr(
            refresh_module,
            "DailyFinancialRefreshService",
            FakeFinancialService,
        )
        assert (
            refresh.process_next(
                RecordingRefreshSource(current),
                benchmark_source=FixtureBenchmarkSource(),
                financial_announcement_source=object(),
                financial_source=object(),
            )
            is True
        )

        receipt = refresh.inspect(key)
        assert receipt.status == "succeeded"
        assert receipt.outcome == expected_outcome
        assert receipt.pending_instrument_count == 0
        assert receipt.discovery_gap_count == 0
    finally:
        _delete_refresh_operations(database, key)
        database.close()


def test_financial_business_rejection_is_terminal_without_retry(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit_financial(
            idempotency_key="financial-business-rejected",
            observation_through_session=current["research_calendar"][-1],
        )

        class RejectingFinancialService:
            def __init__(self, *arguments: object, **options: object) -> None:
                del arguments, options

            def publish(self, **arguments: object) -> object:
                del arguments
                raise refresh_module.FinancialDailyRefreshError("FINANCIAL_TARGET_EXCEEDS_MARKET")

        monkeypatch.setattr(
            refresh_module,
            "DailyFinancialRefreshService",
            RejectingFinancialService,
        )
        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(
                RecordingRefreshSource(current),
                benchmark_source=FixtureBenchmarkSource(),
                financial_announcement_source=object(),
                financial_source=object(),
            )
        assert failure.value.code == "FINANCIAL_TARGET_EXCEEDS_MARKET"

        receipt = refresh.inspect("financial-business-rejected")
        assert receipt.status == "failed"
        assert receipt.outcome == "business_rejected"
        assert receipt.failure_code == "FINANCIAL_TARGET_EXCEEDS_MARKET"
        assert receipt.attempt_count == 1
    finally:
        _delete_refresh_operations(database, "financial-business-rejected")
        database.close()


@pytest.mark.parametrize(
    "failure_code",
    (
        "FINANCIAL_DAILY_REFRESH_WRITE_FAILED",
        "FINANCIAL_CANDIDATE_RECORD_CONFLICT",
        "FINANCIAL_REFRESH_CLOCK_INVALID",
        "FINANCIAL_DAILY_CANDIDATE_INVALID",
    ),
)
def test_nonretryable_financial_internal_failure_is_not_business_rejection(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_code: str,
) -> None:
    database = _database(core_settings)
    key = f"financial-internal-{failure_code.lower()}"
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit_financial(
            idempotency_key=key,
            observation_through_session=current["research_calendar"][-1],
        )

        class InternallyFailingFinancialService:
            def __init__(self, *arguments: object, **options: object) -> None:
                del arguments, options

            def publish(self, **arguments: object) -> object:
                del arguments
                raise refresh_module.FinancialDailyRefreshError(failure_code)

        monkeypatch.setattr(
            refresh_module,
            "DailyFinancialRefreshService",
            InternallyFailingFinancialService,
        )
        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(
                RecordingRefreshSource(current),
                benchmark_source=FixtureBenchmarkSource(),
                financial_announcement_source=object(),
                financial_source=object(),
            )
        assert failure.value.code == failure_code

        receipt = refresh.inspect(key)
        assert receipt.status == "failed"
        assert receipt.outcome == "infrastructure_failed"
        assert receipt.failure_code == failure_code
        assert receipt.last_failure_code == failure_code
        assert receipt.attempt_count == 1
    finally:
        _delete_refresh_operations(database, key)
        database.close()


def test_financial_infrastructure_failure_retries_then_exhausts(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path, max_attempts=2)
        refresh.submit_financial(
            idempotency_key="financial-infrastructure-failed",
            observation_through_session=current["research_calendar"][-1],
        )

        class FailingFinancialService:
            def __init__(self, *arguments: object, **options: object) -> None:
                del arguments, options

            def publish(self, **arguments: object) -> object:
                del arguments
                raise RuntimeError("private infrastructure detail")

        monkeypatch.setattr(
            refresh_module,
            "DailyFinancialRefreshService",
            FailingFinancialService,
        )
        for expected_status in ("accepted", "failed"):
            with pytest.raises(DataRefreshError) as failure:
                refresh.process_next(
                    RecordingRefreshSource(current),
                    benchmark_source=FixtureBenchmarkSource(),
                    financial_announcement_source=object(),
                    financial_source=object(),
                )
            assert failure.value.code == "REFRESH_INFRASTRUCTURE_FAILURE"
            assert refresh.inspect("financial-infrastructure-failed").status == expected_status

        receipt = refresh.inspect("financial-infrastructure-failed")
        assert receipt.outcome == "infrastructure_failed"
        assert receipt.failure_code == "RETRY_EXHAUSTED"
        assert receipt.last_failure_code == "REFRESH_INFRASTRUCTURE_FAILURE"
        assert receipt.attempt_count == 2
    finally:
        _delete_refresh_operations(database, "financial-infrastructure-failed")
        database.close()


@pytest.mark.parametrize(
    ("canonical_changed", "expected_outcome"),
    ((True, "published"), (False, "no_change")),
)
def test_shared_worker_dispatches_industry_and_distinguishes_terminal_outcomes(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    canonical_changed: bool,
    expected_outcome: str,
) -> None:
    database = _database(core_settings)
    key = f"industry-{expected_outcome}"
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        target = current["research_calendar"][-1]
        refresh = _refresh_service(database, tmp_path)
        refresh.submit_industry(
            idempotency_key=key,
            observation_through_session=target,
        )
        received: dict[str, object] = {}

        class FakeIndustryService:
            def __init__(
                self,
                selected_database: object,
                mount_root: object,
                industry_source: object,
                **options: object,
            ) -> None:
                received.update(
                    database=selected_database,
                    mount_root=mount_root,
                    industry_source=industry_source,
                    options=options,
                )

            def publish(self, **arguments: object) -> object:
                received.update(arguments)
                return SimpleNamespace(
                    generation_manifest_sha256=manifest,
                    canonical_changed=canonical_changed,
                )

        monkeypatch.setattr(
            refresh_module,
            "IndustryRefreshService",
            FakeIndustryService,
        )
        industry_source = object()
        selected_targets: list[str] = []
        assert (
            refresh.process_next(
                RecordingRefreshSource(current),
                benchmark_source=FixtureBenchmarkSource(),
                industry_source=industry_source,  # type: ignore[arg-type]
                industry_source_target_selector=selected_targets.append,
            )
            is True
        )

        receipt = refresh.inspect(key)
        assert received["industry_source"] is industry_source
        assert received["idempotency_key"] == key
        assert received["observation_through_session"] == target
        assert callable(received["options"]["ownership_guard"])  # type: ignore[index]
        assert callable(received["options"]["publication_guard"])  # type: ignore[index]
        assert selected_targets == [target]
        assert receipt.status == "succeeded"
        assert receipt.outcome == expected_outcome
        overview = _overview_service(database, tmp_path).overview()
        assert overview.last_industry_refresh_at is not None
    finally:
        _delete_refresh_operations(database, key)
        with database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.current_dataset_state
                SET last_industry_refresh_at = NULL
                WHERE singleton = 1
                """
            )
        database.close()


def test_industry_business_rejection_is_terminal_without_retry(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit_industry(
            idempotency_key="industry-business-rejected",
            observation_through_session=current["research_calendar"][-1],
        )

        class RejectingIndustryService:
            def __init__(self, *arguments: object, **options: object) -> None:
                del arguments, options

            def publish(self, **arguments: object) -> object:
                del arguments
                raise refresh_module.IndustryRefreshError(
                    "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION"
                )

        monkeypatch.setattr(
            refresh_module,
            "IndustryRefreshService",
            RejectingIndustryService,
        )
        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(
                RecordingRefreshSource(current),
                benchmark_source=FixtureBenchmarkSource(),
                industry_source=object(),  # type: ignore[arg-type]
            )
        assert failure.value.code == "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION"

        receipt = refresh.inspect("industry-business-rejected")
        assert receipt.status == "failed"
        assert receipt.outcome == "business_rejected"
        assert receipt.failure_code == "OVERLAPPING_PRIMARY_INDUSTRY_CLASSIFICATION"
        assert receipt.attempt_count == 1
    finally:
        _delete_refresh_operations(database, "industry-business-rejected")
        database.close()


def test_industry_infrastructure_failure_retries_then_exhausts(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path, max_attempts=2)
        refresh.submit_industry(
            idempotency_key="industry-infrastructure-failed",
            observation_through_session=current["research_calendar"][-1],
        )

        class FailingIndustryService:
            def __init__(self, *arguments: object, **options: object) -> None:
                del arguments, options

            def publish(self, **arguments: object) -> object:
                del arguments
                raise RuntimeError("private industry infrastructure detail")

        monkeypatch.setattr(
            refresh_module,
            "IndustryRefreshService",
            FailingIndustryService,
        )
        for expected_status in ("accepted", "failed"):
            with pytest.raises(DataRefreshError) as failure:
                refresh.process_next(
                    RecordingRefreshSource(current),
                    benchmark_source=FixtureBenchmarkSource(),
                    industry_source=object(),  # type: ignore[arg-type]
                )
            assert failure.value.code == "REFRESH_INFRASTRUCTURE_FAILURE"
            assert (
                refresh.inspect("industry-infrastructure-failed").status
                == expected_status
            )

        receipt = refresh.inspect("industry-infrastructure-failed")
        assert receipt.outcome == "infrastructure_failed"
        assert receipt.failure_code == "RETRY_EXHAUSTED"
        assert receipt.last_failure_code == "REFRESH_INFRASTRUCTURE_FAILURE"
        assert receipt.attempt_count == 2
    finally:
        _delete_refresh_operations(database, "industry-infrastructure-failed")
        database.close()


def test_worker_waits_for_a_nonexpired_running_refresh_before_claiming_fifo(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key="interrupted-running", as_of=AS_OF)
        refresh.submit(idempotency_key="queued-behind-running", as_of=AS_OF)
        with database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.refresh_operations
                SET status = 'running', owner_token = 'interrupted-worker',
                    lease_expires_at = now() + interval '1 minute',
                    attempt_count = 1, phase = 'claim',
                    last_heartbeat_at = now(), started_at = now(), updated_at = now()
                WHERE idempotency_key = 'interrupted-running'
                """
            )

        source = RecordingRefreshSource(current)
        assert _process_next(refresh, source) is False
        assert source.plans == []
        assert refresh.inspect("interrupted-running").status == "running"
        assert refresh.inspect("queued-behind-running").status == "accepted"
    finally:
        _delete_refresh_operations(
            database,
            "interrupted-running",
            "queued-behind-running",
        )
        database.close()


def test_operator_cancels_only_unclaimed_refresh_and_fifo_skips_it(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    keys = ("cancel-before-claim", "queued-after-cancel")
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key=keys[0], as_of=AS_OF)
        refresh.submit(idempotency_key=keys[1], as_of=AS_OF)

        cancelled = refresh.cancel(
            idempotency_key=keys[0],
            kind="market",
            target=AS_OF.isoformat(),
        )

        assert cancelled.status == "cancelled"
        assert cancelled.attempt_count == 0
        assert refresh.inspect(keys[0]) == cancelled
        with pytest.raises(DataRefreshError) as duplicate:
            refresh.cancel(
                idempotency_key=keys[0],
                kind="market",
                target=AS_OF.isoformat(),
            )
        assert duplicate.value.code == "REFRESH_NOT_CANCELLABLE"

        assert _process_next(refresh, RecordingRefreshSource(current)) is True
        assert refresh.inspect(keys[0]).status == "cancelled"
        assert refresh.inspect(keys[1]).status == "succeeded"
    finally:
        _delete_refresh_operations(database, *keys)
        database.close()


def test_cancel_and_worker_claim_race_has_exactly_one_winner(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    key = "cancel-claim-race"
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key=key, as_of=AS_OF)
        barrier = threading.Barrier(2)

        def run_worker() -> bool:
            barrier.wait()
            return _process_next(refresh, RecordingRefreshSource(current))

        def run_cancel() -> str:
            barrier.wait()
            try:
                return refresh.cancel(
                    idempotency_key=key,
                    kind="market",
                    target=AS_OF.isoformat(),
                ).status
            except DataRefreshError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            worker = executor.submit(run_worker)
            cancel = executor.submit(run_cancel)
            worker_result = worker.result(timeout=10)
            cancel_result = cancel.result(timeout=10)

        receipt = refresh.inspect(key)
        assert (worker_result, cancel_result, receipt.status) in {
            (False, "cancelled", "cancelled"),
            (True, "REFRESH_NOT_CANCELLABLE", "succeeded"),
        }
    finally:
        _delete_refresh_operations(database, key)
        database.close()


def test_retry_inserts_new_receipt_without_changing_source_and_preserves_fifo(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    keys = ("failed-source", "fifo-before-retry", "failed-source-retry")
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key=keys[0], as_of=AS_OF)
        with pytest.raises(DataRefreshError):
            _process_next(refresh, UnavailableRefreshSource())
        assert refresh.inspect(keys[0]).status == "failed"
        refresh.submit(idempotency_key=keys[1], as_of=AS_OF)
        with database.transaction() as transaction:
            source_before = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (keys[0],),
            ).fetchone()
        assert source_before is not None

        retried = refresh.retry(
            source_idempotency_key=keys[0],
            idempotency_key=keys[2],
            kind="market",
            target=AS_OF.isoformat(),
        )

        assert retried.idempotency_key == keys[2]
        assert retried.status == "accepted"
        assert retried.attempt_count == 0
        assert retried.as_of == AS_OF.isoformat()
        with database.transaction() as transaction:
            source_after = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (keys[0],),
            ).fetchone()
            retry_row = transaction.execute(
                "SELECT * FROM data.refresh_operations WHERE idempotency_key = %s",
                (keys[2],),
            ).fetchone()
        assert source_after == source_before
        assert retry_row is not None
        assert retry_row["fingerprint"] == source_before["fingerprint"]

        with pytest.raises(DataRefreshError) as duplicate:
            refresh.retry(
                source_idempotency_key=keys[0],
                idempotency_key=keys[2],
                kind="market",
                target=AS_OF.isoformat(),
            )
        assert duplicate.value.code == "IDEMPOTENCY_KEY_CONFLICT"

        assert _process_next(refresh, RecordingRefreshSource(current)) is True
        assert refresh.inspect(keys[1]).status == "succeeded"
        assert refresh.inspect(keys[2]).status == "accepted"
        assert refresh.inspect(keys[0]).status == "failed"
    finally:
        _delete_refresh_operations(database, *keys)
        database.close()


def test_cancelled_refresh_retries_as_a_distinct_accepted_receipt(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    keys = ("cancelled-retry-source", "cancelled-retry-new")
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key=keys[0], as_of=AS_OF)
        source = refresh.cancel(
            idempotency_key=keys[0],
            kind="market",
            target=AS_OF.isoformat(),
        )

        retried = refresh.retry(
            source_idempotency_key=keys[0],
            idempotency_key=keys[1],
            kind="market",
            target=AS_OF.isoformat(),
        )

        assert source.status == "cancelled"
        assert refresh.inspect(keys[0]) == source
        assert retried.idempotency_key == keys[1]
        assert retried.status == "accepted"
        assert retried.as_of == source.as_of
        assert retried.attempt_count == 0
    finally:
        _delete_refresh_operations(database, *keys)
        database.close()


def test_cancel_and_retry_reject_wrong_target_and_lifecycle_state(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    keys = ("action-source", "action-retry")
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key=keys[0], as_of=AS_OF)

        with pytest.raises(DataRefreshError) as wrong_target:
            refresh.cancel(
                idempotency_key=keys[0],
                kind="market",
                target=(AS_OF + timedelta(hours=1)).isoformat(),
            )
        assert wrong_target.value.code == "REFRESH_TARGET_CONFLICT"
        assert refresh.inspect(keys[0]).status == "accepted"

        with pytest.raises(DataRefreshError) as not_retryable:
            refresh.retry(
                source_idempotency_key=keys[0],
                idempotency_key=keys[1],
                kind="market",
                target=AS_OF.isoformat(),
            )
        assert not_retryable.value.code == "REFRESH_NOT_RETRYABLE"
        with pytest.raises(DataRefreshError) as missing:
            refresh.cancel(
                idempotency_key="missing-action-source",
                kind="market",
                target=AS_OF.isoformat(),
            )
        assert missing.value.code == "REFRESH_NOT_FOUND"
        with database.transaction() as transaction:
            retry_count = transaction.execute(
                "SELECT count(*) AS count FROM data.refresh_operations WHERE idempotency_key = %s",
                (keys[1],),
            ).fetchone()
        assert retry_count == {"count": 0}
    finally:
        _delete_refresh_operations(database, *keys)
        database.close()


def test_unavailable_refresh_retries_are_bounded_and_sanitized(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        lifecycle_events: list[dict[str, object]] = []
        refresh = _refresh_service(
            database,
            tmp_path,
            max_attempts=2,
            lifecycle_event=lifecycle_events.append,
        )
        refresh.submit(idempotency_key="bounded-retry", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as first:
            _process_next(refresh, UnavailableRefreshSource())
        assert first.value.code == "SOURCE_UNAVAILABLE"
        retrying = refresh.inspect("bounded-retry")
        assert retrying.status == "accepted"
        assert retrying.attempt_count == 1
        assert retrying.failure_code is None
        assert retrying.last_failure_code == "SOURCE_UNAVAILABLE"

        with pytest.raises(DataRefreshError) as second:
            _process_next(refresh, UnavailableRefreshSource())
        assert second.value.code == "SOURCE_UNAVAILABLE"
        terminal = refresh.inspect("bounded-retry")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.last_failure_code == "SOURCE_UNAVAILABLE"
        assert terminal.attempt_count == 2
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
        failures = [event for event in lifecycle_events if event["event"] == "data_refresh_failed"]
        assert [(event["level"], event["failure_code"], event["status"]) for event in failures] == [
            ("WARNING", "SOURCE_UNAVAILABLE", "accepted"),
            ("ERROR", "RETRY_EXHAUSTED", "failed"),
        ]
        assert all(event["phase"] == "market" for event in failures)
        assert not [
            event for event in lifecycle_events if event["event"] == "data_refresh_succeeded"
        ]
        assert "canary-secret" not in json.dumps(lifecycle_events)
        assert "/private/data-source" not in json.dumps(lifecycle_events)
    finally:
        database.close()


def test_late_worker_cannot_renew_or_complete_after_recovery_takes_over(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    old_benchmark_started = threading.Event()
    resume_old_worker = threading.Event()

    class PausedOldBenchmarkSource(FixtureBenchmarkSource):
        def collect_open_levels(
            self,
            *,
            start_session: str,
            end_session: str,
        ) -> tuple[BenchmarkLevel, ...]:
            old_benchmark_started.set()
            assert resume_old_worker.wait(timeout=10)
            return super().collect_open_levels(
                start_session=start_session,
                end_session=end_session,
            )

    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        stale_candidate = copy.deepcopy(current)
        _append_session(stale_candidate)
        old_worker = _refresh_service(
            database,
            tmp_path,
            lease_seconds=60,
            heartbeat_seconds=30,
            max_attempts=3,
        )
        replacement = _refresh_service(database, tmp_path, max_attempts=3)
        old_worker.submit(idempotency_key="lost-worker", as_of=AS_OF)

        with ThreadPoolExecutor(max_workers=1) as executor:
            old_future = executor.submit(
                old_worker.process_next,
                RecordingRefreshSource(stale_candidate),
                benchmark_source=PausedOldBenchmarkSource(),
            )
            assert old_benchmark_started.wait(timeout=10)
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.refresh_operations
                    SET lease_expires_at = now() - interval '1 second'
                    WHERE idempotency_key = 'lost-worker' AND status = 'running'
                    """
                )

            assert _process_next(replacement, RecordingRefreshSource(current)) is True
            recovered = replacement.inspect("lost-worker")
            assert recovered.status == "succeeded"
            assert recovered.outcome == "no_change"
            assert recovered.attempt_count == 2
            assert recovered.last_failure_code is None
            recovered_freshness = (
                _overview_service(database, tmp_path).overview().last_market_refresh_at
            )

            resume_old_worker.set()
            assert old_future.result(timeout=10) is True

        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert replacement.inspect("lost-worker") == recovered
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            recovered_freshness
        )
        snapshot = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read()
        assert snapshot is not None
        assert snapshot.coverage_end_session == current["research_calendar"][-1]
        with database.transaction() as transaction:
            candidates = transaction.execute(
                """
                SELECT count(*) AS count FROM data.generation_candidates
                WHERE status = 'live'
                """
            ).fetchone()
        assert candidates == {"count": 0}
    finally:
        resume_old_worker.set()
        database.close()


def test_benchmark_publication_rechecks_lease_after_waiting_for_lifecycle_lock(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    observer = PostgresDatabase(core_settings.database_url)
    observer.open()
    benchmark_collected = threading.Event()
    resume_benchmark = threading.Event()

    class PausedBenchmarkSource(FixtureBenchmarkSource):
        def collect_open_levels(
            self,
            *,
            start_session: str,
            end_session: str,
        ) -> tuple[BenchmarkLevel, ...]:
            levels = super().collect_open_levels(
                start_session=start_session,
                end_session=end_session,
            )
            benchmark_collected.set()
            assert resume_benchmark.wait(timeout=10)
            return levels

    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        snapshot_store = BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path))
        assert snapshot_store.read() is None
        refresh = _refresh_service(
            database,
            tmp_path,
            lease_seconds=1,
            heartbeat_seconds=0.8,
            max_attempts=1,
        )
        refresh.submit(idempotency_key="benchmark-lock-expiry", as_of=AS_OF)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                refresh.process_next,
                RecordingRefreshSource(candidate),
                benchmark_source=PausedBenchmarkSource(),
            )
            assert benchmark_collected.wait(timeout=10)
            with database.transaction() as blocker:
                blocker.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("thesistrace-mounted-data-lifecycle",),
                )
                resume_benchmark.set()
                _wait_for_advisory_waiters(observer, expected=1, timeout=5)
                _wait_for_refresh_lease_expiry(
                    observer,
                    "benchmark-lock-expiry",
                    timeout=5,
                )
            assert future.result(timeout=10) is True

        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert snapshot_store.read() is None
        expired = refresh.inspect("benchmark-lock-expiry")
        assert expired.status == "running"
        assert expired.attempt_count == 1

        replacement = _refresh_service(database, tmp_path, max_attempts=1)
        assert _process_next(replacement, RecordingRefreshSource(current)) is True
        recovered = replacement.inspect("benchmark-lock-expiry")
        assert recovered.status == "failed"
        assert recovered.failure_code == "RETRY_EXHAUSTED"
        assert recovered.last_failure_code == "WORKER_LEASE_EXPIRED"
    finally:
        resume_benchmark.set()
        observer.close()
        database.close()


def test_head_publication_rechecks_lease_after_waiting_for_lifecycle_lock(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    observer = PostgresDatabase(core_settings.database_url)
    observer.open()
    head_publication_started = threading.Event()
    resume_head_publication = threading.Event()
    original_compare_and_swap = DatasetLifecycle.compare_and_swap_refresh_head

    def pause_head_publication(
        lifecycle: DatasetLifecycle,
        **arguments: object,
    ) -> object:
        head_publication_started.set()
        assert resume_head_publication.wait(timeout=10)
        return original_compare_and_swap(lifecycle, **arguments)  # type: ignore[arg-type]

    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = _refresh_service(
            database,
            tmp_path,
            lease_seconds=1,
            heartbeat_seconds=0.8,
            max_attempts=1,
        )
        refresh.submit(idempotency_key="head-lock-expiry", as_of=AS_OF)

        with monkeypatch.context() as scoped_patch:
            scoped_patch.setattr(
                DatasetLifecycle,
                "compare_and_swap_refresh_head",
                pause_head_publication,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    refresh.process_next,
                    RecordingRefreshSource(candidate),
                    benchmark_source=FixtureBenchmarkSource(),
                )
                assert head_publication_started.wait(timeout=10)
                with database.transaction() as blocker:
                    blocker.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        ("thesistrace-mounted-data-lifecycle",),
                    )
                    resume_head_publication.set()
                    _wait_for_advisory_waiters(observer, expected=1, timeout=5)
                    _wait_for_refresh_lease_expiry(
                        observer,
                        "head-lock-expiry",
                        timeout=5,
                    )
                assert future.result(timeout=10) is True

        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        expired = refresh.inspect("head-lock-expiry")
        assert expired.status == "running"
        assert expired.attempt_count == 1

        replacement = _refresh_service(database, tmp_path, max_attempts=1)
        assert _process_next(replacement, RecordingRefreshSource(current)) is True
        recovered = replacement.inspect("head-lock-expiry")
        assert recovered.status == "failed"
        assert recovered.failure_code == "RETRY_EXHAUSTED"
        assert recovered.last_failure_code == "WORKER_LEASE_EXPIRED"
        with database.transaction() as transaction:
            live_candidates = transaction.execute(
                """
                SELECT count(*) AS count FROM data.generation_candidates
                WHERE status = 'live'
                """
            ).fetchone()
        assert live_candidates == {"count": 0}
    finally:
        resume_head_publication.set()
        observer.close()
        database.close()


def test_candidate_receipt_and_protection_commit_atomically(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = _refresh_service(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key="candidate-transaction", as_of=AS_OF)
        with database.transaction() as transaction:
            candidate_count_before = transaction.execute(
                "SELECT count(*) AS count FROM data.generation_candidates"
            ).fetchone()
            transaction.execute(
                """
                CREATE FUNCTION data.reject_refresh_candidate_insert() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE
                    receipt_candidate_is_visible boolean;
                BEGIN
                    SELECT
                        generation_manifest_sha256 IS NOT NULL
                        AND candidate_prepared_at IS NOT NULL
                    INTO receipt_candidate_is_visible
                    FROM data.refresh_operations
                    WHERE idempotency_key = 'candidate-transaction';
                    IF receipt_candidate_is_visible THEN
                        RAISE EXCEPTION 'injected candidate insert failure';
                    END IF;
                    RETURN NEW;
                END
                $$;
                CREATE TRIGGER reject_refresh_candidate_insert
                BEFORE INSERT ON data.generation_candidates
                FOR EACH ROW EXECUTE FUNCTION data.reject_refresh_candidate_insert();
                """
            )
        try:
            with pytest.raises(DataRefreshError) as failure:
                _process_next(refresh, RecordingRefreshSource(candidate))
            assert failure.value.code == "REFRESH_INFRASTRUCTURE_FAILURE"
        finally:
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    DROP TRIGGER reject_refresh_candidate_insert
                    ON data.generation_candidates;
                    DROP FUNCTION data.reject_refresh_candidate_insert();
                    """
                )

        terminal = refresh.inspect("candidate-transaction")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        with database.transaction() as transaction:
            receipt = transaction.execute(
                """
                    SELECT generation_manifest_sha256, candidate_prepared_at
                    FROM data.refresh_operations
                    WHERE idempotency_key = 'candidate-transaction'
                    """
            ).fetchone()
            candidates = transaction.execute(
                "SELECT count(*) AS count FROM data.generation_candidates"
            ).fetchone()
        assert receipt == {
            "candidate_prepared_at": None,
            "generation_manifest_sha256": None,
        }
        assert candidates == candidate_count_before
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
    finally:
        database.close()


def test_real_tushare_overlap_merge_failure_keeps_prior_head_and_freshness(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        snapshot = _tushare_snapshot(_tushare_sessions(20))
        _lineage, current = normalize_tushare_snapshot(snapshot)
        manifest = _establish_head(database, tmp_path, current)
        prior_canonical = open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        malformed = copy.deepcopy(snapshot)
        malformed["daily"] = {"not": "a source table"}
        refresh = _refresh_service(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key="failure-merge", as_of=CORRECTION_AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            _process_next(
                refresh,
                TushareDataSource(provider=ReplayRefreshProvider(malformed)),
            )

        assert failure.value.code == "SOURCE_INVALID_SOURCE_DATA"
        terminal = refresh.inspect("failure-merge")
        assert terminal.status == "failed"
        assert terminal.failure_code == "SOURCE_INVALID_SOURCE_DATA"
        assert terminal.last_failure_code == "SOURCE_INVALID_SOURCE_DATA"
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert (
            open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest)
            == prior_canonical
        )
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
    finally:
        database.close()


def test_real_tushare_derived_recomputation_failure_keeps_prior_head_and_freshness(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        snapshot = _tushare_snapshot(_tushare_sessions(20))
        _lineage, current = normalize_tushare_snapshot(snapshot)
        manifest = _establish_head(database, tmp_path, current)
        prior_canonical = open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        corrected = copy.deepcopy(snapshot)
        daily = corrected["daily"]
        assert isinstance(daily, list)
        daily[2]["amount"] = "1000.00001"
        refresh = _refresh_service(database, tmp_path, max_attempts=1)
        refresh.submit(
            idempotency_key="failure-derived-recomputation",
            as_of=CORRECTION_AS_OF,
        )

        with localcontext() as context:
            context.traps[Inexact] = True
            with pytest.raises(DataRefreshError) as failure:
                _process_next(
                    refresh,
                    TushareDataSource(provider=ReplayRefreshProvider(corrected)),
                )

        assert failure.value.code == "REFRESH_INFRASTRUCTURE_FAILURE"
        terminal = refresh.inspect("failure-derived-recomputation")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.last_failure_code == "REFRESH_INFRASTRUCTURE_FAILURE"
        assert terminal.attempt_count == 1
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert (
            open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest)
            == prior_canonical
        )
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
    finally:
        database.close()


def test_real_generation_write_failure_keeps_the_prior_head_readable(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    source_entered = threading.Event()
    release_source = threading.Event()
    blocked_candidate_object: Path | None = None

    class BlockingSource(RecordingRefreshSource):
        def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
            source_entered.set()
            assert release_source.wait(timeout=10)
            return super().collect(plan)

    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        preview_root = tmp_path.with_name(f"{tmp_path.name}-candidate-preview")
        MountedGenerationStore(preview_root).materialize(
            candidate,
            prepared_at=FIRST_PREPARED_AT,
            source_name="recording-refresh-source",
            source_lineage={"fixture": "refresh-v1"},
        )
        candidate_objects = sorted((preview_root / "objects" / "sha256").glob("*/*.parquet"))
        blocked_candidate_object = next(
            (
                tmp_path / path.relative_to(preview_root)
                for path in candidate_objects
                if not (tmp_path / path.relative_to(preview_root)).exists()
            ),
            None,
        )
        assert blocked_candidate_object is not None
        blocked_candidate_object.parent.mkdir(parents=True, exist_ok=True)
        blocked_candidate_object.write_bytes(b"candidate write fault barrier")
        refresh = _refresh_service(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key="failure-generation-write", as_of=AS_OF)
        assert open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest) == current

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                refresh.process_next,
                BlockingSource(candidate),
                benchmark_source=FixtureBenchmarkSource(),
            )
            assert source_entered.wait(timeout=10)
            assert (
                open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest) == current
            )
            release_source.set()
            with pytest.raises(DataRefreshError) as failure:
                future.result(timeout=10)
        assert failure.value.code == "REFRESH_INFRASTRUCTURE_FAILURE"
        assert open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest) == current

        terminal = refresh.inspect("failure-generation-write")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.last_failure_code == "REFRESH_INFRASTRUCTURE_FAILURE"
        assert terminal.attempt_count == 1
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest) == current
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
    finally:
        release_source.set()
        if blocked_candidate_object is not None and blocked_candidate_object.is_file():
            blocked_candidate_object.unlink()
        database.close()


def test_head_replacement_with_rolled_back_lifecycle_commit_is_reconciled(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original = _establish_head(database, tmp_path, current)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = _refresh_service(database, tmp_path)
        refresh.submit(idempotency_key="ambiguous-cas", as_of=AS_OF)
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION data.reject_candidate_release() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock(1147011);
                    RAISE EXCEPTION 'injected candidate release failure';
                END
                $$;
                CREATE TRIGGER reject_candidate_release
                BEFORE UPDATE OF status ON data.generation_candidates
                FOR EACH ROW
                WHEN (OLD.status = 'live' AND NEW.status = 'released')
                EXECUTE FUNCTION data.reject_candidate_release();
                """
            )
        original_mode = stat.S_IMODE(tmp_path.stat().st_mode)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                with database.transaction() as blocker:
                    blocker.execute("SELECT pg_advisory_xact_lock(1147011)")
                    future = executor.submit(
                        refresh.process_next,
                        RecordingRefreshSource(candidate),
                        benchmark_source=FixtureBenchmarkSource(),
                    )
                    _wait_for_physical_head_change(tmp_path, original, timeout=10)
                    tmp_path.chmod(0)
                with pytest.raises(DataRefreshError) as failure:
                    future.result(timeout=10)
            assert failure.value.code == "REFRESH_COMPLETION_PENDING"
        finally:
            tmp_path.chmod(original_mode)
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    DROP TRIGGER reject_candidate_release ON data.generation_candidates;
                    DROP FUNCTION data.reject_candidate_release();
                    """
                )

        moved = DatasetLifecycle(database, tmp_path).current_pointer()
        assert moved is not None
        assert moved.generation_manifest_sha256 != original
        pending = refresh.inspect("ambiguous-cas")
        assert pending.status == "running"
        assert pending.failure_code is None
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
        manifests_before = tuple((tmp_path / "manifests" / "sha256").glob("*/*.json"))

        recovery_events: list[dict[str, object]] = []
        reopened = _refresh_service(
            database,
            tmp_path,
            lifecycle_event=recovery_events.append,
        )
        assert _process_next(reopened, RecordingRefreshSource(candidate)) is True

        terminal = reopened.inspect("ambiguous-cas")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "published"
        assert terminal.attempt_count == 1
        assert terminal.last_failure_code is None
        assert tuple((tmp_path / "manifests" / "sha256").glob("*/*.json")) == manifests_before
        assert [event["event"] for event in recovery_events] == [
            "data_refresh_phase_completed",
            "data_refresh_succeeded",
        ]
        assert recovery_events[0]["phase"] == "publication"
        assert recovery_events[0]["outcome"] == "recovered"
        assert recovery_events[1]["outcome"] == "published"
        recovery_operation_ids = {event["operation_id"] for event in recovery_events}
        assert len(recovery_operation_ids) == 1
        assert str(next(iter(recovery_operation_ids))).startswith("refresh:")
    finally:
        database.close()


def test_post_cas_completion_failure_reconciles_without_rebuilding_generation(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original = _establish_head(database, tmp_path, current)
        prior_refresh_at = _overview_service(database, tmp_path).overview().last_market_refresh_at
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        lifecycle_events: list[dict[str, object]] = []
        refresh = _refresh_service(
            database,
            tmp_path,
            lifecycle_event=lifecycle_events.append,
        )
        refresh.submit(idempotency_key="completion-crash", as_of=AS_OF)
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION data.reject_refresh_completion() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected Refresh completion failure';
                END
                $$;
                CREATE TRIGGER reject_refresh_completion
                BEFORE UPDATE OF status ON data.refresh_operations
                FOR EACH ROW
                WHEN (
                    OLD.idempotency_key = 'completion-crash'
                    AND NEW.status = 'succeeded'
                )
                EXECUTE FUNCTION data.reject_refresh_completion();
                """
            )
        try:
            with pytest.raises(DataRefreshError) as failure:
                _process_next(refresh, RecordingRefreshSource(candidate))
            assert failure.value.code == "REFRESH_COMPLETION_PENDING"
        finally:
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    DROP TRIGGER reject_refresh_completion ON data.refresh_operations;
                    DROP FUNCTION data.reject_refresh_completion();
                    """
                )

        moved = DatasetLifecycle(database, tmp_path).current_pointer()
        assert moved is not None
        assert moved.generation_manifest_sha256 != original
        assert open_complete_refresh_basis(MountedGenerationStore(tmp_path), original) == current
        assert refresh.inspect("completion-crash").status == "running"
        failure_event = next(
            event for event in lifecycle_events if event["event"] == "data_refresh_failed"
        )
        assert failure_event["level"] == "ERROR"
        assert failure_event["phase"] == "publication"
        assert failure_event["failure_code"] == "REFRESH_COMPLETION_PENDING"
        assert not [
            event
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
            and event.get("phase") == "publication"
        ]
        assert not [
            event for event in lifecycle_events if event["event"] == "data_refresh_succeeded"
        ]
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
        manifests_before = tuple((tmp_path / "manifests" / "sha256").glob("*/*.json"))

        reopened = _refresh_service(database, tmp_path)
        assert _process_next(reopened, RecordingRefreshSource(candidate)) is True

        terminal = reopened.inspect("completion-crash")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "published"
        assert terminal.attempt_count == 1
        assert _overview_service(database, tmp_path).overview().last_market_refresh_at is not None
        assert tuple((tmp_path / "manifests" / "sha256").glob("*/*.json")) == manifests_before
    finally:
        database.close()


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "refresh-financial",
            "--idempotency-key",
            "financial-failure-boundary",
            "--observation-through-session",
            "2026-08-13",
        ],
    ],
    ids=("financial",),
)
def test_financial_submission_failure_uses_the_normal_cli_error_channel(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    environment = {
        key: value for key, value in os.environ.items() if key != "THESISTRACE_DATABASE_URL"
    }
    environment["THESISTRACE_DATA_MOUNT"] = os.fspath(tmp_path)
    environment["THESISTRACE_TUSHARE_TOKEN"] = "diagnostic-canary-secret"
    completed = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.data_operator", *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(completed.stderr) == {
        "status": "failed",
        "code": "OPERATOR_FAILURE",
    }
    assert "diagnostic-canary-secret" not in completed.stdout + completed.stderr


def _twenty_session_canonical() -> dict[str, object]:
    canonical = build_minimal_canonical_fixture()
    for _ in range(19):
        _append_session(canonical)
    return canonical


def _tushare_sessions(count: int) -> list[str]:
    sessions: list[str] = []
    cursor = date(2026, 7, 1)
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    return sessions


def _tushare_snapshot(sessions: list[str]) -> dict[str, object]:
    daily = [
        {
            "ts_code": "600000.SH",
            "trade_date": session,
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10.5",
            "pre_close": "10",
            "change": "0.5",
            "pct_chg": "5",
            "vol": "100",
            "amount": "1000",
        }
        for session in sessions
    ]
    return {
        "calendar_sse": [
            {"exchange": "SSE", "cal_date": session, "is_open": "1"} for session in sessions
        ],
        "calendar_szse": [
            {"exchange": "SZSE", "cal_date": session, "is_open": "1"} for session in sessions
        ],
        "stock_basic": [
            {
                "ts_code": "600000.SH",
                "exchange": "SSE",
                "market": "主板",
                "list_date": "20220101",
                "delist_date": "",
            }
        ],
        "daily": daily,
        "adjustments": [
            {"ts_code": "600000.SH", "trade_date": session, "adj_factor": "1"}
            for session in sessions
        ],
        "suspensions": [],
        "price_limits": [
            {
                "ts_code": "600000.SH",
                "trade_date": session,
                "up_limit": "11",
                "down_limit": "9",
            }
            for session in sessions
        ],
        "industry_membership": [
            {
                "ts_code": "600000.SH",
                "in_date": "20220101",
                "out_date": "",
                "l1_code": "801010",
                "l2_code": "801011",
                "l3_code": "850111",
            }
        ],
    }


def _wait_for_physical_head_change(
    mount_root: Path,
    original_manifest: str,
    *,
    timeout: float,
) -> None:
    heads = MountedDatasetHeadStore(mount_root)
    deadline = monotonic() + timeout
    poll = threading.Event()
    while monotonic() < deadline:
        pointer = heads.current_pointer()
        if pointer is not None and pointer.generation_manifest_sha256 != original_manifest:
            return
        poll.wait(timeout=0.01)
    raise AssertionError("Dataset Head did not move before the fault barrier timed out")


def _wait_for_advisory_waiters(
    database: PostgresDatabase,
    *,
    expected: int,
    timeout: float,
) -> None:
    deadline = monotonic() + timeout
    poll = threading.Event()
    last_waiting = -1
    while monotonic() < deadline:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS waiting
                FROM pg_stat_activity
                WHERE datname = current_database() AND wait_event = 'advisory'
                """
            ).fetchone()
        assert row is not None
        last_waiting = int(row["waiting"])
        if last_waiting >= expected:
            return
        poll.wait(timeout=0.01)
    raise AssertionError(f"expected {expected} advisory-lock waiters, observed {last_waiting}")


def _wait_for_refresh_lease_expiry(
    database: PostgresDatabase,
    idempotency_key: str,
    *,
    timeout: float,
) -> None:
    deadline = monotonic() + timeout
    poll = threading.Event()
    last_lease: object = None
    while monotonic() < deadline:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT lease_expires_at,
                       lease_expires_at <= clock_timestamp() AS expired
                FROM data.refresh_operations
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (idempotency_key,),
            ).fetchone()
        assert row is not None
        last_lease = row["lease_expires_at"]
        if row["expired"] is True:
            return
        poll.wait(timeout=0.01)
    raise AssertionError(
        f"refresh {idempotency_key!r} lease did not expire; last lease {last_lease!r}"
    )


def _establish_head(
    database: PostgresDatabase,
    mount_root: Path,
    canonical: dict[str, object],
) -> str:
    generation = MountedGenerationStore(mount_root).materialize(
        canonical,
        prepared_at=datetime(2026, 9, 6, 10, tzinfo=UTC),
        source_name="prepared-refresh-test",
        source_lineage={"fixture": "prepared"},
    )
    lifecycle = DatasetLifecycle(database, mount_root)
    operation_id = f"prepared-refresh-head:{mount_root.name}"
    lifecycle.protect_candidate(
        operation_id=operation_id,
        generation_manifest_sha256=generation.manifest_sha256,
        lease_seconds=60,
    )
    lifecycle.compare_and_swap_head(
        expected_generation_manifest_sha256=None,
        candidate_generation_manifest_sha256=generation.manifest_sha256,
        operation_id=operation_id,
    )
    return generation.manifest_sha256


def _database(settings: CoreSettings) -> PostgresDatabase:
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    return database


def _delete_refresh_operations(
    database: PostgresDatabase,
    *idempotency_keys: str,
) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            "DELETE FROM data.refresh_operations WHERE idempotency_key = ANY(%s)",
            (list(idempotency_keys),),
        )


def _operator_command(
    settings: CoreSettings,
    mount_root: Path,
    arguments: list[str],
) -> dict[str, object]:
    value, _events = _operator_command_with_events(settings, mount_root, arguments)
    return value


def _operator_command_with_events(
    settings: CoreSettings,
    mount_root: Path,
    arguments: list[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_DATA_MOUNT": os.fspath(mount_root),
        "THESISTRACE_BENCHMARK_MOUNT": os.fspath(
            mount_root.parent / f"{mount_root.name}-benchmark-data"
        ),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.data_operator", *arguments],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
        timeout=30,
    )
    stdout_lines = [line for line in completed.stdout.splitlines() if line]
    assert len(stdout_lines) == 1
    value = json.loads(stdout_lines[0])
    assert isinstance(value, dict)
    events = [json.loads(line) for line in completed.stderr.splitlines() if line]
    assert all({"timestamp", "level", "component", "event"} <= set(event) for event in events)
    return value, events
