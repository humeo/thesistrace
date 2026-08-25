from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from canonical_store import align_canonical_market_data, open_complete_refresh_basis
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from psycopg import Connection, connect
from psycopg.conninfo import make_conninfo

import thesistrace.research_run.service as research_run_service
from thesistrace._postgres import PostgresDatabase
from thesistrace.data import (
    DatasetLifecycle,
    MountedGenerationStore,
)
from thesistrace.data.canonical_mapping import field_catalog
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.publication import Publication, PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import RunInput, StrategyRunInput, run
from thesistrace.research_kernel.factor import prepare_columnar_forward_labels
from thesistrace.research_kernel.numeric import NUMERIC_CONTRACT_ID
from thesistrace.research_kernel.research_chunks import (
    AlphaFactorExecutionBinding,
    empty_research_continuation,
    execute_research_chunk,
)
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.execution import SupervisedResearchExecutor
from thesistrace.research_run.result import build_result_payload, read_result_bundle

SESSIONS = ("2026-08-03", "2026-08-04", "2026-08-05")


def _weekday_sessions(start: date, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(sessions)


LONG_SESSIONS = _weekday_sessions(date(2025, 1, 2), 140)
ADVISORY_KEY = 150015


class _InspectablePostgresDatabase(PostgresDatabase):
    def failed_request_count(self) -> int:
        return int(self._pool.get_stats().get("requests_errors", 0))


@dataclass
class _BlockedWorker:
    settings: CoreSettings
    run_id: str
    process: subprocess.Popen[str]
    advisory_owner: Connection[object]
    application_name: str
    barrier_released: bool = False
    stopped: bool = False
    stdout: str = ""
    stderr: str = ""

    def wait_until_blocked(self) -> None:
        poll = Event()
        for _ in range(500):
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                raise AssertionError(
                    "Worker exited before reaching the PostgreSQL barrier; "
                    f"exit={self.process.returncode}; stdout={stdout!r}; "
                    f"stderr={stderr!r}; attempts={_attempts(self.settings, self.run_id)!r}"
                )
            if self._matching_locks():
                return
            poll.wait(0.02)
        self.terminate()
        raise AssertionError(
            "Worker did not reach the PostgreSQL barrier; "
            f"exit={self.process.returncode}; stdout={self.stdout!r}; "
            f"stderr={self.stderr!r}; attempts={_attempts(self.settings, self.run_id)!r}; "
            f"locks={self._matching_locks()!r}"
        )

    def backend_pid(self) -> int:
        rows = self._matching_locks()
        if len(rows) != 1:
            raise AssertionError(f"expected one blocked Worker backend, got {rows!r}")
        return int(rows[0]["pid"])

    def stop(self) -> None:
        os.kill(self.process.pid, signal.SIGSTOP)
        self.stopped = True

    def resume(self) -> None:
        if self.stopped and self.process.poll() is None:
            os.kill(self.process.pid, signal.SIGCONT)
        self.stopped = False

    def terminate(self) -> None:
        self.resume()
        if self.process.poll() is None:
            self.process.terminate()
        self.stdout, self.stderr = self.process.communicate(timeout=10)

    def release_barrier(self) -> None:
        if self.barrier_released:
            return
        self.advisory_owner.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_KEY,)).fetchone()
        self.advisory_owner.close()
        _drop_worker_block(self.settings)
        self.barrier_released = True

    def close(self) -> None:
        self.terminate()
        self.release_barrier()

    def _matching_locks(self) -> list[dict[str, object]]:
        database = PostgresDatabase(self.settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                rows = transaction.execute(
                    """
                    SELECT lock.pid, lock.granted, activity.state,
                           activity.wait_event_type, activity.wait_event
                    FROM pg_locks AS lock
                    JOIN pg_stat_activity AS activity ON activity.pid = lock.pid
                    WHERE lock.locktype = 'advisory'
                      AND lock.database = (
                          SELECT oid FROM pg_database
                          WHERE datname = current_database()
                      )
                      AND lock.classid = 0
                      AND lock.objid = %s
                      AND lock.objsubid = 1
                      AND NOT lock.granted
                      AND activity.application_name = %s
                    ORDER BY lock.pid
                    """,
                    (ADVISORY_KEY, self.application_name),
                ).fetchall()
            return rows
        finally:
            database.close()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "research_kind",
    ("strategy_backtest", "factor_evaluation"),
    ids=("strategy-backtest", "factor-evaluation"),
)
def test_worker_loss_retry_resumes_committed_chunks_on_the_frozen_generation(
    tmp_path: Path,
    research_kind: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0, sessions=LONG_SESSIONS)

    with TestClient(create_app(settings)) as first_process:
        run_id = _admit_run(
            first_process,
            request_id=f"retry-current-head-{research_kind}",
            sessions=LONG_SESSIONS,
            research_kind=research_kind,
        )
        frozen_plan = _stored_run(settings, run_id)["immutable_input"]["execution_plan"]
        with _blocked_worker(settings, run_id, after_checkpoint_count=2) as blocked:
            blocked.wait_until_blocked()
            assert _checkpoint_ordinals(settings, run_id) == [1, 2]
            committed = first_process.get(f"/api/research-runs/{run_id}").json()
            assert committed["progress"]["committed_chunk_count"] == 2
            assert committed["progress"]["completed_research_sessions"] == 128
            assert committed["progress"]["phase"] == "research"
            if research_kind == "factor_evaluation":
                _assert_factor_checkpoint_evidence(
                    first_process.app.state.core_runtime,
                    settings,
                    run_id,
                    expected_generation_id=head_a,
                )
            blocked.terminate()
            assert blocked.process.returncode != 0, blocked.stdout + blocked.stderr
        assert _attempts(settings, run_id) == [
            {
                "ordinal": 1,
                "status": "running",
                "failure_reason": None,
                "data_generation_id": head_a,
            }
        ]
        _expire_live_attempt(settings, run_id)
        _publish_head(
            settings,
            price_offset=7,
            sessions=LONG_SESSIONS,
            expected_manifest=head_a,
        )

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        recovery_events = _worker_events(completed)
        worker_loss_events = [
            event
            for event in recovery_events
            if event["event"]
            in {"research_attempt_failed", "research_retry_scheduled"}
        ]
        assert [event["event"] for event in worker_loss_events] == [
            "research_attempt_failed",
            "research_retry_scheduled",
        ]
        assert all(event["level"] == "WARNING" for event in worker_loss_events)
        assert all(event["failure_code"] == "WORKER_LOST" for event in worker_loss_events)
        assert all(event["run_id"] == run_id for event in worker_loss_events)
        assert worker_loss_events[0]["attempt_id"] == worker_loss_events[1]["attempt_id"]
        detail = restarted_process.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        assert "attempt" not in str(detail).lower()
        assert "generation" not in str(detail).lower()

        attempts = _attempts(settings, run_id)
        assert attempts == [
            {
                "ordinal": 1,
                "status": "failed",
                "failure_reason": "WorkerLost",
                "data_generation_id": head_a,
            },
            {
                "ordinal": 2,
                "status": "succeeded",
                "failure_reason": None,
                "data_generation_id": head_a,
            },
        ]
        stored = _stored_run(settings, run_id)
        assert stored["immutable_input"]["execution_plan"] == frozen_plan
        assert stored["result_provenance"]["data_generation_id"] == head_a
        assert stored["result_provenance"]["data_through_session"] == LONG_SESSIONS[-1]
        expected_result_names = (
            {"factor_summary"}
            if research_kind == "factor_evaluation"
            else {
                "factor_summary",
                "strategy_summary",
                "strategy_daily_observations",
                "terminal_strategy_state",
            }
        )
        assert set(_read_result(runtime, stored)) == expected_result_names
        expected = _reference_result(
            settings,
            head_a,
            sessions=LONG_SESSIONS,
            research_kind=research_kind,
        )
        assert canonical_json_bytes(_read_result(runtime, stored)) == canonical_json_bytes(expected)
        assert len(_attempts(settings, run_id)) == 2
        assert _checkpoint_ordinals(settings, run_id) == []


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "research_kind",
    ("strategy_backtest", "factor_evaluation"),
    ids=("strategy-backtest", "factor-evaluation"),
)
def test_publication_retry_reuses_the_validated_final_checkpoint(
    tmp_path: Path,
    research_kind: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, price_offset=0, sessions=LONG_SESSIONS)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(
            client,
            request_id=f"retry-final-publication-{research_kind}",
            sessions=LONG_SESSIONS,
            research_kind=research_kind,
        )
        _install_transient_result_publication_failure(settings)
        first_attempt_events: list[dict[str, object]] = []
        try:
            assert (
                runtime.research_runs.process_next(
                    on_execution_event=first_attempt_events.append
                )
                is True
            )
        finally:
            _remove_transient_result_publication_failure(settings)

        retry_wait = client.get(f"/api/research-runs/{run_id}").json()
        assert retry_wait["status"] == "running"
        checkpoint_ordinals = _checkpoint_ordinals(settings, run_id)
        plan = _stored_run(settings, run_id)["immutable_input"]["execution_plan"]
        assert checkpoint_ordinals == list(range(1, len(plan["chunks"]) + 1))
        assert _attempts(settings, run_id)[0]["failure_reason"] == ("InfrastructureUnavailable")
        retry_events = [
            event
            for event in first_attempt_events
            if event["event"] in {"research_attempt_failed", "research_retry_scheduled"}
        ]
        assert [event["event"] for event in retry_events] == [
            "research_attempt_failed",
            "research_retry_scheduled",
        ]
        assert all(event["level"] == "WARNING" for event in retry_events)
        assert all(event["run_id"] == run_id for event in retry_events)
        assert all(
            event["failure_code"] == "INFRASTRUCTURE_UNAVAILABLE"
            for event in retry_events
        )
        assert not {
            "research_result_published",
            "research_run_succeeded",
        } & {event["event"] for event in first_attempt_events}

        events: list[dict[str, object]] = []
        assert runtime.research_runs.process_next(on_execution_event=events.append) is True
        started = next(
            event
            for event in events
            if event["event"] == "research_execution_child_started"
        )
        assert started["resource_type"] == "ResearchRun"
        assert started["resource_id"] == run_id
        assert started["attempt_id"].startswith("attempt_")
        assert started["research_kind"] == research_kind
        assert started["resumed_from_checkpoint"] is True
        assert started["resumed_from_chunk_ordinal"] == len(plan["chunks"])
        assert [
            event["reused_checkpoint"]
            for event in events
            if event["event"] == "research_execution_chunk_received"
        ] == [True]
        completed = client.get(f"/api/research-runs/{run_id}").json()
        assert completed["status"] == "succeeded"
        assert [row["status"] for row in _attempts(settings, run_id)] == [
            "failed",
            "succeeded",
        ]
        _set_attempt_timing(settings, run_id)
        completed = client.get(f"/api/research-runs/{run_id}").json()
        assert completed["execution_timing"] == {
            "started_at": "2026-08-13T10:00:00Z",
            "finished_at": "2026-08-13T10:08:00Z",
            "elapsed_seconds": 480.0,
            "is_final": True,
        }
        assert _checkpoint_ordinals(settings, run_id) == []
        stored = _stored_run(settings, run_id)
        assert stored["result_provenance"]["data_generation_id"] == head
        assert canonical_json_bytes(_read_result(runtime, stored)) == canonical_json_bytes(
            _reference_result(
                settings,
                head,
                sessions=LONG_SESSIONS,
                research_kind=research_kind,
            )
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_corrupt_checkpoint_payload_is_a_terminal_integrity_failure(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0, sessions=LONG_SESSIONS)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(
            client,
            request_id="retry-corrupt-checkpoint",
            sessions=LONG_SESSIONS,
        )
        with _blocked_worker(settings, run_id, after_checkpoint_count=2) as blocked:
            blocked.wait_until_blocked()
            blocked.terminate()
            assert blocked.process.returncode != 0, blocked.stdout + blocked.stderr
        _expire_live_attempt(settings, run_id)
        with _corrupt_first_checkpoint_payload(settings, run_id):
            retry = _run_worker_once(settings)
            assert retry.returncode == 0, retry.stdout + retry.stderr
            failed = client.get(f"/api/research-runs/{run_id}").json()
            assert failed["status"] == "failed"
            assert failed["failure_reason"] == (
                "Research execution checkpoint integrity validation failed."
            )
            assert [row["failure_reason"] for row in _attempts(settings, run_id)] == [
                "WorkerLost",
                "CheckpointIntegrityFailure",
            ]
            assert _checkpoint_ordinals(settings, run_id) == []
            assert _research_result_manifest_count(settings) == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_retry_rejects_checkpoint_after_runtime_semantics_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0, sessions=LONG_SESSIONS)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(
            client,
            request_id="retry-obsolete-runtime-contract",
            sessions=LONG_SESSIONS,
        )
        with _blocked_worker(settings, run_id, after_checkpoint_count=2) as blocked:
            blocked.wait_until_blocked()
            blocked.terminate()
            assert blocked.process.returncode != 0, blocked.stdout + blocked.stderr
        _expire_live_attempt(settings, run_id)
        monkeypatch.setattr(
            research_run_service,
            "SEMANTIC_VERSIONS",
            {"factor": "factor-v2", "strategy": "strategy-v1", "kernel": "kernel-v4"},
        )

        assert runtime.research_runs.process_next() is True
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == (
            "Research execution contract does not match this runtime."
        )
        assert [row["failure_reason"] for row in _attempts(settings, run_id)] == [
            "WorkerLost",
            "ContractMismatch",
        ]
        assert _checkpoint_ordinals(settings, run_id) == []


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "research_kind",
    ("strategy_backtest", "factor_evaluation"),
    ids=("strategy-backtest", "factor-evaluation"),
)
def test_real_pool_timeout_retries_without_replacing_the_run(
    tmp_path: Path,
    research_kind: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(
            client,
            request_id=f"retry-pool-timeout-{research_kind}",
            research_kind=research_kind,
        )
        constrained = _InspectablePostgresDatabase(
            settings.database_url,
            pool_max_size=1,
            pool_timeout_seconds=0.1,
        )
        constrained.open()
        holder: Thread | None = None
        holder_errors: list[BaseException] = []

        def reserve_pool_after_claim(_run_id: str, _attempt_id: str) -> None:
            nonlocal holder
            reserved = Event()

            def hold_until_timeout() -> None:
                try:
                    poll = Event()
                    with constrained.transaction():
                        failed_requests = constrained.failed_request_count()
                        reserved.set()
                        for _ in range(500):
                            if constrained.failed_request_count() > failed_requests:
                                return
                            poll.wait(0.01)
                        raise AssertionError("PostgreSQL pool request did not time out")
                except BaseException as error:
                    holder_errors.append(error)
                    reserved.set()

            holder = Thread(target=hold_until_timeout, daemon=True)
            holder.start()
            assert reserved.wait(timeout=5)

        processor = ResearchRunService(
            constrained,
            dataset_lifecycle=DatasetLifecycle(constrained, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
        )
        try:
            assert processor.process_next(on_claim=reserve_pool_after_claim) is True
            assert holder is not None
            holder.join(timeout=5)
            assert not holder.is_alive()
            assert holder_errors == []
        finally:
            constrained.close()

        retry_wait = client.get(f"/api/research-runs/{run_id}").json()
        assert retry_wait["status"] == "running"
        assert _attempts(settings, run_id)[0]["failure_reason"] == ("InfrastructureUnavailable")
        assert runtime.research_runs.process_next() is True
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == ("succeeded")
        attempts = _attempts(settings, run_id)
        assert [row["status"] for row in attempts] == ["failed", "succeeded"]
        assert {row["data_generation_id"] for row in attempts} == {head}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "research_kind",
    ("strategy_backtest", "factor_evaluation"),
    ids=("strategy-backtest", "factor-evaluation"),
)
def test_real_publication_unavailability_retries_without_replacing_the_run(
    tmp_path: Path,
    research_kind: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(
            client,
            request_id=f"retry-publication-unavailable-{research_kind}",
            research_kind=research_kind,
        )
        unavailable_s3 = boto3.client(
            "s3",
            endpoint_url="http://127.0.0.1:1",
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                connect_timeout=0.1,
                read_timeout=0.1,
                retries={"max_attempts": 0},
            ),
        )
        unavailable_processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=Publication(
                runtime.database,
                unavailable_s3,
                bucket=settings.s3_bucket,
            ),
            execution=SupervisedResearchExecutor(settings.data_mount),
        )
        assert unavailable_processor.process_next() is True

        retry_wait = client.get(f"/api/research-runs/{run_id}").json()
        assert retry_wait["status"] == "running"
        assert _attempts(settings, run_id)[0]["failure_reason"] == ("InfrastructureUnavailable")
        assert runtime.research_runs.process_next() is True
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == ("succeeded")
        attempts = _attempts(settings, run_id)
        assert [row["status"] for row in attempts] == ["failed", "succeeded"]
        assert {row["data_generation_id"] for row in attempts} == {head}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_real_child_execution_memory_breach_is_terminal_capacity_failure(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="real-child-memory-breach")
        processor = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(
                settings.data_mount,
                execution_memory_bytes=1,
            ),
        )
        events: list[dict[str, object]] = []
        assert processor.process_next(on_execution_event=events.append) is True

        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == ("Research execution exceeded its resource limit.")
        assert [row["failure_reason"] for row in _attempts(settings, run_id)] == [
            "ResourceExhausted"
        ]
        assert _checkpoint_ordinals(settings, run_id) == []
        assert [event["event"] for event in events] == [
            "research_attempt_started",
            "research_run_state_changed",
            "research_execution_child_started",
            "research_execution_child_exited",
            "research_attempt_failed",
            "research_run_failed",
        ]
        terminal = events[-1]
        assert terminal["level"] == "ERROR"
        assert terminal["run_id"] == run_id
        assert terminal["failure_code"] == "RESOURCE_EXHAUSTED"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "research_kind",
    ("strategy_backtest", "factor_evaluation"),
    ids=("strategy-backtest", "factor-evaluation"),
)
def test_recovered_winner_fences_a_stale_prepared_attempt(
    tmp_path: Path,
    research_kind: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head_a = _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(
            client,
            request_id=f"retry-stale-fence-{research_kind}",
            research_kind=research_kind,
        )
        with _blocked_worker(settings, run_id) as stale:
            stale.wait_until_blocked()
            backend_pid = stale.backend_pid()
            stale.stop()
            _terminate_backend(settings, backend_pid)
            stale.release_barrier()
            _expire_live_attempt(settings, run_id)
            _publish_head(settings, price_offset=9, expected_manifest=head_a)

            completed_worker = _run_worker_once(settings)
            assert completed_worker.returncode == 0, (
                completed_worker.stdout + completed_worker.stderr
            )
            winning = client.get(f"/api/research-runs/{run_id}").json()
            assert winning["status"] == "succeeded"
            stale.resume()
            stale.stdout, stale.stderr = stale.process.communicate(timeout=10)
            assert stale.process.returncode == 0, stale.stdout + stale.stderr

        assert client.get(f"/api/research-runs/{run_id}").json() == winning
        assert [row["status"] for row in _attempts(settings, run_id)] == [
            "failed",
            "succeeded",
        ]
        stored = _stored_run(settings, run_id)
        assert stored["result_provenance"]["data_generation_id"] == head_a
        assert _research_result_manifest_count(settings) == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_worker_loss_retry_exhaustion_is_bounded_and_restart_stable(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="retry-exhaustion")
        for ordinal in range(1, 4):
            with _blocked_worker(settings, run_id) as blocked:
                blocked.wait_until_blocked()
                blocked.terminate()
                assert blocked.process.returncode != 0, blocked.stdout + blocked.stderr
            assert len(_attempts(settings, run_id)) == ordinal
            _expire_live_attempt(settings, run_id)

        exhausted = _run_worker_once(settings)
        assert exhausted.returncode == 0, exhausted.stdout + exhausted.stderr
        terminal_events = [
            event
            for event in _worker_events(exhausted)
            if event["event"] in {"research_attempt_failed", "research_run_failed"}
        ]
        assert [event["event"] for event in terminal_events] == [
            "research_attempt_failed",
            "research_run_failed",
        ]
        assert all(event["level"] == "ERROR" for event in terminal_events)
        assert all(event["failure_code"] == "WORKER_LOST" for event in terminal_events)
        assert all(event["run_id"] == run_id for event in terminal_events)
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == (
            "Research execution could not complete after automatic retries."
        )
        assert "WorkerLost" not in str(failed)
        assert [row["status"] for row in _attempts(settings, run_id)] == [
            "failed",
            "failed",
            "failed",
        ]

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{run_id}").json() == failed
        idle = _run_worker_once(settings)
        assert idle.returncode == 0, idle.stdout + idle.stderr
        assert len(_attempts(settings, run_id)) == 3


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_resource_exhaustion_is_bounded_sanitized_and_restart_stable(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        run_id = _admit_run(client, request_id="resource-exhaustion")
        _install_resource_exhaustion(settings)
        try:
            first = _run_worker_once(settings)
            assert first.returncode == 0, first.stdout + first.stderr
        finally:
            _remove_resource_exhaustion(settings)
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == ("Research execution exceeded its resource limit.")
        assert "secret-resource-pressure-detail" not in str(failed)
        assert [row["failure_reason"] for row in _attempts(settings, run_id)] == [
            "ResourceExhausted"
        ]
        assert _research_result_manifest_count(settings) == 0

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{run_id}").json() == failed
        assert len(_attempts(settings, run_id)) == 1


def _admit_run(
    client: TestClient,
    *,
    request_id: str,
    sessions: tuple[str, ...] = SESSIONS,
    research_kind: str = "strategy_backtest",
) -> str:
    response = client.post(
        "/api/research-runs",
        json=_run_command(
            request_id,
            sessions=sessions,
            research_kind=research_kind,
        ),
    )
    assert response.status_code == 202
    return str(response.json()["id"])


def _run_command(
    request_id: str,
    *,
    sessions: tuple[str, ...] = SESSIONS,
    research_kind: str = "strategy_backtest",
) -> dict[str, object]:
    command: dict[str, object] = {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "Same research question on current data",
        "start_date": sessions[0],
        "end_date": sessions[-1],
        "formula": "close",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": research_kind,
    }
    if research_kind == "strategy_backtest":
        command.update(
            {
                "holdings_count": 1,
                "rebalance_every_sessions": 1,
            }
        )
    return command


def _publish_head(
    settings: CoreSettings,
    *,
    price_offset: int,
    sessions: tuple[str, ...] = SESSIONS,
    expected_manifest: str | None = None,
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        _canonical(price_offset=price_offset, sessions=sessions),
        prepared_at=datetime(2026, 8, 10, 0, price_offset, tzinfo=UTC),
        source_name="retry-current-head-test",
        source_lineage={"price_offset": price_offset},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        operation_id = f"retry-current-head-{price_offset}"
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _canonical(
    *,
    price_offset: int,
    sessions: tuple[str, ...] = SESSIONS,
) -> dict[str, object]:
    template = build_minimal_canonical_fixture(price_offset=price_offset)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "field_catalog": [
            next(
                row
                for row in field_catalog(sessions[0])
                if row["field_id"] == "price.close.adjusted"
            )
        ],
        "research_calendar": list(sessions),
        "prices": [{**template["prices"][0], "session": session} for session in sessions],
        "trading_states": [
            {**template["trading_states"][0], "session": session} for session in sessions
        ],
        "price_limits": [
            {**template["price_limits"][0], "session": session} for session in sessions
        ],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _reference_result(
    settings: CoreSettings,
    generation_id: str,
    *,
    sessions: tuple[str, ...] = SESSIONS,
    research_kind: str = "strategy_backtest",
) -> dict[str, object]:
    store = MountedGenerationStore(settings.data_mount)
    canonical = open_complete_refresh_basis(store, generation_id)
    research_data = align_canonical_market_data(
        canonical,
        field_bindings={"price.close.adjusted": "close"},
        universe="top300",
        neutralization="none",
    )
    run_input = RunInput(
        research_data=research_data,
        alpha_expression={"kind": "field", "field_id": "price.close.adjusted"},
        field_bindings={"price.close.adjusted": "close"},
        effective_alpha_lookback=0,
        universe="top300",
        neutralization="none",
        research_kind=research_kind,
        strategy=(
            StrategyRunInput(
                holdings_count=1,
                rebalance_interval=1,
                initial_cash_cny="10000000",
                commission_rate_all_in="0.0003",
                commission_min_cny="5",
                stamp_duty_sell_rate="0.0005",
                transfer_fee_rate="0.00001",
            )
            if research_kind == "strategy_backtest"
            else None
        ),
        research_start_session=sessions[0],
        research_end_session=sessions[-1],
    )
    if research_kind == "factor_evaluation":
        columnar = store.read_columnar_slice(
            generation_id,
            sessions=list(sessions),
            universe_name="top300",
            neutralization="none",
            field_bindings={"price.close.adjusted": "close"},
            fact_instrument_ids=frozenset(),
        )
        columnar_input = run_input.with_research_data(columnar)
        calculation = execute_research_chunk(
            run_input=columnar_input,
            binding=AlphaFactorExecutionBinding.from_run_input(
                columnar_input,
                data_generation_id=generation_id,
                numeric_execution_contract=NUMERIC_CONTRACT_ID,
                semantic_versions=research_run_service.SEMANTIC_VERSIONS,
            ),
            research_data=columnar,
            forward_labels=prepare_columnar_forward_labels(
                columnar,
                cancellation_check=lambda: None,
            ),
            research_sessions=sessions,
            final_chunk=True,
            continuation=empty_research_continuation("factor_evaluation"),
            cancellation_check=lambda: None,
        )
        assert calculation.final_values is not None
        return calculation.final_values

    output = run(run_input)
    return build_result_payload(
        output,
        research_kind=research_kind,
        rebalance_interval=(1 if research_kind == "strategy_backtest" else None),
        universe="top300",
    )


def _read_result(runtime, stored: dict[str, object]) -> dict[str, object]:
    immutable_input = stored["immutable_input"]
    assert isinstance(immutable_input, dict)
    return read_result_bundle(
        runtime.publication.read(
            PublishedRef(
                manifest_sha256=str(stored["result_manifest_sha256"]),
                kind="research.result",
                provenance=stored["result_provenance"],
            )
        ),
        research_kind=str(immutable_input["research_kind"]),
    )


def _expire_live_attempt(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET lease_expires_at = '2000-01-01'
                WHERE run_id = %s AND status = 'running'
                """,
                (run_id,),
            )
        assert updated.rowcount == 1
    finally:
        database.close()


def _set_attempt_timing(settings: CoreSettings, run_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET started_at = CASE ordinal
                        WHEN 1 THEN '2026-08-13T10:00:00Z'::timestamptz
                        WHEN 2 THEN '2026-08-13T10:06:00Z'::timestamptz
                    END,
                    finished_at = CASE ordinal
                        WHEN 1 THEN '2026-08-13T10:01:00Z'::timestamptz
                        WHEN 2 THEN '2026-08-13T10:08:00Z'::timestamptz
                    END
                WHERE run_id = %s
                """,
                (run_id,),
            )
        assert updated.rowcount == 2
    finally:
        database.close()


def _attempts(settings: CoreSettings, run_id: str) -> list[dict[str, object]]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT ordinal, status, failure_reason, data_generation_id
                FROM research_runs.attempts
                WHERE run_id = %s
                ORDER BY ordinal
                """,
                (run_id,),
            ).fetchall()
        return rows
    finally:
        database.close()


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT immutable_input, result_manifest_sha256, result_provenance
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return row
    finally:
        database.close()


def _checkpoint_ordinals(settings: CoreSettings, run_id: str) -> list[int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT ordinal
                FROM research_runs.execution_checkpoints
                WHERE run_id = %s
                ORDER BY ordinal
                """,
                (run_id,),
            ).fetchall()
        return [int(row["ordinal"]) for row in rows]
    finally:
        database.close()


def _assert_factor_checkpoint_evidence(
    runtime,
    settings: CoreSettings,
    run_id: str,
    *,
    expected_generation_id: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT checkpoint.*, manifest.manifest_bytes,
                       attempt.fence AS creator_fence,
                       attempt.data_generation_id,
                       run.immutable_input
                FROM research_runs.execution_checkpoints AS checkpoint
                JOIN research_runs.attempts AS attempt
                  ON attempt.id = checkpoint.attempt_id
                JOIN research_runs.runs AS run ON run.id = checkpoint.run_id
                JOIN publication.manifests AS manifest
                  ON manifest.sha256 = checkpoint.checkpoint_manifest_sha256
                WHERE checkpoint.run_id = %s
                ORDER BY checkpoint.ordinal
                """,
                (run_id,),
            ).fetchall()
    finally:
        database.close()

    assert [int(row["ordinal"]) for row in rows] == [1, 2]
    prior_chain: str | None = None
    for row in rows:
        immutable_input = dict(row["immutable_input"])
        manifest = json.loads(bytes(row["manifest_bytes"]))
        provenance = manifest["provenance"]
        assert provenance["research_kind"] == "factor_evaluation"
        assert provenance["run_id"] == run_id
        assert provenance["creator_attempt_id"] == row["attempt_id"]
        assert provenance["creator_fence"] == int(row["creator_fence"])
        assert provenance["data_generation_id"] == expected_generation_id
        assert provenance["ordinal"] == int(row["ordinal"])
        assert provenance["boundary_session"] == row["boundary_session"].isoformat()
        assert provenance["completed_research_sessions"] == int(
            row["completed_research_sessions"]
        )
        assert provenance["immutable_input_sha256"] == hashlib.sha256(
            canonical_json_bytes(immutable_input)
        ).hexdigest()
        assert provenance["execution_plan_sha256"] == hashlib.sha256(
            canonical_json_bytes(immutable_input["execution_plan"])
        ).hexdigest()
        assert provenance["continuation_payload"] == row["continuation_payload"]
        assert provenance["observation_payload"] is None
        assert provenance["final_values_payload"] is None
        assert provenance["prior_chain_sha256"] == prior_chain
        assert hashlib.sha256(canonical_json_bytes(provenance)).hexdigest() == row[
            "chain_sha256"
        ]

        bundle = runtime.publication.read(
            PublishedRef(
                manifest_sha256=str(row["checkpoint_manifest_sha256"]),
                kind="research.execution-checkpoint",
                provenance=provenance,
            )
        )
        assert set(bundle.payloads) == {"continuation"}
        continuation = json.loads(bundle.payloads["continuation"].content)
        assert set(continuation) == {
            "schema_version",
            "research_kind",
            "binding_checksum",
            "completed_research_session_count",
            "rolling_tail_sessions",
            "pending_alpha",
            "alpha_checksum",
            "factor_state",
        }
        assert continuation["research_kind"] == "factor_evaluation"
        assert continuation["completed_research_session_count"] == int(
            row["completed_research_sessions"]
        )
        assert len(continuation["pending_alpha"]) <= 21
        assert "strategy" not in repr(continuation).lower()
        assert row["observation_payload"] is None
        assert int(row["observation_row_count"]) == 0
        prior_chain = str(row["chain_sha256"])


@contextmanager
def _corrupt_first_checkpoint_payload(
    settings: CoreSettings,
    run_id: str,
) -> Iterator[None]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT continuation_payload
                FROM research_runs.execution_checkpoints
                WHERE run_id = %s
                ORDER BY ordinal
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        digest = str(row["continuation_payload"]["sha256"])
    finally:
        database.close()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    key = f"publication/v1/sha256/{digest[:2]}/{digest}"
    original = s3.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    try:
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=b"corrupt-checkpoint-payload",
        )
        yield
    finally:
        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                referenced = transaction.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM publication.manifest_objects
                        WHERE object_sha256 = %s
                    ) AS referenced
                    """,
                    (digest,),
                ).fetchone()
            assert referenced is not None
        finally:
            database.close()
        if referenced["referenced"]:
            s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=original)
        else:
            s3.delete_object(Bucket=settings.s3_bucket, Key=key)


def _research_result_manifest_count(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS count
                FROM publication.manifests
                WHERE kind = 'research.result'
                """
            ).fetchone()
        assert row is not None
        return int(row["count"])
    finally:
        database.close()


def _install_transient_result_publication_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION publication.reject_ticket06_result_transiently()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected transient Result publication failure'
                        USING ERRCODE = '08006';
                END
                $$;
                CREATE TRIGGER reject_ticket06_result_transiently
                BEFORE INSERT ON publication.manifests
                FOR EACH ROW
                WHEN (NEW.kind = 'research.result')
                EXECUTE FUNCTION publication.reject_ticket06_result_transiently();
                """
            )
    finally:
        database.close()


def _remove_transient_result_publication_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_ticket06_result_transiently
                    ON publication.manifests;
                DROP FUNCTION publication.reject_ticket06_result_transiently();
                """
            )
    finally:
        database.close()


def _install_resource_exhaustion(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION publication.reject_ticket15_out_of_memory()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'secret-resource-pressure-detail'
                        USING ERRCODE = '53200';
                END
                $$;
                CREATE TRIGGER reject_ticket15_out_of_memory
                BEFORE INSERT ON publication.manifests
                FOR EACH ROW
                EXECUTE FUNCTION publication.reject_ticket15_out_of_memory();
                """
            )
    finally:
        database.close()


