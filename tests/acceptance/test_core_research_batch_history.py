from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, isolated_core_settings
from fastapi.testclient import TestClient
from psycopg.errors import CheckViolation, ForeignKeyViolation
from psycopg.types.json import Jsonb
from test_core_research_batch_admission import (
    _factor_command,
    _publish_current_data,
    _strategy_command,
)

from thesistrace.data import DatasetLifecycle
from thesistrace.entrypoints.runtime import core_environment_is_configured
from thesistrace.research_batch import ResearchBatchService
from thesistrace.research_batch.execution import SupervisedResearchBatchExecutor


class _TaskStartBarrierExecution:
    def __init__(self, delegate, *, target_status: str) -> None:
        self._delegate = delegate
        self._target_status = target_status
        self.started = Event()
        self.release = Event()
        self._blocked = False

    @property
    def message(self):
        return self._delegate.message

    def advance(self, command: str) -> None:
        self._delegate.advance(command)
        if self.message.get("status") == self._target_status and not self._blocked:
            self._blocked = True
            self.started.set()
            if not self.release.wait(timeout=10):
                self._delegate.close()
                raise TimeoutError("Research Batch task-start barrier timed out")

    def acknowledge(self) -> None:
        self._delegate.acknowledge()

    def close(self) -> None:
        self._delegate.close()


