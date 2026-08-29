from __future__ import annotations

import os
import selectors
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, isolated_core_settings
from fastapi.testclient import TestClient
from test_core_research_batch_admission import (
    _factor_command,
    _publish_current_data,
    _strategy_command,
)
from test_core_research_batch_factor_recovery import _run_dependency_command
from test_core_research_batch_fifo import (
    _release_claim_barrier_worker,
    _run_worker_once,
    _start_claim_barrier_worker,
    _terminate_worker,
    _wait_for_worker_event,
)
from test_core_research_batch_history import _TaskStartBarrierExecutor

from thesistrace.data import DatasetLifecycle
from thesistrace.entrypoints.runtime import core_environment_is_configured
from thesistrace.publication import PublicationUnavailableError
from thesistrace.research_batch import ResearchBatchService
from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)


class _StartingClaimBarrierExecutor:
    def __init__(self, delegate: SupervisedResearchBatchExecutor) -> None:
        self._delegate = delegate
        self.entered = Event()
        self.release = Event()

    def execute(self, request, *, emit, cancel_requested):
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("Research Batch starting-claim barrier timed out")
        return self._delegate.execute(
            request,
            emit=emit,
            cancel_requested=cancel_requested,
        )


def _wait_for_worker_stderr(process, pattern: str) -> None:
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stderr, selectors.EVENT_READ)
    deadline = monotonic() + 10
    observed: list[str] = []
    try:
        while monotonic() < deadline:
            ready = selector.select(timeout=max(0.0, deadline - monotonic()))
            if not ready:
                break
            line = process.stderr.readline()
            if not line:
                break
            observed.append(line)
            if pattern in line:
                return
    finally:
        selector.close()
    raise AssertionError(f"Worker stderr did not contain {pattern!r}; observed={observed!r}")


