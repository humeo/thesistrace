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

import pytest
from benchmark_support import FixtureBenchmarkSource, benchmark_mount_for_data_mount
from canonical_store import open_complete_refresh_basis

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
                raise RuntimeError(
                    "simulated telemetry loss with canary-secret at /private/source"
                )

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
        snapshot = BenchmarkSnapshotStore(
            benchmark_mount_for_data_mount(tmp_path)
        ).read()
        assert snapshot is not None
        assert snapshot.coverage_end_session == candidate["research_calendar"][-1]
        assert snapshot.published_at == "2026-09-07T09:45:00Z"
        assert benchmark_source.requests == [
            ("2010-01-04", candidate["research_calendar"][-1])
        ]
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
        snapshot = BenchmarkSnapshotStore(
            benchmark_mount_for_data_mount(tmp_path)
        ).publish(
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
            event
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
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
        snapshot = BenchmarkSnapshotStore(
            benchmark_mount_for_data_mount(tmp_path)
        ).read()
        assert snapshot is not None
        assert snapshot.coverage_end_session == current["research_calendar"][-1]
        assert benchmark_source.requests == [
            ("2010-01-04", current["research_calendar"][-1])
        ]
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
        assert (
            BenchmarkSnapshotStore(benchmark_mount_for_data_mount(tmp_path)).read()
            is None
        )
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
            snapshot = BenchmarkSnapshotStore(
                benchmark_mount_for_data_mount(tmp_path)
            ).read()
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
            clock=iter(
                (FIRST_PREPARED_AT, FIRST_BENCHMARK_PUBLISHED_AT)
            ).__next__,
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
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
                "version": 2,
                "request_start": current["research_calendar"][0],
                "request_end": "2026-08-03",
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
        assert (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
            is not None
        )
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
            assert _process_next(second, source) is False
            release.set()
            assert future.result(timeout=10) is True

        terminal = first.inspect("concurrent-workers")
        assert terminal.status == "succeeded"
        assert terminal.attempt_count == 1
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
                    attempt_count = 1, started_at = now(), updated_at = now()
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


def test_unavailable_refresh_retries_are_bounded_and_sanitized(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
        failures = [
            event for event in lifecycle_events if event["event"] == "data_refresh_failed"
        ]
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
        snapshot = BenchmarkSnapshotStore(
            benchmark_mount_for_data_mount(tmp_path)
        ).read()
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
        snapshot_store = BenchmarkSnapshotStore(
            benchmark_mount_for_data_mount(tmp_path)
        )
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
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
        prior_refresh_at = (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
        )
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
        assert (
            _overview_service(database, tmp_path).overview().last_market_refresh_at
            is not None
        )
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
def test_refresh_command_failure_before_operation_start_keeps_one_stdout_result(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "THESISTRACE_DATABASE_URL"
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
    assert json.loads(completed.stdout) == {
        "status": "failed",
        "code": "OPERATOR_FAILURE",
    }
    assert completed.stderr == ""
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
    raise AssertionError(
        f"expected {expected} advisory-lock waiters, observed {last_waiting}"
    )


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
    assert all(
        {"timestamp", "level", "component", "event"} <= set(event)
        for event in events
    )
    return value, events
