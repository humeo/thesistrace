from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from psycopg.errors import RaiseException

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import (
    BootstrapCollectionPlan,
    CanonicalSourceBatch,
    DataOperator,
    DataOperatorError,
    DatasetLifecycle,
    DataSourceError,
    MountedGenerationStore,
)
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.fixture import build_minimal_canonical_fixture

AS_OF = datetime(2026, 8, 3, 10, tzinfo=UTC)
PREPARED_AT = datetime(2026, 8, 9, 12, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 9, 12, 5, tzinfo=UTC)


class RecordingBootstrapSource:
    def __init__(self, *, failure: DataSourceError | None = None) -> None:
        self.failure = failure
        self.plans: list[BootstrapCollectionPlan] = []

    def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch:
        self.plans.append(plan)
        if self.failure is not None:
            raise self.failure
        canonical = build_minimal_canonical_fixture()
        return CanonicalSourceBatch(
            source_name="tushare-replay",
            collection_kind="bootstrap",
            source_lineage={"replay": "operator-integration-v1"},
            canonical=canonical,
            covered_session_range=("2026-08-07", "2026-08-07"),
        )


def test_private_operator_bootstraps_once_and_reopens_idempotently(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        source = RecordingBootstrapSource()
        times = iter((PREPARED_AT, COMPLETED_AT))
        operator = DataOperator(database, tmp_path, source, clock=times.__next__)

        first = operator.bootstrap(idempotency_key="bootstrap-once", as_of=AS_OF)
        repeated = operator.bootstrap(idempotency_key="bootstrap-once", as_of=AS_OF)

        assert repeated == first
        assert len(source.plans) == 1
        assert source.plans[0].start_date.isoformat() == "2025-08-03"
        assert source.plans[0].completed_through_date.isoformat() == "2026-08-03"
        assert first.prepared_at == COMPLETED_AT.isoformat()
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == first.generation_manifest_sha256
        assert head.generation.canonical == build_minimal_canonical_fixture()
        assert head.generation.preparation["prepared_at"] == PREPARED_AT.isoformat()

        with pytest.raises(DataOperatorError, match="HEAD_ALREADY_EXISTS"):
            operator.bootstrap(idempotency_key="cannot-overwrite", as_of=AS_OF)
        with pytest.raises(DataOperatorError, match="HEAD_ALREADY_EXISTS"):
            operator.bootstrap(idempotency_key="cannot-overwrite", as_of=AS_OF)
        assert len(source.plans) == 1
    finally:
        database.close()


def test_collection_failure_leaves_no_head_and_replays_sanitized_failure(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:
        source = RecordingBootstrapSource(
            failure=DataSourceError("unavailable", detail_code="SECRET_PROVIDER_DETAIL")
        )
        operator = DataOperator(database, tmp_path, source, clock=lambda: PREPARED_AT)
        for _ in range(2):
            with pytest.raises(DataOperatorError) as failure:
                operator.bootstrap(idempotency_key="source-failure", as_of=AS_OF)
            assert failure.value.code == "SOURCE_UNAVAILABLE"
        assert len(source.plans) == 1
        assert DatasetLifecycle(database, tmp_path).current_head() is None
        assert not (tmp_path / "HEAD.json").exists()
    finally:
        database.close()


def test_validation_failure_and_head_cas_loser_never_replace_the_winner(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    try:

        class InvalidSource(RecordingBootstrapSource):
            def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch:
                batch = super().collect_bootstrap(plan)
                batch.canonical["prices"] = []
                return batch

        invalid = InvalidSource()
        with pytest.raises(DataOperatorError) as failure:
            DataOperator(database, tmp_path, invalid, clock=lambda: PREPARED_AT).bootstrap(
                idempotency_key="invalid-canonical",
                as_of=AS_OF,
            )
        assert failure.value.code == "INVALID_CANONICAL_DATA"
        assert DatasetLifecycle(database, tmp_path).current_head() is None

        class WinnerPublishingSource(RecordingBootstrapSource):
            def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch:
                winner = MountedGenerationStore(tmp_path).materialize(
                    build_minimal_canonical_fixture(price_offset=9),
                    prepared_at=PREPARED_AT,
                    source_name="competing-operator",
                    source_lineage={"winner": True},
                )
                lifecycle = DatasetLifecycle(database, tmp_path)
                lifecycle.protect_candidate(
                    operation_id="competing-bootstrap",
                    generation_manifest_sha256=winner.manifest_sha256,
                    lease_seconds=60,
                )
                lifecycle.compare_and_swap_head(
                    expected_generation_manifest_sha256=None,
                    candidate_generation_manifest_sha256=winner.manifest_sha256,
                    operation_id="competing-bootstrap",
                )
                return super().collect_bootstrap(plan)

        losing_source = WinnerPublishingSource()
        with pytest.raises(DataOperatorError) as failure:
            DataOperator(database, tmp_path, losing_source, clock=lambda: PREPARED_AT).bootstrap(
                idempotency_key="cas-loser",
                as_of=AS_OF,
            )
        assert failure.value.code == "HEAD_ALREADY_EXISTS"
        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation.canonical == build_minimal_canonical_fixture(price_offset=9)
        with pytest.raises(DataOperatorError, match="HEAD_ALREADY_EXISTS"):
            DataOperator(database, tmp_path, losing_source, clock=lambda: PREPARED_AT).bootstrap(
                idempotency_key="cas-loser",
                as_of=AS_OF,
            )
        assert len(losing_source.plans) == 1
    finally:
        database.close()


def test_expired_bootstrap_attempt_is_fenced_and_taken_over_without_sleep(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    entered_source = threading.Event()
    release_source = threading.Event()

    class BlockingSource(RecordingBootstrapSource):
        def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch:
            entered_source.set()
            assert release_source.wait(timeout=10)
            return super().collect_bootstrap(plan)

    first = DataOperator(
        database,
        tmp_path,
        BlockingSource(),
        clock=lambda: PREPARED_AT,
        heartbeat_seconds=600,
    )
    winner_source = RecordingBootstrapSource()
    winner_times = iter((PREPARED_AT, COMPLETED_AT))
    winner = DataOperator(database, tmp_path, winner_source, clock=winner_times.__next__)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        stale = executor.submit(first.bootstrap, idempotency_key="take-over", as_of=AS_OF)
        assert entered_source.wait(timeout=10)
        with database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET lease_expires_at = now() - interval '1 second'
                WHERE idempotency_key = 'take-over'
                """
            )

        outcome = winner.bootstrap(idempotency_key="take-over", as_of=AS_OF)
        release_source.set()
        with pytest.raises(DataOperatorError) as stale_failure:
            stale.result(timeout=10)

        assert stale_failure.value.code == "BOOTSTRAP_INFRASTRUCTURE_FAILURE"
        assert DatasetLifecycle(database, tmp_path).current_head() is not None
        assert outcome.prepared_at == COMPLETED_AT.isoformat()
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status, generation_manifest_sha256
                FROM data.bootstrap_operations
                WHERE idempotency_key = 'take-over'
                """
            ).fetchone()
        assert row == {
            "status": "succeeded",
            "generation_manifest_sha256": outcome.generation_manifest_sha256,
        }
    finally:
        release_source.set()
        executor.shutdown(wait=True)
        database.close()


def test_active_bootstrap_heartbeat_prevents_lease_takeover(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    entered_source = threading.Event()
    release_source = threading.Event()

    class BlockingSource(RecordingBootstrapSource):
        def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch:
            entered_source.set()
            assert release_source.wait(timeout=10)
            return super().collect_bootstrap(plan)

    times = iter((PREPARED_AT, COMPLETED_AT))
    active = DataOperator(
        database,
        tmp_path,
        BlockingSource(),
        clock=times.__next__,
        lease_seconds=2,
        heartbeat_seconds=0.05,
    )
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(active.bootstrap, idempotency_key="heartbeat", as_of=AS_OF)
        assert entered_source.wait(timeout=10)
        with database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET lease_expires_at = now() - interval '1 second'
                WHERE idempotency_key = 'heartbeat'
                """
            )
        deadline = time.monotonic() + 5
        renewed = False
        while time.monotonic() < deadline:
            with database.transaction() as transaction:
                row = transaction.execute(
                    """
                    SELECT lease_expires_at > now() AS renewed
                    FROM data.bootstrap_operations
                    WHERE idempotency_key = 'heartbeat'
                    """
                ).fetchone()
            if row is not None and row["renewed"]:
                renewed = True
                break
        assert renewed
        with pytest.raises(DataOperatorError) as duplicate:
            DataOperator(database, tmp_path, RecordingBootstrapSource()).bootstrap(
                idempotency_key="heartbeat",
                as_of=AS_OF,
            )
        assert duplicate.value.code == "BOOTSTRAP_IN_PROGRESS"

        release_source.set()
        assert future.result(timeout=10).status == "succeeded"
    finally:
        release_source.set()
        executor.shutdown(wait=True)
        database.close()


def test_takeover_revokes_an_old_protected_candidate_before_head_cas(
    core_settings: CoreSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(core_settings)
    stale_at_cas = threading.Event()
    release_stale = threading.Event()
    call_lock = threading.Lock()
    first_call = True
    original_cas = DatasetLifecycle.compare_and_swap_head

    def barrier_cas(self: DatasetLifecycle, **kwargs: object):
        nonlocal first_call
        with call_lock:
            should_pause = first_call
            first_call = False
        if should_pause:
            stale_at_cas.set()
            assert release_stale.wait(timeout=10)
        return original_cas(self, **kwargs)

    monkeypatch.setattr(DatasetLifecycle, "compare_and_swap_head", barrier_cas)
    stale_times = iter((PREPARED_AT, COMPLETED_AT))
    stale_operator = DataOperator(
        database,
        tmp_path,
        RecordingBootstrapSource(),
        clock=stale_times.__next__,
        heartbeat_seconds=600,
    )
    winner_times = iter((PREPARED_AT, COMPLETED_AT))
    winner_operator = DataOperator(
        database,
        tmp_path,
        RecordingBootstrapSource(),
        clock=winner_times.__next__,
    )
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        stale = executor.submit(
            stale_operator.bootstrap,
            idempotency_key="protected-takeover",
            as_of=AS_OF,
        )
        assert stale_at_cas.wait(timeout=10)
        with database.transaction() as transaction:
            live_before = transaction.execute(
                "SELECT count(*) AS count FROM data.generation_candidates WHERE status = 'live'"
            ).fetchone()
            transaction.execute(
                """
                UPDATE data.bootstrap_operations
                SET lease_expires_at = now() - interval '1 second'
                WHERE idempotency_key = 'protected-takeover'
                """
            )
        assert live_before == {"count": 1}

        winner = winner_operator.bootstrap(
            idempotency_key="protected-takeover",
            as_of=AS_OF,
        )
        release_stale.set()
        with pytest.raises(DataOperatorError) as stale_failure:
            stale.result(timeout=10)
        assert stale_failure.value.code == "BOOTSTRAP_INFRASTRUCTURE_FAILURE"

        head = DatasetLifecycle(database, tmp_path).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == winner.generation_manifest_sha256
        with database.transaction() as transaction:
            state = transaction.execute(
                """
                SELECT operation.status,
                       (SELECT count(*) FROM data.generation_candidates
                        WHERE status = 'live') AS live_candidates
                FROM data.bootstrap_operations AS operation
                WHERE idempotency_key = 'protected-takeover'
                """
            ).fetchone()
        assert state == {"status": "succeeded", "live_candidates": 0}
    finally:
        release_stale.set()
        executor.shutdown(wait=True)
        database.close()


def test_expired_bootstrap_reconciles_a_committed_head_after_process_loss(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    fault_installed = False
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION data.reject_bootstrap_completion()
                RETURNS trigger LANGUAGE plpgsql AS $function$
                BEGIN
                    IF NEW.status = 'succeeded' THEN
                        RAISE EXCEPTION 'simulated process loss after Head commit';
                    END IF;
                    RETURN NEW;
                END
                $function$;
                CREATE TRIGGER reject_bootstrap_completion
                BEFORE UPDATE ON data.bootstrap_operations
                FOR EACH ROW EXECUTE FUNCTION data.reject_bootstrap_completion();
                """
            )
        fault_installed = True

        source = RecordingBootstrapSource()
        times = iter((PREPARED_AT, COMPLETED_AT))
        with pytest.raises(RaiseException, match="simulated process loss"):
            DataOperator(database, tmp_path, source, clock=times.__next__).bootstrap(
                idempotency_key="head-committed",
                as_of=AS_OF,
            )
        committed = DatasetLifecycle(database, tmp_path).current_head()
        assert committed is not None
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_bootstrap_completion ON data.bootstrap_operations;
                DROP FUNCTION data.reject_bootstrap_completion();
                """
            )
        fault_installed = False

        reopened_source = RecordingBootstrapSource()
        recovered = DataOperator(database, tmp_path, reopened_source).bootstrap(
            idempotency_key="head-committed",
            as_of=AS_OF,
        )

        assert recovered.generation_manifest_sha256 == committed.generation_manifest_sha256
        assert recovered.prepared_at == COMPLETED_AT.isoformat()
        assert reopened_source.plans == []
    finally:
        if fault_installed:
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    DROP TRIGGER IF EXISTS reject_bootstrap_completion
                    ON data.bootstrap_operations;
                    DROP FUNCTION IF EXISTS data.reject_bootstrap_completion();
                    """
                )
        database.close()


def test_real_private_command_bootstraps_from_tushare_replay(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    database = _database(core_settings)
    database.close()
    replay = tmp_path / "bootstrap-replay.json"
    mount = tmp_path / "mounted-data"
    mount.mkdir()
    replay.write_text(json.dumps(_replay_payload()))
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": core_settings.database_url,
        "THESISTRACE_DATA_MOUNT": str(mount),
    }
    command = (
        sys.executable,
        "-m",
        "thesistrace.entrypoints.data_operator",
        "bootstrap",
        "--idempotency-key",
        "cli-replay",
        "--as-of",
        "2026-08-03T18:00:00+08:00",
        "--replay",
        str(replay),
    )

    first = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    second = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == json.loads(first.stdout)
    outcome = json.loads(first.stdout)
    assert outcome["status"] == "succeeded"
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        head = DatasetLifecycle(database, mount).current_head()
        assert head is not None
        assert head.generation_manifest_sha256 == outcome["generation_manifest_sha256"]
        assert head.data_through_session == "2026-08-03"
        assert set(json.loads((mount / "HEAD.json").read_text())) == {
            "format",
            "version",
            "generation_manifest_sha256",
            "data_identity",
            "dataset_coverage",
            "data_through_session",
            "prepared_at",
        }
    finally:
        database.close()

    malformed = tmp_path / "malformed-replay.json"
    malformed.write_text('{"secret":"must-not-leak"}')
    failed = subprocess.run(
        (*command[:-1], str(malformed)),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert failed.returncode == 2
    assert json.loads(failed.stderr) == {"status": "failed", "code": "OPERATOR_FAILURE"}
    assert "must-not-leak" not in failed.stderr

    database_failure_environment = {
        **environment,
        "THESISTRACE_DATABASE_URL": (
            "postgresql://operator:SUPERSECRET@127.0.0.1:1/unreachable"
        ),
    }
    database_failed = subprocess.run(
        command,
        env=database_failure_environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert database_failed.returncode == 2
    assert json.loads(database_failed.stderr) == {
        "status": "failed",
        "code": "OPERATOR_FAILURE",
    }
    assert "SUPERSECRET" not in database_failed.stderr


def _database(settings: CoreSettings) -> PostgresDatabase:
    migrate_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    with database.transaction() as transaction:
        transaction.execute(
            "TRUNCATE data.bootstrap_operations, data.generation_pins, data.generation_candidates"
        )
    return database


def _replay_payload() -> dict[str, object]:
    session = "20260803"
    daily = {
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
    anchor = {**daily, "trade_date": "20220103"}
    snapshot = {
        "calendar_sse": [{"exchange": "SSE", "cal_date": session, "is_open": "1"}],
        "calendar_szse": [{"exchange": "SZSE", "cal_date": session, "is_open": "1"}],
        "stock_basic": [
            {
                "ts_code": "600000.SH",
                "exchange": "SSE",
                "market": "主板",
                "list_date": "20220103",
                "delist_date": "",
            }
        ],
        "anchor_daily": [anchor],
        "anchor_adjustments": [
            {"ts_code": "600000.SH", "trade_date": "20220103", "adj_factor": "1"}
        ],
        "daily": [daily],
        "adjustments": [{"ts_code": "600000.SH", "trade_date": session, "adj_factor": "1"}],
        "suspensions": [],
        "price_limits": [
            {
                "ts_code": "600000.SH",
                "trade_date": session,
                "up_limit": "11",
                "down_limit": "9",
            }
        ],
        "industry_membership": [
            {
                "ts_code": "600000.SH",
                "in_date": "20220103",
                "out_date": "",
                "l1_code": "801010",
                "l2_code": "801011",
                "l3_code": "850111",
            }
        ],
    }
    return {
        "format": "thesistrace-tushare-bootstrap-replay",
        "version": 1,
        "request_start": "2025-08-03",
        "request_end": "2026-08-03",
        "snapshot": snapshot,
    }
