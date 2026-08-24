from __future__ import annotations

import os
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_research_batch_admission import _factor_command, _publish_current_data
from test_core_research_batch_factor_execution import _PreparationBarrierExecutor
from test_core_research_batch_fifo import (
    _start_claim_barrier_worker,
    _terminate_and_collect,
    _wait_for_worker_event,
)

from thesistrace.data import DatasetLifecycle
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_batch import ResearchBatchService
from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor


class _KillSecondFactorExecution:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self._killed = False

    @property
    def message(self):
        return self._delegate.message

    def advance(self, command: str) -> None:
        self._delegate.advance(command)
        if (
            not self._killed
            and self.message.get("status") == "item_started"
            and self.message.get("item_ordinal") == 2
        ):
            os.kill(self._delegate.child_pid, signal.SIGKILL)
            self._killed = True

    def acknowledge(self) -> None:
        self._delegate.acknowledge()

    def close(self) -> None:
        self._delegate.close()


class _KillSecondFactorOnceExecutor:
    def __init__(self, delegate: SupervisedResearchBatchExecutor) -> None:
        self._delegate = delegate
        self.killed = False

    def execute(self, request, *, emit):
        execution = self._delegate.execute(request, emit=emit)
        if self.killed:
            return execution
        self.killed = True
        return _KillSecondFactorExecution(execution)


class _FinalFactorChunkBarrierExecution:
    def __init__(self, delegate, final_chunk: Event, release: Event) -> None:
        self._delegate = delegate
        self._final_chunk = final_chunk
        self._release = release

    @property
    def message(self):
        return self._delegate.message

    @property
    def child_pid(self) -> int:
        return self._delegate.child_pid

    def advance(self, command: str) -> None:
        self._delegate.advance(command)
        if (
            self.message.get("status") == "item_chunk_succeeded"
            and isinstance(self.message.get("chunk"), dict)
            and self.message["chunk"].get("final") is True
        ):
            self._final_chunk.set()
            if not self._release.wait(timeout=30):
                raise AssertionError("Final Factor Chunk barrier was not released")

    def acknowledge(self) -> None:
        self._delegate.acknowledge()

    def close(self) -> None:
        self._delegate.close()