def _remove_resource_exhaustion(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER reject_ticket15_out_of_memory ON publication.manifests;
                DROP FUNCTION publication.reject_ticket15_out_of_memory();
                """
            )
    finally:
        database.close()


def _terminate_backend(settings: CoreSettings, backend_pid: int) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT pg_terminate_backend(%s) AS terminated",
                (backend_pid,),
            ).fetchone()
        assert row == {"terminated": True}
    finally:
        database.close()


@contextmanager
def _blocked_worker(
    settings: CoreSettings,
    run_id: str,
    *,
    after_checkpoint_count: int = 0,
) -> Iterator[_BlockedWorker]:
    if not 0 <= after_checkpoint_count <= 100:
        raise ValueError("Checkpoint barrier count is invalid")
    advisory_owner: Connection[object] | None = None
    trigger_created = False
    blocked: _BlockedWorker | None = None
    try:
        advisory_owner = connect(settings.database_url, autocommit=True)
        advisory_owner.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_KEY,)).fetchone()
        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                transaction.execute(
                    """
                    CREATE TABLE publication.ticket15_barrier_config (
                        after_checkpoint_count integer NOT NULL
                    )
                    """
                )
                transaction.execute(
                    """
                    INSERT INTO publication.ticket15_barrier_config
                    VALUES (%s)
                    """,
                    (after_checkpoint_count,),
                )
                transaction.execute(
                    """
                    CREATE FUNCTION publication.block_ticket15_manifest()
                    RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    DECLARE
                        configured_count integer;
                    BEGIN
                        SELECT after_checkpoint_count INTO configured_count
                        FROM publication.ticket15_barrier_config;
                        IF configured_count = 0 OR (
                            NEW.kind = 'research.execution-checkpoint'
                            AND (
                                SELECT count(*)
                                FROM publication.manifests
                                WHERE kind = 'research.execution-checkpoint'
                            ) >= configured_count
                        ) THEN
                            PERFORM pg_advisory_xact_lock(150015);
                        END IF;
                        RETURN NEW;
                    END
                    $$;
                    CREATE TRIGGER block_ticket15_manifest
                    BEFORE INSERT ON publication.manifests
                    FOR EACH ROW
                    EXECUTE FUNCTION publication.block_ticket15_manifest();
                    """
                )
            trigger_created = True
        finally:
            database.close()
        application_name = f"ticket15_{uuid4().hex}"
        worker_settings = replace(
            settings,
            database_url=make_conninfo(
                settings.database_url,
                application_name=application_name,
            ),
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "thesistrace.entrypoints.worker",
                "--role",
                "research",
                "--once",
            ],
            env=_worker_environment(worker_settings),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        blocked = _BlockedWorker(
            settings=settings,
            run_id=run_id,
            process=process,
            advisory_owner=advisory_owner,
            application_name=application_name,
        )
        yield blocked
    finally:
        if blocked is not None:
            blocked.close()
        else:
            if advisory_owner is not None and not advisory_owner.closed:
                advisory_owner.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_KEY,)).fetchone()
                advisory_owner.close()
            if trigger_created:
                _drop_worker_block(settings)


def _drop_worker_block(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DROP TRIGGER IF EXISTS block_ticket15_manifest
                    ON publication.manifests;
                DROP FUNCTION IF EXISTS publication.block_ticket15_manifest();
                DROP TABLE IF EXISTS publication.ticket15_barrier_config;
                """
            )
    finally:
        database.close()


def _run_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "research",
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=_worker_environment(settings),
    )


def _worker_events(
    completed: subprocess.CompletedProcess[str],
) -> list[dict[str, object]]:
    return [json.loads(line) for line in completed.stderr.splitlines() if line.startswith("{")]


def _worker_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
    }