def test_queued_cancel_is_atomic_idempotent_conflict_safe_and_terminal(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        first = client.post(
            "/api/research-batches",
            json=_factor_command("batch-cancel-queued-first"),
        ).json()
        second = client.post(
            "/api/research-batches",
            json=_factor_command("batch-cancel-queued-second"),
        ).json()
        queued_strategy = client.post(
            "/api/research-batches",
            json=_strategy_command("batch-cancel-queued-strategy"),
        ).json()

        cancelled = client.post(
            f"/api/research-batches/{first['id']}/cancel",
            json={"request_id": "cancel-queued"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["progress"] == {
            "completed_factor_tasks": 0,
            "total_factor_tasks": 2,
        }
        assert cancelled.json()["attempt"] is None
        assert [item["status"] for item in cancelled.json()["items"]] == [
            "cancelled",
            "cancelled",
        ]
        assert [item["outcome"] for item in cancelled.json()["items"]] == [
            "cancelled",
            "cancelled",
        ]
        assert (
            client.post(
                f"/api/research-batches/{first['id']}/cancel",
                json={"request_id": "batch-cancel-queued-first"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/research-batches/{first['id']}/cancel",
                json={"request_id": "cancel-queued"},
            ).json()
            == cancelled.json()
        )
        assert (
            client.post(
                f"/api/research-batches/{second['id']}/cancel",
                json={"request_id": "cancel-queued"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/research-batches/{first['id']}/items/1/cancel",
                json={"request_id": "per-item-is-not-supported"},
            ).status_code
            == 404
        )
        strategy_cancelled = client.post(
            f"/api/research-batches/{queued_strategy['id']}/cancel",
            json={"request_id": "cancel-queued-strategy"},
        )
        assert strategy_cancelled.status_code == 200, strategy_cancelled.text
        assert strategy_cancelled.json()["status"] == "cancelled"
        assert strategy_cancelled.json()["progress"] == {
            "shared_alpha_factor_status": "cancelled",
            "completed_strategy_tasks": 0,
            "total_strategy_tasks": 2,
        }
        assert (
            client.post(
                "/api/research-batches",
                json=_factor_command("cancel-queued"),
            ).status_code
            == 409
        )

        assert client.app.state.core_runtime.research_batches.process_next() is True
        natural = client.get(f"/api/research-batches/{second['id']}").json()
        assert natural["status"] == "succeeded"
        late = client.post(
            f"/api/research-batches/{second['id']}/cancel",
            json={"request_id": "cancel-after-natural-terminal"},
        )
        assert late.status_code == 409

        with client.app.state.core_runtime.database.transaction() as transaction:
            receipts = transaction.execute(
                "SELECT request_id, batch_id FROM research_batches.cancel_receipts"
            ).fetchall()
        assert {(row["request_id"], row["batch_id"]) for row in receipts} == {
            ("cancel-queued", first["id"]),
            ("cancel-queued-strategy", queued_strategy["id"]),
        }


def test_running_strategy_cancel_preserves_acknowledged_result_and_daily_track(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    cancelled = Event()
    cancel_response: list[dict[str, object]] = []
    track_ids: list[str] = []

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("batch-cancel-running-strategy"),
        ).json()

        def observe(event: dict[str, object]) -> None:
            if (
                event.get("event") != "research_batch_execution_item_started"
                or event.get("item_ordinal") != 2
                or cancelled.is_set()
            ):
                return
            first_run_id = str(admitted["items"][0]["research_run_id"])
            track = client.post(
                f"/api/research-runs/{first_run_id}/daily-tracks",
                json={"request_id": "track-before-batch-cancel"},
            )
            assert track.status_code == 201, track.text
            track_ids.append(str(track.json()["id"]))
            response = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-running-strategy"},
            )
            assert response.status_code == 200, response.text
            cancel_response.append(response.json())
            cancelled.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.app.state.core_runtime.research_batches.process_next,
                on_execution_event=observe,
            )
            assert future.result(timeout=30) is True

        assert cancelled.is_set()
        assert cancel_response[0]["status"] == "cancelling"
        detail = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert detail["status"] == "cancelled"
        assert detail["progress"] == {
            "shared_alpha_factor_status": "succeeded",
            "completed_strategy_tasks": 1,
            "total_strategy_tasks": 2,
        }
        assert [item["status"] for item in detail["items"]] == [
            "succeeded",
            "cancelled",
        ]
        assert detail["attempt"]["status"] == "cancelled"
        assert detail["live_progress"] is None
        assert [item["task_attempt_count"] for item in detail["items"]] == [1, 1]
        first_run = client.get(f"/api/research-runs/{detail['items'][0]['research_run_id']}").json()
        assert first_run["result"] is not None
        second_run = client.get(
            f"/api/research-runs/{detail['items'][1]['research_run_id']}"
        ).json()
        assert second_run["status"] == "cancelled"
        assert "result" not in second_run
        assert client.get(f"/api/daily-tracks/{track_ids[0]}").status_code == 200
        with client.app.state.core_runtime.database.transaction() as transaction:
            state = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM data.generation_pins
                     WHERE owner_id = %s AND status = 'active') AS active_pins,
                    (SELECT count(*) FROM research_batches.task_attempts
                     WHERE batch_id = %s AND status = 'running') AS running_tasks,
                    (SELECT count(*) FROM research_batches.task_attempts
                     WHERE batch_id = %s AND status = 'cancelled') AS cancelled_tasks,
                    (SELECT count(*) FROM research_runs.execution_checkpoints
                     WHERE run_id = %s) AS incomplete_checkpoints,
                    (SELECT count(*) FROM research_batches.private_alpha_factor_artifacts
                     WHERE batch_id = %s) AS private_artifacts
                """,
                (
                    detail["attempt"]["id"],
                    admitted["id"],
                    admitted["id"],
                    detail["items"][1]["research_run_id"],
                    admitted["id"],
                ),
            ).fetchone()
        assert state == {
            "active_pins": 0,
            "running_tasks": 0,
            "cancelled_tasks": 1,
            "incomplete_checkpoints": 0,
            "private_artifacts": 0,
        }


def test_cancel_receipt_and_terminal_state_survive_api_restart(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("batch-cancel-api-restart"),
        ).json()
        first = client.post(
            f"/api/research-batches/{admitted['id']}/cancel",
            json={"request_id": "cancel-survives-api-restart"},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "cancelled"

    with TestClient(create_app(settings)) as restarted:
        replay = restarted.post(
            f"/api/research-batches/{admitted['id']}/cancel",
            json={"request_id": "cancel-survives-api-restart"},
        )
        assert replay.status_code == 200
        assert replay.json() == first.json()
        assert restarted.app.state.core_runtime.research_batches.process_next() is False


def test_cancel_does_not_finalize_while_claim_owner_can_still_start_child(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("batch-cancel-starting-claim-race"),
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _StartingClaimBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            )
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=barrier,
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(processor.process_next)
            assert barrier.entered.wait(timeout=10)
            response = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-starting-claim-race"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "cancelling"

            assert runtime.research_batches.process_next() is False
            still_cancelling = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert still_cancelling["status"] == "cancelling"
            assert still_cancelling["attempt"] is None

            barrier.release.set()
            assert future.result(timeout=20) is True

        terminal = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert terminal["status"] == "cancelled"
        assert terminal["attempt"] is None
        assert [item["task_attempt_count"] for item in terminal["items"]] == [0, 0]


def test_cancel_fence_rejects_unacknowledged_factor_result_publication(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("batch-cancel-stale-publication"),
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _TaskStartBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
            target_status="item_chunk_succeeded",
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=barrier,
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(processor.process_next)
            assert barrier.created.wait(timeout=10)
            assert barrier.execution is not None
            assert barrier.execution.started.wait(timeout=20)
            response = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-stale-publication"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "cancelling"
            barrier.execution.release.set()
            assert future.result(timeout=20) is True

        terminal = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert terminal["status"] == "cancelled"
        assert [item["outcome"] for item in terminal["items"]] == [
            "cancelled",
            "cancelled",
        ]
        assert [item["task_attempt_count"] for item in terminal["items"]] == [1, 0]
        with runtime.database.transaction() as transaction:
            stale_results = transaction.execute(
                """
                SELECT count(*) AS count
                FROM research_runs.runs
                WHERE id = ANY(%s) AND result_manifest_sha256 IS NOT NULL
                """,
                ([item["research_run_id"] for item in admitted["items"]],),
            ).fetchone()
            task_attempt = transaction.execute(
                """
                SELECT status
                FROM research_batches.task_attempts
                WHERE batch_id = %s
                """,
                (admitted["id"],),
            ).fetchone()
        assert stale_results == {"count": 0}
        assert task_attempt == {"status": "cancelled"}


def test_cancellation_wins_before_final_batch_ack_and_preserves_completed_results(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("batch-cancel-final-ack-race"),
        ).json()
        runtime = client.app.state.core_runtime
        barrier = _TaskStartBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
            target_status="batch_succeeded",
        )
        processor = ResearchBatchService(
            runtime.database,
            research_runs=runtime.research_runs,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            publication=runtime.publication,
            attempt_control_directory=settings.batch_attempt_control_directory,
            execution=barrier,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(processor.process_next)
            assert barrier.created.wait(timeout=10)
            assert barrier.execution is not None
            assert barrier.execution.started.wait(timeout=20)
            response = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-before-final-batch-ack"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "cancelling"
            barrier.execution.release.set()
            assert future.result(timeout=20) is True

        detail = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert detail["status"] == "cancelled"
        assert detail["progress"] == {
            "completed_factor_tasks": 2,
            "total_factor_tasks": 2,
        }
        assert [item["outcome"] for item in detail["items"]] == [
            "succeeded",
            "succeeded",
        ]
        assert all(
            client.get(f"/api/research-runs/{item['research_run_id']}").json()["result"] is not None
            for item in detail["items"]
        )


def test_unresponsive_real_child_is_forced_out_before_terminal_cancel(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    worker = None
    child_pid = 0
    try:
        with TestClient(create_app(settings)) as client:
            _publish_current_data(settings)
            admitted = client.post(
                "/api/research-batches",
                json=_factor_command("batch-cancel-forced-child"),
            ).json()
            worker = _start_claim_barrier_worker(settings, "batch-research")
            claim = _wait_for_worker_event(worker, "worker_claim")
            with client.app.state.core_runtime.database.transaction() as transaction:
                attempt = transaction.execute(
                    """
                    SELECT child_pid
                    FROM research_batches.attempts
                    WHERE id = %s AND status = 'running'
                    """,
                    (claim["attempt_id"],),
                ).fetchone()
            assert attempt is not None
            child_pid = int(attempt["child_pid"])
            os.kill(child_pid, signal.SIGSTOP)
            response = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-forced-child"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "cancelling"

            started = monotonic()
            events = _release_claim_barrier_worker(worker)
            elapsed = monotonic() - started
            worker = None
            assert elapsed < 5
            assert any(
                event["event"] == "research_batch_execution_child_exited"
                and int(event["exit_code"]) in {-signal.SIGTERM, -signal.SIGKILL}
                for event in events
            )
            assert (
                client.get(f"/api/research-batches/{admitted['id']}").json()["status"]
                == "cancelled"
            )
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
    finally:
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if worker is not None:
            _terminate_worker(worker)


@pytest.mark.dependency_restart
def test_cancel_is_terminal_while_object_cleanup_retries_after_rustfs_restart(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    interrupted = False
    restarted_s3_port: int | None = None

    def interrupt_after_private_artifact(event: dict[str, object]) -> None:
        nonlocal interrupted
        if not interrupted and event.get("event") == "research_batch_execution_item_started":
            interrupted = True
            raise RuntimeError("injected Worker loss after private artifact acknowledgement")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_strategy_command("batch-cancel-rustfs-outage"),
        ).json()
        runtime = client.app.state.core_runtime
        assert (
            runtime.research_batches.process_next(
                on_execution_event=interrupt_after_private_artifact
            )
            is True
        )
        queued = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert queued["status"] == "queued"
        assert queued["progress"]["shared_alpha_factor_status"] == "succeeded"

        _run_dependency_command("stop-rustfs")
        try:
            cancelled = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-during-rustfs-outage"},
            )
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            with runtime.database.transaction() as transaction:
                assert transaction.execute(
                    "SELECT count(*) AS count FROM publication.object_deletions"
                ).fetchone() == {"count": 1}
            with pytest.raises(PublicationUnavailableError):
                runtime.publication.collect_one_pending_deletion()
            with runtime.database.transaction() as transaction:
                assert transaction.execute(
                    "SELECT count(*) AS count FROM publication.object_deletions"
                ).fetchone() == {"count": 1}
        finally:
            restarted_s3_port = _run_dependency_command("restart-rustfs")

    assert restarted_s3_port is not None
    restarted_settings = replace(
        settings,
        s3_endpoint_url=f"http://127.0.0.1:{restarted_s3_port}",
    )
    with TestClient(create_app(restarted_settings)) as restarted:
        assert (
            restarted.get(f"/api/research-batches/{admitted['id']}").json()["status"] == "cancelled"
        )
        runtime = restarted.app.state.core_runtime
        assert runtime.publication.collect_one_pending_deletion() is True
        with runtime.database.transaction() as transaction:
            assert transaction.execute(
                "SELECT count(*) AS count FROM publication.object_deletions"
            ).fetchone() == {"count": 0}


def test_cancel_converges_after_supervisor_loss_and_worker_restart(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    worker = None
    try:
        with TestClient(create_app(settings)) as client:
            _publish_current_data(settings)
            admitted = client.post(
                "/api/research-batches",
                json=_factor_command("batch-cancel-lost-supervisor"),
            ).json()
            worker = _start_claim_barrier_worker(settings, "batch-research")
            _wait_for_worker_event(worker, "worker_claim")
            response = client.post(
                f"/api/research-batches/{admitted['id']}/cancel",
                json={"request_id": "cancel-lost-supervisor"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "cancelling"
            _terminate_worker(worker)
            worker = None

            for _attempt in range(3):
                restarted = _run_worker_once(settings, "batch-research")
                assert restarted.returncode == 0, restarted.stderr
                if (
                    client.get(f"/api/research-batches/{admitted['id']}").json()["status"]
                    == "cancelled"
                ):
                    break
            else:
                raise AssertionError("Cancelled Batch did not converge after Worker restart")
            assert client.app.state.core_runtime.research_batches.process_next() is False
    finally:
        if worker is not None:
            _terminate_worker(worker)


@pytest.mark.database_restart
def test_cancel_check_fails_closed_during_postgres_outage_and_reconciles_after_restart(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    worker = None
    restarted_postgres_port: int | None = None
    admitted_id = ""
    try:
        with TestClient(create_app(settings)) as client:
            _publish_current_data(settings)
            admitted = client.post(
                "/api/research-batches",
                json=_factor_command("batch-cancel-postgres-outage"),
            ).json()
            admitted_id = str(admitted["id"])
            worker = _start_claim_barrier_worker(settings, "batch-research")
            _wait_for_worker_event(worker, "worker_claim")
            response = client.post(
                f"/api/research-batches/{admitted_id}/cancel",
                json={"request_id": "cancel-before-postgres-outage"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "cancelling"
            _run_dependency_command("stop-postgres")
            try:
                assert worker.stdin is not None
                worker.stdin.write("release\n")
                worker.stdin.flush()
                _wait_for_worker_stderr(worker, "error connecting")
                assert worker.poll() is None
                _terminate_worker(worker)
                worker = None
            finally:
                restarted_postgres_port = _run_dependency_command("restart-postgres")
    finally:
        if worker is not None:
            _terminate_worker(worker)

    assert restarted_postgres_port is not None
    restarted_settings = replace(
        settings,
        database_url=(
            "postgresql://thesistrace_owner:owner-test-password@127.0.0.1:"
            f"{restarted_postgres_port}/thesistrace"
        ),
    )
    with TestClient(create_app(restarted_settings)) as restarted:
        completed = _run_worker_once(restarted_settings, "batch-research")
        assert completed.returncode == 0, completed.stderr
        assert restarted.get(f"/api/research-batches/{admitted_id}").json()["status"] == (
            "cancelled"
        )
