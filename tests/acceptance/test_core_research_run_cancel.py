from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic

import boto3
import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from psycopg import connect
from test_core_current_head_research_run_retry import (
    _admit_run,
    _install_resource_exhaustion,
    _publish_head,
    _remove_resource_exhaustion,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.execution import SupervisedResearchExecutor

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_queued_cancel_replays_and_conflicts_without_malformed_receipt(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-queued-cancel")
        second_id = _admit_run(client, request_id="current-data-conflict-target")

        cancelled = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-cancel"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert _run_storage(runtime.database, run_id) == {
            "status": "cancelled",
            "execution_fence": 1,
            "attempt_count": 0,
            "result_count": 0,
        }

        replay = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-cancel"},
        )
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert _cancel_receipt_count(runtime.database) == 1

        conflict = client.post(
            f"/api/research-runs/{second_id}/cancel",
            json={"request_id": "current-data-cancel"},
        )
        assert conflict.status_code == 409
        malformed = client.post(
            f"/api/research-runs/{second_id}/cancel",
            json={"unexpected": "field"},
        )
        assert malformed.status_code == 422
        assert _run_storage(runtime.database, second_id)["status"] == "queued"
        missing = client.post(
            "/api/research-runs/run_missing/cancel",
            json={"request_id": "current-data-missing"},
        )
        assert missing.status_code == 404


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_running_cancel_fences_a_stale_prepared_worker_and_survives_restart(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-running-cancel")

        def pause_after_prepare(stage: str, _run_id: str) -> None:
            if stage == "prepared":
                prepared.set()
                assert release_stale.wait(timeout=30)

        stale = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
            progress=pause_after_prepare,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale.process_next)
            assert prepared.wait(timeout=20)
            try:
                cancelled = client.post(
                    f"/api/research-runs/{run_id}/cancel",
                    json={"request_id": "current-data-running-cancel-request"},
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelling"
                assert _attempt_status(runtime.database, run_id) == "cancelling"
                assert _active_pin_count(runtime.database) == 1
            finally:
                release_stale.set()
            assert future.result(timeout=30) is True

        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        assert _run_storage(runtime.database, run_id)["result_count"] == 0

    with TestClient(create_app(settings)) as restarted:
        replay = restarted.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-running-cancel-request"},
        )
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert restarted.app.state.core_runtime.research_runs.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_running_cancel_cooperatively_stops_child_before_terminal_state(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    child_started = Event()
    release_child = Event()
    events: list[dict[str, object]] = []

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="cooperative-running-cancel")

        def hold_started_child(event: dict[str, object]) -> None:
            events.append(event)
            if event["event"] == "research_execution_child_started":
                child_started.set()
                assert release_child.wait(timeout=20)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                runtime.research_runs.process_next,
                on_execution_event=hold_started_child,
            )
            assert child_started.wait(timeout=20)
            cancel_started = monotonic()
            cancelled = client.post(
                f"/api/research-runs/{run_id}/cancel",
                json={"request_id": "cooperative-running-cancel-request"},
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelling"
            assert _attempt_status(runtime.database, run_id) == "cancelling"
            assert _active_pin_count(runtime.database) == 1
            release_child.set()
            assert future.result(timeout=10) is True
            assert monotonic() - cancel_started < 5

        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        assert _run_storage(runtime.database, run_id)["result_count"] == 0
        event_names = [event["event"] for event in events]
        assert "research_execution_child_cancel_requested" in event_names
        assert "research_execution_child_termination_requested" not in event_names
        assert event_names[-1] == "research_execution_child_exited"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_running_cancel_forces_an_unresponsive_child_to_exit_within_budget(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    child_stopped = Event()
    events: list[dict[str, object]] = []

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="forced-running-cancel")

        def stop_started_child(event: dict[str, object]) -> None:
            events.append(event)
            if event["event"] == "research_execution_child_started":
                os.kill(int(event["child_pid"]), signal.SIGSTOP)
                child_stopped.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                runtime.research_runs.process_next,
                on_execution_event=stop_started_child,
            )
            assert child_stopped.wait(timeout=20)
            cancel_started = monotonic()
            cancelled = client.post(
                f"/api/research-runs/{run_id}/cancel",
                json={"request_id": "forced-running-cancel-request"},
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelling"
            assert _active_pin_count(runtime.database) == 1
            assert future.result(timeout=10) is True
            assert monotonic() - cancel_started < 5

        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        event_names = [event["event"] for event in events]
        assert "research_execution_child_cancel_requested" in event_names
        assert "research_execution_child_termination_requested" in event_names
        assert event_names[-1] == "research_execution_child_exited"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_lost_supervisor_cancel_waits_for_lease_expiry_before_recovery(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    owner: subprocess.Popen[str] | None = None
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="lost-supervisor-cancel")
        try:
            owner = _start_claim_barrier_worker(settings, "research")
            assert _wait_for_barrier_claim(owner)["resource_id"] == run_id
            owner.terminate()
            owner.communicate(timeout=10)
        finally:
            if owner is not None and owner.poll() is None:
                owner.terminate()
                owner.communicate(timeout=10)

        cancelled = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "lost-supervisor-cancel-request"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelling"
        assert _attempt_status(runtime.database, run_id) == "cancelling"
        assert _active_pin_count(runtime.database) == 1

    with TestClient(create_app(settings)) as restarted:
        runtime = restarted.app.state.core_runtime
        assert runtime.research_runs.process_next() is False
        assert _attempt_status(runtime.database, run_id) == "cancelling"
        assert _active_pin_count(runtime.database) == 1

        _expire_cancelling_attempt(runtime.database, run_id)
        assert runtime.research_runs.process_next() is True
        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        assert _run_storage(runtime.database, run_id)["attempt_count"] == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_stale_claim_is_rejected_before_any_result_objects_are_staged(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    claimed = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-pre-stage-fence")
        before = _publication_object_keys(settings)

        def pause_after_claim(stage: str, _run_id: str) -> None:
            if stage == "claimed":
                claimed.set()
                assert release_stale.wait(timeout=30)

        stale = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=SupervisedResearchExecutor(settings.data_mount),
            progress=pause_after_claim,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale.process_next)
            assert claimed.wait(timeout=20)
            try:
                cancelled = client.post(
                    f"/api/research-runs/{run_id}/cancel",
                    json={"request_id": "current-data-pre-stage-fence-cancel"},
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelling"
            finally:
                release_stale.set()
            assert future.result(timeout=30) is True

        assert _publication_object_keys(settings) == before
        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _run_storage(runtime.database, run_id)["result_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_cancel_wins_production_staging_authority_without_result_objects(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="cancel-wins-staging-lock")
        before = _publication_object_keys(settings)
        staging_owner = connect(settings.database_url)
        try:
            staging_owner.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"research_runs.result_staging:{run_id}",),
            ).fetchone()
            with ThreadPoolExecutor(max_workers=2) as executor:
                try:
                    cancel_future = executor.submit(
                        client.post,
                        f"/api/research-runs/{run_id}/cancel",
                        json={"request_id": "cancel-wins-staging-lock-request"},
                    )
                    _wait_for_advisory_waiters(runtime.database, minimum=1)
                    worker_future = executor.submit(runtime.research_runs.process_next)
                    _wait_for_advisory_waiters(runtime.database, minimum=2)
                    staging_owner.commit()
                    cancelled = cancel_future.result(timeout=10)
                    assert cancelled.status_code == 200
                    assert cancelled.json()["status"] == "cancelling"
                    assert worker_future.result(timeout=10) is True
                finally:
                    staging_owner.rollback()
        finally:
            staging_owner.close()

        assert _publication_object_keys(settings) == before
        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        assert _run_storage(runtime.database, run_id)["result_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_cancel_racing_with_terminal_handshake_failure_is_confirmed_locally(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    acknowledgement_started = Event()
    release_failure = Event()

    class FailingAcknowledgement:
        def __init__(self, execution) -> None:
            self._execution = execution
            self.chunk = execution.chunk

        def advance(self, *, cancel_requested) -> None:
            self._execution.advance(cancel_requested=cancel_requested)
            self.chunk = self._execution.chunk

        def acknowledge(self, *, cancel_requested) -> None:
            acknowledgement_started.set()
            assert release_failure.wait(timeout=20)
            raise RuntimeError("terminal acknowledgement fault")

        def cancel(self) -> None:
            self._execution.cancel()

        def close(self) -> None:
            self._execution.close()

    class FailingAcknowledgementExecutor:
        def __init__(self) -> None:
            self._delegate = SupervisedResearchExecutor(settings.data_mount)

        def execute(self, request, *, emit, cancel_requested):
            return FailingAcknowledgement(
                self._delegate.execute(
                    request,
                    emit=emit,
                    cancel_requested=cancel_requested,
                )
            )

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="cancel-acknowledgement-failure")
        service = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=FailingAcknowledgementExecutor(),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service.process_next)
            assert acknowledgement_started.wait(timeout=20)
            cancelled = client.post(
                f"/api/research-runs/{run_id}/cancel",
                json={"request_id": "cancel-acknowledgement-failure-request"},
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelling"
            release_failure.set()
            assert future.result(timeout=10) is True

        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        assert _run_storage(runtime.database, run_id)["result_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_handshake_failure_keeps_attempt_live_until_child_close_and_cancel(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)
    close_started = Event()
    release_close = Event()

    class FailingBeforeSlowClose:
        def __init__(self, execution) -> None:
            self._execution = execution
            self.chunk = execution.chunk

        def advance(self, *, cancel_requested) -> None:
            self._execution.advance(cancel_requested=cancel_requested)
            self.chunk = self._execution.chunk

        def acknowledge(self, *, cancel_requested) -> None:
            raise RuntimeError("terminal acknowledgement fault before close")

        def cancel(self) -> None:
            self._execution.cancel()

        def close(self) -> None:
            close_started.set()
            assert release_close.wait(timeout=20)
            self._execution.close()

    class FailingBeforeSlowCloseExecutor:
        def __init__(self) -> None:
            self._delegate = SupervisedResearchExecutor(settings.data_mount)

        def execute(self, request, *, emit, cancel_requested):
            return FailingBeforeSlowClose(
                self._delegate.execute(
                    request,
                    emit=emit,
                    cancel_requested=cancel_requested,
                )
            )

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="failure-before-cancel")
        service = ResearchRunService(
            runtime.database,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount),
            publication=runtime.publication,
            execution=FailingBeforeSlowCloseExecutor(),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service.process_next)
            assert close_started.wait(timeout=20)
            cancelled = client.post(
                f"/api/research-runs/{run_id}/cancel",
                json={"request_id": "failure-before-cancel-request"},
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelling"
            assert _attempt_status(runtime.database, run_id) == "cancelling"
            assert _active_pin_count(runtime.database) == 1
            release_close.set()
            assert future.result(timeout=10) is True

        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _active_pin_count(runtime.database) == 0
        assert _run_storage(runtime.database, run_id)["result_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_terminal_run_wins_over_late_cancel(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="current-data-terminal-cancel")
        assert runtime.research_runs.process_next() is True
        before = client.get(f"/api/research-runs/{run_id}").json()
        assert before["status"] == "succeeded"

        outcome = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "current-data-after-success"},
        )
        assert outcome.status_code == 200
        assert outcome.json() == {
            key: before[key]
            for key in (
                "id",
                "status",
                "name",
                "folder_id",
                "created_at",
                "start_date",
                "end_date",
                "formula_summary",
            )
        }
        assert client.get(f"/api/research-runs/{run_id}").json() == before


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_cancel_during_retry_wait_prevents_another_attempt(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, price_offset=0)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="cancel-retry-wait")
        _install_resource_exhaustion(settings)
        try:
            assert runtime.research_runs.process_next() is True
        finally:
            _remove_resource_exhaustion(settings)
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
        assert _attempt_status(runtime.database, run_id) == "failed"

        cancelled = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "cancel-retry-wait-request"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert runtime.research_runs.process_next() is False
        assert _run_storage(runtime.database, run_id)["attempt_count"] == 1
        assert _active_pin_count(runtime.database) == 0