class _TaskStartBarrierExecutor:
    def __init__(
        self,
        delegate: SupervisedResearchBatchExecutor,
        *,
        target_status: str,
    ) -> None:
        self._delegate = delegate
        self._target_status = target_status
        self.execution: _TaskStartBarrierExecution | None = None
        self.created = Event()

    def execute(self, request, *, emit, cancel_requested):
        self.execution = _TaskStartBarrierExecution(
            self._delegate.execute(request, emit=emit, cancel_requested=cancel_requested),
            target_status=self._target_status,
        )
        self.created.set()
        return self.execution


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_batch_history_schema_rejects_contradictory_attempts_and_item_outcomes(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        admitted = client.post(
            "/api/research-batches",
            json=_factor_command("batch-history-schema-invariants"),
        ).json()
        runtime = client.app.state.core_runtime
        invalid_attempts = (
            (
                "invalid_attempt_succeeded_without_finish",
                "succeeded",
                None,
                None,
                None,
            ),
            (
                "invalid_attempt_running_with_failure",
                "running",
                None,
                "InternalError",
                {"code": "X", "category": "execution", "message": "failed"},
            ),
            (
                "invalid_attempt_succeeded_with_failure",
                "succeeded",
                datetime.now(UTC),
                "InternalError",
                {"code": "X", "category": "execution", "message": "failed"},
            ),
        )
        for ordinal, invalid in enumerate(invalid_attempts, start=1):
            attempt_id, status, finished_expression, failure_reason, diagnostic = invalid
            with pytest.raises((CheckViolation, ForeignKeyViolation)):
                with runtime.database.transaction() as transaction:
                    transaction.execute(
                        """
                        INSERT INTO research_batches.attempts (
                            id, batch_id, ordinal, fence, generation_pin_id,
                            data_generation_id, data_through_session, status,
                            lease_expires_at, finished_at, failure_reason,
                            failure_diagnostic, child_pid, child_control_path,
                            child_started_at
                        ) VALUES (
                            %s, %s, %s, 1, %s, %s, %s, %s,
                            now() + interval '1 minute', %s, %s, %s,
                            1, '/tmp/.batch-attempts/invalid.lock', now()
                        )
                        """,
                        (
                            attempt_id,
                            admitted["id"],
                            ordinal,
                            f"invalid-pin-{ordinal}",
                            admitted["scope"]["data_generation_id"],
                            admitted["scope"]["data_through_session"],
                            status,
                            finished_expression,
                            failure_reason,
                            None if diagnostic is None else Jsonb(diagnostic),
                        ),
                    )

        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO research_batches.attempts (
                    id, batch_id, ordinal, fence, generation_pin_id,
                    data_generation_id, data_through_session, status,
                    lease_expires_at, child_pid, child_control_path,
                    child_started_at
                ) VALUES (
                    'task-schema-parent', %s, 10, 10, 'task-schema-pin',
                    %s, %s, 'running', now() + interval '1 minute',
                    1, '/tmp/.batch-attempts/task-schema-parent.lock', now()
                )
                """,
                (
                    admitted["id"],
                    admitted["scope"]["data_generation_id"],
                    admitted["scope"]["data_through_session"],
                ),
            )
        invalid_task_attempts = (
            (
                "task-succeeded-unfinished",
                1,
                "factor",
                1,
                10,
                "succeeded",
                False,
                None,
                None,
            ),
            (
                "task-failed-no-diagnostic",
                1,
                "factor",
                1,
                10,
                "failed",
                True,
                "Failure",
                None,
            ),
            ("task-over-retry-limit", 1, "factor", 4, 10, "running", False, None, None),
            (
                "task-shared-with-item",
                1,
                "shared_alpha_factor",
                1,
                10,
                "running",
                False,
                None,
                None,
            ),
            ("task-stale-fence", 1, "factor", 1, 11, "running", False, None, None),
        )
        for invalid in invalid_task_attempts:
            (
                task_id,
                item_ordinal,
                task_role,
                task_ordinal,
                fence,
                status,
                finished,
                failure_reason,
                diagnostic,
            ) = invalid
            with pytest.raises((CheckViolation, ForeignKeyViolation)):
                with runtime.database.transaction() as transaction:
                    transaction.execute(
                        """
                        INSERT INTO research_batches.task_attempts (
                            id, batch_id, item_ordinal, task_key, task_role,
                            ordinal, batch_attempt_id, fence, status,
                            finished_at, failure_reason, failure_diagnostic
                        ) VALUES (
                            %s, %s, %s, 'value', %s, %s,
                            'task-schema-parent', %s, %s,
                            CASE WHEN %s THEN now() END,
                            %s, %s
                        )
                        """,
                        (
                            task_id,
                            admitted["id"],
                            item_ordinal,
                            task_role,
                            task_ordinal,
                            fence,
                            status,
                            finished,
                            failure_reason,
                            None if diagnostic is None else Jsonb(diagnostic),
                        ),
                    )

        batch_id = admitted["id"]
        invalid_item_updates = (
            'SET diagnostic = \'{"code":"X","category":"execution","message":"failed"}\'',
            "SET outcome = 'succeeded', diagnostic = "
            '\'{"code":"X","category":"execution","message":"failed"}\'',
            "SET outcome = 'failed', diagnostic = NULL",
            "SET run_deleted_at = now()",
        )
        for update in invalid_item_updates:
            with pytest.raises(CheckViolation):
                with runtime.database.transaction() as transaction:
                    transaction.execute(
                        f"""
                        UPDATE research_batches.items
                        {update}
                        WHERE batch_id = %s AND ordinal = 1
                        """,
                        (batch_id,),
                    )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    ("batch_kind", "target_status", "task_role", "item_key"),
    [
        ("factor_evaluation", "item_started", "factor", "value"),
        (
            "strategy_sweep",
            "shared_alpha_factor_started",
            "shared_alpha_factor",
            None,
        ),
    ],
)
def test_batch_detail_separates_durable_and_live_progress_and_survives_restart(
    tmp_path: Path,
    batch_kind: str,
    target_status: str,
    task_role: str,
    item_key: str | None,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    request_id = f"batch-history-{batch_kind}"
    final_detail: dict[str, object]

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = (
            _factor_command(request_id)
            if batch_kind == "factor_evaluation"
            else _strategy_command(request_id)
        )
        admitted = client.post("/api/research-batches", json=command).json()
        runtime = client.app.state.core_runtime
        barrier = _TaskStartBarrierExecutor(
            SupervisedResearchBatchExecutor(
                settings.data_mount,
                attempt_control_directory=settings.batch_attempt_control_directory,
                execution_memory_bytes=settings.research_execution_memory_bytes,
            ),
            target_status=target_status,
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
            assert barrier.execution.started.wait(timeout=10)
            active = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert active["status"] == "running"
            assert active["attempt"]["number"] == 1
            assert active["attempt"]["status"] == "running"
            assert active["live_progress"] == {
                "attempt_number": 1,
                "task_role": task_role,
                "item_key": item_key,
                "phase": "research",
                "completed_research_sessions": 0,
                "total_research_sessions": active["live_progress"]["total_research_sessions"],
                "estimated_percentage": 0.0,
                "elapsed_seconds": active["live_progress"]["elapsed_seconds"],
                "remaining_duration_estimate_seconds": None,
                "is_estimate": True,
                "observed_at": active["live_progress"]["observed_at"],
            }
            assert active["live_progress"]["total_research_sessions"] > 0
            assert active["live_progress"]["elapsed_seconds"] >= 0
            durable_progress = active["progress"]
            with runtime.database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE research_batches.attempts
                    SET lease_expires_at = now() - interval '1 second'
                    WHERE id = %s
                    """,
                    (active["attempt"]["id"],),
                )
            expired = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert expired["attempt"]["status"] == "running"
            assert expired["progress"] == durable_progress
            assert expired["live_progress"] is None
            with runtime.database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE research_batches.attempts
                    SET lease_expires_at = now() + interval '5 minutes'
                    WHERE id = %s
                    """,
                    (active["attempt"]["id"],),
                )
            listed = client.get("/api/research-batches").json()["items"][0]
            assert listed["id"] == admitted["id"]
            assert "items" not in listed
            assert "attempt" not in listed
            assert "live_progress" not in listed
            barrier.execution.release.set()
            assert future.result(timeout=30) is True

        final_detail = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert final_detail["status"] == "succeeded"
        assert final_detail["live_progress"] is None
        assert final_detail["attempt"]["status"] == "succeeded"
        assert final_detail["attempt"]["finished_at"] is not None
        assert final_detail["execution_timing"]["is_final"] is True
        assert final_detail["execution_timing"]["finished_at"] is not None
        assert all(item["outcome"] == "succeeded" for item in final_detail["items"])

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-batches/{admitted['id']}").json() == final_detail


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_incomplete_factor_chunk_estimate_never_advances_durable_task_progress(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    sessions = _business_sessions(120, ending=date(2026, 8, 4))
    chunk_observed = Event()
    release = Event()

    def observe(event: dict[str, object]) -> None:
        if (
            event.get("event") == "research_batch_execution_item_chunk_succeeded"
            and int(event["completed_research_sessions"]) < int(event["total_research_sessions"])
            and not chunk_observed.is_set()
        ):
            chunk_observed.set()
            if not release.wait(timeout=10):
                raise TimeoutError("Research Batch live-progress barrier timed out")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(
            settings,
            operation_id="batch-history-multi-chunk",
            sessions=sessions,
            instrument_count=64,
        )
        command = _factor_command("batch-history-multi-chunk")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "start_date": sessions[20],
                "end_date": sessions[-1],
                "factors": [
                    {
                        "item_key": "multi-chunk",
                        "formula": " + ".join("ts_mean(close, 20)" for _ in range(4)),
                    }
                ],
            },
        ).json()
        runtime = client.app.state.core_runtime
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                runtime.research_batches.process_next,
                on_execution_event=observe,
            )
            assert chunk_observed.wait(timeout=20)
            active = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert active["progress"] == {
                "completed_factor_tasks": 0,
                "total_factor_tasks": 1,
            }
            live = active["live_progress"]
            assert live["item_key"] == "multi-chunk"
            assert live["phase"] == "research"
            assert 0 < live["completed_research_sessions"] < live["total_research_sessions"]
            assert 0 < live["estimated_percentage"] < 100
            assert live["remaining_duration_estimate_seconds"] >= 1
            assert live["is_estimate"] is True
            release.set()
            assert future.result(timeout=30) is True

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["progress"] == {
            "completed_factor_tasks": 1,
            "total_factor_tasks": 1,
        }
        assert completed["live_progress"] is None


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_reports_intermediate_shared_and_item_progress(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path)
    drop_product_schemas(settings)
    sessions = _business_sessions(120, ending=date(2026, 8, 4))
    shared_observed = Event()
    release_shared = Event()
    strategy_observed = Event()
    release_strategy = Event()

    def observe(event: dict[str, object]) -> None:
        completed = event.get("completed_research_sessions")
        total = event.get("total_research_sessions")
        if not isinstance(completed, int) or not isinstance(total, int) or completed >= total:
            return
        if (
            event.get("event") == "research_batch_execution_shared_alpha_factor_chunk_succeeded"
            and not shared_observed.is_set()
        ):
            shared_observed.set()
            if not release_shared.wait(timeout=10):
                raise TimeoutError("Shared Alpha-and-Factor progress barrier timed out")
        elif (
            event.get("event") == "research_batch_execution_item_strategy_chunk_succeeded"
            and not strategy_observed.is_set()
        ):
            strategy_observed.set()
            if not release_strategy.wait(timeout=10):
                raise TimeoutError("Strategy item progress barrier timed out")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(
            settings,
            operation_id="batch-history-strategy-multi-chunk",
            sessions=sessions,
            instrument_count=64,
        )
        command = _strategy_command("batch-history-strategy-multi-chunk")
        admitted = client.post(
            "/api/research-batches",
            json={
                **command,
                "start_date": sessions[20],
                "end_date": sessions[-1],
                "alpha": {
                    "formula": " + ".join("ts_mean(close, 20)" for _ in range(4)),
                    "hypothesis": "shared multi-chunk",
                },
                "strategies": command["strategies"][:1],
            },
        ).json()
        runtime = client.app.state.core_runtime
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                runtime.research_batches.process_next,
                on_execution_event=observe,
            )
            assert shared_observed.wait(timeout=20)
            shared_active = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert shared_active["progress"] == {
                "shared_alpha_factor_status": "running",
                "completed_strategy_tasks": 0,
                "total_strategy_tasks": 1,
            }
            shared_live = shared_active["live_progress"]
            assert shared_live["task_role"] == "shared_alpha_factor"
            assert shared_live["item_key"] is None
            assert (
                0
                < shared_live["completed_research_sessions"]
                < shared_live["total_research_sessions"]
            )
            assert shared_live["remaining_duration_estimate_seconds"] >= 1
            release_shared.set()

            assert strategy_observed.wait(timeout=20)
            strategy_active = client.get(f"/api/research-batches/{admitted['id']}").json()
            assert strategy_active["progress"] == {
                "shared_alpha_factor_status": "succeeded",
                "completed_strategy_tasks": 0,
                "total_strategy_tasks": 1,
            }
            strategy_live = strategy_active["live_progress"]
            assert strategy_live["task_role"] == "strategy"
            assert strategy_live["item_key"] == "focused"
            assert (
                0
                < strategy_live["completed_research_sessions"]
                < strategy_live["total_research_sessions"]
            )
            assert strategy_live["remaining_duration_estimate_seconds"] >= 1
            release_strategy.set()
            assert future.result(timeout=30) is True

        completed = client.get(f"/api/research-batches/{admitted['id']}").json()
        assert completed["status"] == "succeeded"
        assert completed["progress"] == {
            "shared_alpha_factor_status": "succeeded",
            "completed_strategy_tasks": 1,
            "total_strategy_tasks": 1,
        }
        assert completed["live_progress"] is None


def _business_sessions(count: int, *, ending: date) -> list[str]:
    sessions: list[date] = []
    current = ending
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current -= timedelta(days=1)
    return [value.isoformat() for value in reversed(sessions)]