class _FinalFactorChunkBarrierExecutor:
    def __init__(self, delegate: SupervisedResearchBatchExecutor) -> None:
        self._delegate = delegate
        self.final_chunk = Event()
        self.release = Event()

    def execute(self, request, *, emit):
        return _FinalFactorChunkBarrierExecution(
            self._delegate.execute(request, emit=emit),
            self.final_chunk,
            self.release,
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.dependency_restart
def test_real_rustfs_loss_retries_the_complete_factor_task(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    restarted_s3_port: int | None = None
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _factor_command("factor-rustfs-retry")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "factors": [{"item_key": "value", "formula": "close"}],
            },
        ).json()
        runtime = client.app.state.core_runtime
        _run_dependency_command("stop-rustfs")
        try:
            assert runtime.research_batches.process_next() is True
        finally:
            restarted_s3_port = _run_dependency_command("restart-rustfs")
        interrupted = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert interrupted["status"] == "queued"
        assert interrupted["progress"]["completed_factor_tasks"] == 0
        assert interrupted["items"][0]["task_attempt_count"] == 1
        assert interrupted["items"][0]["outcome"] is None

    assert restarted_s3_port is not None
    restarted_settings = replace(
        settings,
        s3_endpoint_url=f"http://127.0.0.1:{restarted_s3_port}",
    )
    with TestClient(create_app(restarted_settings)) as restarted:
        runtime = restarted.app.state.core_runtime
        assert runtime.research_batches.process_next() is True
        completed = restarted.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["items"][0]["task_attempt_count"] == 2
        assert _batch_attempt_evidence(runtime, admitted["id"]) == [
            ("failed", "InfrastructureUnavailable"),
            ("succeeded", None),
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.dependency_restart
def test_real_postgres_loss_recovers_after_child_exit(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    restarted_postgres_port: int | None = None
    attempt_id: str | None = None
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json={
                **_factor_command("factor-postgres-retry"),
                "factors": [{"item_key": "value", "formula": "close"}],
            },
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _FinalFactorChunkBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.data_mount / ".batch-attempts",
            execution=barrier,
            heartbeat_seconds=60,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(processor.process_next)
            assert barrier.final_chunk.wait(timeout=20)
            attempt_id = client.get(f"/api/research-batches/{admitted['id']}").json()[
                "attempt"
            ]["id"]
            _run_dependency_command("stop-postgres")
            barrier.release.set()
            try:
                assert future.result(timeout=90) is True
            finally:
                restarted_postgres_port = _run_dependency_command("restart-postgres")

    assert restarted_postgres_port is not None and attempt_id is not None
    restarted_settings = replace(
        settings,
        database_url=(
            "postgresql://thesistrace:thesistrace-test@127.0.0.1:"
            f"{restarted_postgres_port}/thesistrace"
        ),
    )
    with TestClient(create_app(restarted_settings)) as restarted:
        runtime = restarted.app.state.core_runtime
        _expire_batch_attempt(runtime, attempt_id)
        assert runtime.research_batches.process_next() is True
        completed = restarted.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["items"][0]["task_attempt_count"] == 2
        assert _batch_attempt_evidence(runtime, admitted["id"]) == [
            ("failed", "WorkerLost"),
            ("succeeded", None),
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_expired_lease_rejects_stale_child_output_before_publication(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("factor-expired-lease-fence"),
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _PreparationBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.data_mount / ".batch-attempts",
            execution=barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(processor.process_next)
            assert barrier.prepared.wait(timeout=10)
            first_attempt = client.get(
                f"/api/research-batches/{admitted['id']}"
            ).json()["attempt"]["id"]
            _expire_batch_attempt(runtime, first_attempt)
            barrier.release.set()
            assert future.result(timeout=20) is True

        fenced = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert fenced["status"] == "running"
        assert fenced["live_progress"] is None
        assert fenced["progress"]["completed_factor_tasks"] == 0
        assert all(item["outcome"] is None for item in fenced["items"])
        assert _pin_status_for_attempt(runtime, first_attempt) == "active"

        assert processor.process_next() is True
        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert [item["task_attempt_count"] for item in completed["items"]] == [2, 1]
        assert _lost_attempt_evidence(runtime, [first_attempt]) == [
            ("failed", "WorkerLost")
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_factor_child_loss_restarts_only_the_unacknowledged_whole_task(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        frozen_generation = _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("factor-child-loss-recovery"),
        ).json()
        runtime = client.app.state.core_runtime
        executor = _KillSecondFactorOnceExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.data_mount / ".batch-attempts",
            execution=executor,
        )

        assert processor.process_next() is True
        interrupted = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert interrupted["status"] == "queued"
        assert interrupted["progress"] == {
            "completed_factor_tasks": 1,
            "total_factor_tasks": 2,
        }
        assert [item["status"] for item in interrupted["items"]] == [
            "succeeded",
            "queued",
        ]
        assert [item["task_attempt_count"] for item in interrupted["items"]] == [1, 1]
        first_result = client.get(
            f"/api/research-runs/{interrupted['items'][0]['research_run_id']}"
        ).json()["result"]

        replacement = _publish_current_data(
            settings,
            operation_id="factor-child-loss-new-head",
            expected_generation=frozen_generation,
        )
        assert replacement != frozen_generation
        assert processor.process_next() is True

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert [item["task_attempt_count"] for item in completed["items"]] == [1, 2]
        assert client.get(
            f"/api/research-runs/{completed['items'][0]['research_run_id']}"
        ).json()["result"] == first_result
        assert all(
            _run_generation_id(runtime, str(item["research_run_id"])) == frozen_generation
            for item in completed["items"]
        )
        assert _attempt_and_pin_counts(runtime, admitted["id"]) == (2, 0, 2)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_three_lost_workers_exhaust_only_the_current_factor_and_continue(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        frozen_generation = _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("factor-worker-loss-retry-limit"),
        ).json()
        runtime = client.app.state.core_runtime
        lost_attempt_ids: list[str] = []

        for expected_attempt in range(1, 4):
            worker = _start_claim_barrier_worker(
                settings,
                "batch-research",
            )
            claim = _wait_for_worker_event(worker, "worker_claim")
            assert claim["resource_id"] == admitted["id"]
            lost_attempt_ids.append(str(claim["attempt_id"]))
            _expire_batch_attempt(runtime, str(claim["attempt_id"]))
            assert runtime.research_batches.process_next() is False
            assert _pin_status_for_attempt(runtime, str(claim["attempt_id"])) == "active"
            stdout, stderr = _terminate_and_collect(worker)
            assert worker.returncode is not None, (stdout, stderr)
            current = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert current["attempt"]["number"] == expected_attempt
            assert current["live_progress"] is None

        replacement = _publish_current_data(
            settings,
            operation_id="factor-worker-loss-new-head",
            expected_generation=frozen_generation,
        )
        assert replacement != frozen_generation
        assert runtime.research_batches.process_next() is True

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "completed_with_failures"
        assert completed["progress"] == {
            "completed_factor_tasks": 2,
            "total_factor_tasks": 2,
        }
        assert [item["status"] for item in completed["items"]] == [
            "failed",
            "succeeded",
        ]
        assert [item["task_attempt_count"] for item in completed["items"]] == [3, 1]
        assert completed["items"][0]["diagnostic"] == {
            "code": "FACTOR_TASK_RETRY_EXHAUSTED",
            "category": "infrastructure",
            "message": "Research execution could not complete after automatic retries.",
        }
        assert completed["attempt"]["number"] == 4
        assert completed["attempt"]["status"] == "succeeded"
        assert _attempt_and_pin_counts(runtime, admitted["id"]) == (4, 0, 4)
        assert _lost_attempt_evidence(runtime, lost_attempt_ids) == [
            ("failed", "WorkerLost"),
            ("failed", "WorkerLost"),
            ("failed", "WorkerLost"),
        ]
        assert (
            _run_generation_id(runtime, str(completed["items"][1]["research_run_id"]))
            == frozen_generation
        )


def _expire_batch_attempt(runtime, attempt_id: str) -> None:
    with runtime.database.transaction() as transaction:
        transaction.execute(
            """
            UPDATE research_batches.attempts
            SET lease_expires_at = now() - interval '1 second'
            WHERE id = %s AND status = 'running'
            """,
            (attempt_id,),
        )


def _attempt_and_pin_counts(runtime, batch_id: str) -> tuple[int, int, int]:
    with runtime.database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT count(*) AS attempts,
                   count(*) FILTER (WHERE pin.status = 'active') AS active_pins,
                   count(*) FILTER (WHERE pin.status = 'released') AS released_pins
            FROM research_batches.attempts AS attempt
            JOIN data.generation_pins AS pin ON pin.id = attempt.generation_pin_id
            WHERE attempt.batch_id = %s
            """,
            (batch_id,),
        ).fetchone()
    assert row is not None
    return int(row["attempts"]), int(row["active_pins"]), int(row["released_pins"])


def _lost_attempt_evidence(runtime, attempt_ids: list[str]) -> list[tuple[str, str]]:
    with runtime.database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT status, failure_reason
            FROM research_batches.attempts
            WHERE id = ANY(%s)
            ORDER BY ordinal
            """,
            (attempt_ids,),
        ).fetchall()
    return [(str(row["status"]), str(row["failure_reason"])) for row in rows]


def _batch_attempt_evidence(runtime, batch_id: str) -> list[tuple[str, str | None]]:
    with runtime.database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT status, failure_reason
            FROM research_batches.attempts
            WHERE batch_id = %s
            ORDER BY ordinal
            """,
            (batch_id,),
        ).fetchall()
    return [
        (
            str(row["status"]),
            str(row["failure_reason"]) if row["failure_reason"] is not None else None,
        )
        for row in rows
    ]


def _pin_status_for_attempt(runtime, attempt_id: str) -> str:
    with runtime.database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT pin.status
            FROM research_batches.attempts AS attempt
            JOIN data.generation_pins AS pin ON pin.id = attempt.generation_pin_id
            WHERE attempt.id = %s
            """,
            (attempt_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _run_generation_id(runtime, run_id: str) -> str:
    with runtime.database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT result_provenance ->> 'data_generation_id' AS data_generation_id
            FROM research_runs.runs
            WHERE id = %s
            """,
            (run_id,),
        ).fetchone()
    assert row is not None
    return str(row["data_generation_id"])


def _run_dependency_command(command: str) -> int | None:
    if not os.environ.get("THESISTRACE_TEST_PROJECT_NAME"):
        pytest.skip("an isolated Core Compose project is required for dependency restart")
    completed = subprocess.run(
        ["./scripts/test-runtime", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if command.startswith("restart-"):
        port = completed.stdout.strip().rsplit(":", maxsplit=1)[-1]
        assert port.isdigit(), completed.stdout
        return int(port)
    return None
