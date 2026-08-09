from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import _append_session
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
from thesistrace.data.source import DataSourceError
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture

AS_OF = datetime(2026, 9, 7, 9, tzinfo=UTC)
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
        raise DataSourceError("unavailable", detail_code="UPSTREAM_UNAVAILABLE")


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
        refresh = DataRefreshService(
            database,
            tmp_path,
            clock=lambda: next(operator_times),
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
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 != original_manifest
        assert head.generation.canonical == candidate
        assert head.prepared_at == FIRST_PREPARED_AT.isoformat()
        assert len(source.plans) == 1
        plan = source.plans[0]
        assert plan.kind == "refresh"
        assert plan.overlap_start_session == current["research_calendar"][-20]
        assert plan.after_session == current["research_calendar"][-1]
        assert plan.completed_through_date.isoformat() == "2026-09-07"
        overview = DatasetOverviewService(database, tmp_path).overview()
        assert overview.last_refresh_at == FIRST_REFRESH_AT
        assert overview.data_through_session.isoformat() == candidate["research_calendar"][-1]
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
        refresh = DataRefreshService(
            database,
            tmp_path,
            clock=lambda: SECOND_REFRESH_AT,
        )

        first = refresh.submit(idempotency_key="no-change", as_of=AS_OF)
        replay = refresh.submit(idempotency_key="no-change", as_of=AS_OF)
        assert replay == first
        assert refresh.process_next(source) is True

        terminal = refresh.inspect("no-change")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "no_change"
        assert terminal.last_refresh_at == SECOND_REFRESH_AT.isoformat()
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert DatasetOverviewService(database, tmp_path).overview().last_refresh_at == (
            SECOND_REFRESH_AT
        )
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
        prior_refresh_at = DatasetOverviewService(database, tmp_path).overview().last_refresh_at
        invalid = copy.deepcopy(current)
        invalid["prices"] = []
        refresh = DataRefreshService(database, tmp_path, clock=lambda: FIRST_REFRESH_AT)
        refresh.submit(idempotency_key="invalid-candidate", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(RecordingRefreshSource(invalid))

        assert failure.value.code == "INVALID_CANONICAL_DATA"
        terminal = refresh.inspect("invalid-candidate")
        assert terminal.status == "failed"
        assert terminal.failure_code == "INVALID_CANONICAL_DATA"
        assert terminal.last_refresh_at is None
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        overview = DatasetOverviewService(database, tmp_path).overview()
        assert overview.last_refresh_at == prior_refresh_at
    finally:
        database.close()


def test_refresh_worker_command_processes_a_deterministic_replay(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        fixture_path = (
            Path(__file__).resolve().parents[1] / "fixtures" / "tushare-bootstrap-replay-v1.json"
        )
        replay = json.loads(fixture_path.read_text())
        _source, current = normalize_tushare_snapshot(replay["snapshot"])
        manifest = _establish_head(database, tmp_path, current)
        replay.update(
            {
                "format": "thesistrace-tushare-refresh-replay",
                "request_start": current["research_calendar"][0],
                "request_end": "2026-08-03",
                "known_ts_codes": ["600000.SH"],
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

        processed = _operator_command(
            core_settings,
            tmp_path,
            ["work-refresh", "--replay", os.fspath(refresh_replay)],
        )

        assert processed == {"status": "processed"}
        terminal = _operator_command(
            core_settings,
            tmp_path,
            ["inspect-refresh", "--idempotency-key", "worker-replay"],
        )
        assert terminal["status"] == "succeeded"
        assert terminal["outcome"] == "no_change"
        assert terminal["last_refresh_at"] is not None
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert DatasetOverviewService(database, tmp_path).overview().last_refresh_at is not None
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
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 != original
        assert head.generation.canonical == candidate
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
        prior_refresh_at = DatasetOverviewService(database, tmp_path).overview().last_refresh_at
        refresh = DataRefreshService(database, tmp_path, max_attempts=2)
        refresh.submit(idempotency_key="bounded-retry", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as first:
            refresh.process_next(UnavailableRefreshSource())
        assert first.value.code == "SOURCE_UNAVAILABLE"
        retrying = refresh.inspect("bounded-retry")
        assert retrying.status == "accepted"
        assert retrying.attempt_count == 1
        assert retrying.failure_code is None

        with pytest.raises(DataRefreshError) as second:
            refresh.process_next(UnavailableRefreshSource())
        assert second.value.code == "SOURCE_UNAVAILABLE"
        terminal = refresh.inspect("bounded-retry")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.attempt_count == 2
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert DatasetOverviewService(database, tmp_path).overview().last_refresh_at == (
            prior_refresh_at
        )
    finally:
        database.close()


def test_expired_worker_is_fenced_and_recovered_from_a_new_attempt(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        _establish_head(database, tmp_path, current)
        refresh = DataRefreshService(database, tmp_path, max_attempts=3)
        refresh.submit(idempotency_key="lost-worker", as_of=AS_OF)
        with database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.refresh_operations
                SET status = 'running', owner_token = 'lost-owner',
                    lease_expires_at = now() - interval '1 second',
                    attempt_count = 1, started_at = now()
                WHERE idempotency_key = 'lost-worker'
                """
            )

        assert refresh.process_next(RecordingRefreshSource(current)) is True

        terminal = refresh.inspect("lost-worker")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "no_change"
        assert terminal.attempt_count == 2
        with database.transaction() as transaction:
            stale_write = transaction.execute(
                """
                UPDATE data.refresh_operations SET failure_code = 'STALE_WRITE'
                WHERE idempotency_key = 'lost-worker'
                  AND status = 'running' AND owner_token = 'lost-owner'
                """
            )
        assert stale_write.rowcount == 0
        assert refresh.inspect("lost-worker") == terminal
    finally:
        database.close()


@pytest.mark.parametrize("failure_stage", ("generation_write", "head_cas"))
def test_precommit_infrastructure_failure_keeps_the_prior_head_readable(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    database = _database(core_settings)
    try:
        current = _twenty_session_canonical()
        manifest = _establish_head(database, tmp_path, current)
        prior_refresh_at = DatasetOverviewService(database, tmp_path).overview().last_refresh_at
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        if failure_stage == "generation_write":
            monkeypatch.setattr(
                MountedGenerationStore,
                "materialize",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected write")),
            )
        else:
            monkeypatch.setattr(
                DatasetLifecycle,
                "compare_and_swap_head",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected cas")),
            )
        refresh = DataRefreshService(database, tmp_path, max_attempts=1)
        refresh.submit(idempotency_key=f"failure-{failure_stage}", as_of=AS_OF)

        with pytest.raises(DataRefreshError) as failure:
            refresh.process_next(RecordingRefreshSource(candidate))

        assert failure.value.code == "REFRESH_INFRASTRUCTURE_FAILURE"
        terminal = refresh.inspect(f"failure-{failure_stage}")
        assert terminal.status == "failed"
        assert terminal.failure_code == "RETRY_EXHAUSTED"
        assert terminal.attempt_count == 1
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == manifest
        assert MountedGenerationStore(tmp_path).open_generation(manifest).canonical == current
        assert DatasetOverviewService(database, tmp_path).overview().last_refresh_at == (
            prior_refresh_at
        )
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
        prior_refresh_at = DatasetOverviewService(database, tmp_path).overview().last_refresh_at
        candidate = copy.deepcopy(current)
        _append_session(candidate)
        refresh = DataRefreshService(database, tmp_path)
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

        moved = DatasetLifecycle(database, tmp_path).current_head()
        assert moved is not None
        assert moved.generation_manifest_sha256 != original
        assert MountedGenerationStore(tmp_path).open_generation(original).canonical == current
        assert refresh.inspect("completion-crash").status == "running"
        assert DatasetOverviewService(database, tmp_path).overview().last_refresh_at == (
            prior_refresh_at
        )
        manifests_before = tuple((tmp_path / "manifests" / "sha256").glob("*/*.json"))

        reopened = DataRefreshService(database, tmp_path)
        assert reopened.process_next(RecordingRefreshSource(candidate)) is True

        terminal = reopened.inspect("completion-crash")
        assert terminal.status == "succeeded"
        assert terminal.outcome == "published"
        assert terminal.attempt_count == 1
        assert DatasetOverviewService(database, tmp_path).overview().last_refresh_at is not None
        assert tuple((tmp_path / "manifests" / "sha256").glob("*/*.json")) == manifests_before
    finally:
        database.close()


def _twenty_session_canonical() -> dict[str, object]:
    canonical = build_minimal_canonical_fixture()
    for _ in range(19):
        _append_session(canonical)
    return canonical


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
    migrate_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    return database


def _operator_command(
    settings: CoreSettings,
    mount_root: Path,
    arguments: list[str],
) -> dict[str, object]:
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
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value
