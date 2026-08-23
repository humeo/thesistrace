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
from canonical_store import open_complete_refresh_basis

import thesistrace.data.refresh as refresh_module
from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import _append_session
from thesistrace.adapters.tushare_data import TushareDataSource
from thesistrace.adapters.tushare_provider import normalize_tushare_snapshot
from thesistrace.data import (
    CanonicalSourceBatch,
    CollectionPlan,
    DataRefreshError,
    DataRefreshService,
    DatasetLifecycle,
    DatasetOverviewService,
    MountedGenerationStore,
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


def test_private_refresh_is_async_moves_head_and_records_successful_freshness(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        original_manifest = _establish_head(database, tmp_path, current)
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        source = RecordingRefreshSource(candidate)
        operator_times = iter((FIRST_PREPARED_AT, FIRST_REFRESH_AT))
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

        refresh = DataRefreshService(
            database,
            tmp_path,
            clock=lambda: next(operator_times),
            lifecycle_event=lossy_lifecycle,
        )

        accepted = _operator_command(
            core_settings,
            tmp_path,
            ["refresh", "--idempotency-key", "refresh-once", "--as-of", AS_OF.isoformat()],
        )

        assert accepted["status"] == "accepted"
        assert source.plans == []
        assert refresh.inspect("refresh-once").__dict__ == accepted
        assert refresh.process_next(source) is True

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
        assert len(source.plans) == 1
        plan = source.plans[0]
        assert plan.kind == "refresh"
        assert plan.overlap_start_session == current["research_calendar"][-20]
        assert plan.after_session == current["research_calendar"][-1]
        assert plan.completed_through_date.isoformat() == "2026-09-07"
        overview = DatasetOverviewService(database, tmp_path).overview()
        assert overview.last_market_refresh_at == FIRST_REFRESH_AT
        assert overview.data_through_session.isoformat() == candidate["research_calendar"][-1]
        assert [event["event"] for event in lifecycle_events] == [
            "data_refresh_started",
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
        timestamps = iter(float(value) for value in range(14))
        operator_times = iter((FIRST_PREPARED_AT, FIRST_REFRESH_AT))
        refresh = DataRefreshService(
            database,
            tmp_path,
            clock=lambda: next(operator_times),
            lifecycle_event=lifecycle_events.append,
            monotonic=lambda: next(timestamps),
        )
        refresh.submit(idempotency_key="timed-refresh", as_of=AS_OF)

        assert refresh.process_next(RecordingRefreshSource(candidate)) is True

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
            "candidate_validation",
            "publication",
        ]
        assert [event["duration_ms"] for event in phase_events] == [1000] * 6
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

        accepted = DataRefreshService(database, tmp_path).submit(
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
        refresh = DataRefreshService(database, tmp_path)
        refresh.submit(idempotency_key="single-candidate-validation", as_of=AS_OF)

        assert refresh.process_next(RecordingRefreshSource(candidate)) is True

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
        refresh = DataRefreshService(
            database,
            tmp_path,
            clock=lambda: SECOND_REFRESH_AT,
            lifecycle_event=lifecycle_events.append,
        )

        first = refresh.submit(idempotency_key="no-change", as_of=AS_OF)
        replay = refresh.submit(idempotency_key="no-change", as_of=AS_OF)
        assert replay == first
        assert refresh.process_next(source) is True

        terminal = refresh.inspect("no-change")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "no_change"
        assert terminal.last_refresh_at == SECOND_REFRESH_AT.isoformat()
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
            SECOND_REFRESH_AT
        )
        assert [
            event.get("phase")
            for event in lifecycle_events
            if event["event"] == "data_refresh_phase_completed"
        ] == ["current_head", "market", "validation"]
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
        refresh = DataRefreshService(database, tmp_path, clock=lambda: SECOND_REFRESH_AT)
        refresh.submit(idempotency_key="no-canonical-json", as_of=AS_OF)

        def reject_canonical_serialization(*_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("refresh processing must not serialize the Canonical dataset")

        monkeypatch.setattr(
            refresh_module,
            "canonical_json_bytes",
            reject_canonical_serialization,
        )

        assert refresh.process_next(RecordingRefreshSource(current)) is True
        assert refresh.inspect("no-canonical-json").outcome == "no_change"
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
        )
        invalid = copy.deepcopy(current)
        invalid["prices"] = []
        lifecycle_events: list[dict[str, object]] = []
        refresh = DataRefreshService(
            database,
            tmp_path,
            clock=lambda: FIRST_REFRESH_AT,
            lifecycle_event=lifecycle_events.append,
        )
        refresh.submit(idempotency_key="invalid-candidate", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(RecordingRefreshSource(invalid))

        assert failure.value.code == "INVALID_CANONICAL_DATA"
        terminal = refresh.inspect("invalid-candidate")
        assert terminal.status == "failed"
        assert terminal.failure_code == "INVALID_CANONICAL_DATA"
        assert terminal.last_refresh_at is None
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        overview = DatasetOverviewService(database, tmp_path).overview()
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
            ["work-refresh", "--replay", os.fspath(refresh_replay)],
        )

        assert processed == {"status": "processed"}
        assert [event["event"] for event in operator_events] == [
            "data_refresh_started",
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
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
        first = DataRefreshService(database, tmp_path, heartbeat_seconds=1)
        second = DataRefreshService(database, tmp_path, heartbeat_seconds=1)
        first.submit(idempotency_key="concurrent-workers", as_of=AS_OF)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(first.process_next, source)
            assert started.wait(timeout=10)
            assert second.process_next(source) is False
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


def test_refresh_submission_replay_and_conflicts_cannot_duplicate_work(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = DataRefreshService(database, tmp_path)

        accepted = refresh.submit(idempotency_key="submission-replay", as_of=AS_OF)
        assert refresh.submit(idempotency_key="submission-replay", as_of=AS_OF) == accepted
        with pytest.raises(DataRefreshError) as conflicting_reuse:
            refresh.submit(
                idempotency_key="submission-replay",
                as_of=AS_OF.replace(hour=10),
            )
        assert conflicting_reuse.value.code == "IDEMPOTENCY_KEY_CONFLICT"
        with pytest.raises(DataRefreshError) as second_operation:
            refresh.submit(idempotency_key="another-refresh", as_of=AS_OF)
        assert second_operation.value.code == "REFRESH_ALREADY_ACTIVE"

        assert refresh.process_next(RecordingRefreshSource(current)) is True
        assert refresh.inspect("submission-replay").status == "succeeded"
        with database.transaction() as transaction:
            count = transaction.execute(
                """
                SELECT count(*) AS count FROM data.refresh_operations
                WHERE idempotency_key IN ('submission-replay', 'another-refresh')
                """
            ).fetchone()
        assert count == {"count": 1}
    finally:
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
        )
        lifecycle_events: list[dict[str, object]] = []
        refresh = DataRefreshService(
            database,
            tmp_path,
            max_attempts=2,
            lifecycle_event=lifecycle_events.append,
        )
        refresh.submit(idempotency_key="bounded-retry", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as first:
            refresh.process_next(UnavailableRefreshSource())
        assert first.value.code == "SOURCE_UNAVAILABLE"
        retrying = refresh.inspect("bounded-retry")
        assert retrying.status == "accepted"
        assert retrying.attempt_count == 1
        assert retrying.failure_code is None
        assert retrying.last_failure_code == "SOURCE_UNAVAILABLE"

        with pytest.raises(DataRefreshError) as second:
            refresh.process_next(UnavailableRefreshSource())
        assert second.value.code == "SOURCE_UNAVAILABLE"
        terminal = refresh.inspect("bounded-retry")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.last_failure_code == "SOURCE_UNAVAILABLE"
        assert terminal.attempt_count == 2
        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
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
    old_worker_started = threading.Event()
    resume_old_worker = threading.Event()

    class PausedOldSource(RecordingRefreshSource):
        def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
            old_worker_started.set()
            assert resume_old_worker.wait(timeout=10)
            return super().collect(plan)

    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        stale_candidate = copy.deepcopy(current)
        _append_session(stale_candidate)
        old_worker = DataRefreshService(
            database,
            tmp_path,
            lease_seconds=60,
            heartbeat_seconds=30,
            max_attempts=3,
        )
        replacement = DataRefreshService(database, tmp_path, max_attempts=3)
        old_worker.submit(idempotency_key="lost-worker", as_of=AS_OF)

        with ThreadPoolExecutor(max_workers=1) as executor:
            old_future = executor.submit(
                old_worker.process_next,
                PausedOldSource(stale_candidate),
            )
            assert old_worker_started.wait(timeout=10)
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.refresh_operations
                    SET lease_expires_at = now() - interval '1 second'
                    WHERE idempotency_key = 'lost-worker' AND status = 'running'
                    """
                )

            assert replacement.process_next(RecordingRefreshSource(current)) is True
            recovered = replacement.inspect("lost-worker")
            assert recovered.status == "succeeded"
            assert recovered.outcome == "no_change"
            assert recovered.attempt_count == 2
            assert recovered.last_failure_code is None
            recovered_freshness = (
                DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
            )

            resume_old_worker.set()
            assert old_future.result(timeout=10) is True

        head = DatasetLifecycle(database, tmp_path).current_pointer()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert replacement.inspect("lost-worker") == recovered
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
            recovered_freshness
        )
    finally:
        resume_old_worker.set()
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
        )
        malformed = copy.deepcopy(snapshot)
        malformed["daily"] = {"not": "a source table"}
        refresh = DataRefreshService(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key="failure-merge", as_of=CORRECTION_AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(TushareDataSource(provider=ReplayRefreshProvider(malformed)))

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
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
        )
        corrected = copy.deepcopy(snapshot)
        daily = corrected["daily"]
        assert isinstance(daily, list)
        daily[2]["amount"] = "1000.00001"
        refresh = DataRefreshService(database, tmp_path, max_attempts=1)
        refresh.submit(
            idempotency_key="failure-derived-recomputation",
            as_of=CORRECTION_AS_OF,
        )

        with localcontext() as context:
            context.traps[Inexact] = True
            with pytest.raises(DataRefreshError) as failure:
                refresh.process_next(TushareDataSource(provider=ReplayRefreshProvider(corrected)))

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
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
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
        refresh = DataRefreshService(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key="failure-generation-write", as_of=AS_OF)
        assert open_complete_refresh_basis(MountedGenerationStore(tmp_path), manifest) == current

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(refresh.process_next, BlockingSource(candidate))
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
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
        )
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = DataRefreshService(database, tmp_path)
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
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
        manifests_before = tuple((tmp_path / "manifests" / "sha256").glob("*/*.json"))

        recovery_events: list[dict[str, object]] = []
        reopened = DataRefreshService(
            database,
            tmp_path,
            lifecycle_event=recovery_events.append,
        )
        assert reopened.process_next(RecordingRefreshSource(candidate)) is True

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
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
        )
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        lifecycle_events: list[dict[str, object]] = []
        refresh = DataRefreshService(
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
                refresh.process_next(RecordingRefreshSource(candidate))
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
        assert DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at == (
            prior_refresh_at
        )
        manifests_before = tuple((tmp_path / "manifests" / "sha256").glob("*/*.json"))

        reopened = DataRefreshService(database, tmp_path)
        assert reopened.process_next(RecordingRefreshSource(candidate)) is True

        terminal = reopened.inspect("completion-crash")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "published"
        assert terminal.attempt_count == 1
        assert (
            DatasetOverviewService(database, tmp_path).overview().last_market_refresh_at
            is not None
        )
        assert tuple((tmp_path / "manifests" / "sha256").glob("*/*.json")) == manifests_before
    finally:
        database.close()


@pytest.mark.parametrize(
    "arguments",
    [
        ["work-refresh"],
        [
            "refresh-financial",
            "--idempotency-key",
            "financial-failure-boundary",
            "--generation-manifest-sha256",
            "a" * 64,
            "--capability-report",
            "unused-capability-report.json",
            "--observation-through-session",
            "2026-08-13",
        ],
    ],
    ids=("market", "financial"),
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