def _run_storage(database: PostgresDatabase, run_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT run.status, run.execution_fence,
                   (SELECT count(*) FROM research_runs.attempts AS attempt
                    WHERE attempt.run_id = run.id) AS attempt_count,
                   (SELECT count(*) FROM publication.manifests
                    WHERE kind = 'research.result') AS result_count
            FROM research_runs.runs AS run
            WHERE run.id = %s
            """,
            (run_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _attempt_status(database: PostgresDatabase, run_id: str) -> str:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT status FROM research_runs.attempts WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _cancel_receipt_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS count FROM research_runs.cancel_receipts"
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _active_pin_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS count FROM data.generation_pins WHERE status = 'active'"
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _expire_cancelling_attempt(database: PostgresDatabase, run_id: str) -> None:
    with database.transaction() as transaction:
        updated = transaction.execute(
            """
            UPDATE research_runs.attempts
            SET lease_expires_at = '2000-01-01'
            WHERE run_id = %s AND status = 'cancelling'
            """,
            (run_id,),
        )
    assert updated.rowcount == 1


def _wait_for_advisory_waiters(
    database: PostgresDatabase,
    *,
    minimum: int,
) -> None:
    poll = Event()
    for _ in range(500):
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS count
                FROM pg_locks
                WHERE locktype = 'advisory' AND NOT granted
                """
            ).fetchone()
        assert row is not None
        if int(row["count"]) >= minimum:
            return
        poll.wait(0.02)
    raise AssertionError(f"fewer than {minimum} advisory lock waiters became visible")


def _start_claim_barrier_worker(
    settings: CoreSettings,
    role: str,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "tests/acceptance/process_worker_with_claim_barrier.py",
            role,
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "THESISTRACE_DATABASE_URL": settings.database_url,
            "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
            "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
            "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
            "THESISTRACE_S3_BUCKET": settings.s3_bucket,
            "THESISTRACE_S3_REGION": settings.s3_region,
            "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_barrier_claim(process: subprocess.Popen[str]) -> dict[str, object]:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        assert selector.select(timeout=30), "Worker did not reach its claim barrier"
        line = process.stdout.readline()
    finally:
        selector.close()
    assert line, f"Worker exited before claim: {process.stderr.read() if process.stderr else ''}"
    event = json.loads(line)
    assert event["event"] == "worker_claim"
    return event


def _publication_object_keys(settings: CoreSettings) -> set[str]:
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    return {
        str(item["Key"])
        for item in s3.list_objects_v2(
            Bucket=settings.s3_bucket,
            Prefix="publication/v1/sha256/",
        ).get("Contents", [])
    }
