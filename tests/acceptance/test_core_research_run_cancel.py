from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_kernel.kernel_run import RunInput, RunOutput
from thesistrace.research_kernel.kernel_run import run as run_kernel
from thesistrace.research_run import ResearchRunService


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_queued_cancel_replays_and_conflicts_without_malformed_receipt() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-24-queued")
        second_id = _admit_run(client, request_id="ticket-24-conflict-target")

        cancelled = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "ticket-24-cancel"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["id"] == run_id
        assert cancelled.json()["status"] == "cancelled"
        assert _run_storage(runtime.database, run_id) == {
            "status": "cancelled",
            "execution_fence": 1,
            "attempt_count": 0,
            "result_count": 0,
        }

        replay = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "ticket-24-cancel"},
        )
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert _cancel_receipt_count(runtime.database) == 1

        conflict = client.post(
            f"/api/research-runs/{second_id}/cancel",
            json={"request_id": "ticket-24-cancel"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "ResearchRun Cancel request_id conflicts"

        malformed = client.post(
            f"/api/research-runs/{second_id}/cancel",
            json={"unexpected": "field"},
        )
        assert malformed.status_code == 422
        assert _cancel_receipt_count(runtime.database) == 1
        assert _run_storage(runtime.database, second_id)["status"] == "queued"

        missing = client.post(
            "/api/research-runs/run_00000000/cancel",
            json={"request_id": "ticket-24-missing"},
        )
        assert missing.status_code == 404
        assert _cancel_receipt_count(runtime.database) == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_running_cancel_fences_a_stale_prepared_worker_and_survives_restart() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-24-running")

        def pause_after_prepare(stage: str, _run_id: str) -> None:
            if stage != "prepared":
                return
            prepared.set()
            if not release_stale.wait(timeout=30):
                raise TimeoutError("stale worker was not released")

        stale = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            progress=pause_after_prepare,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale.process_next)
            assert prepared.wait(timeout=20)
            try:
                cancelled = client.post(
                    f"/api/research-runs/{run_id}/cancel",
                    json={"request_id": "ticket-24-running-cancel"},
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelled"
                assert _run_storage(runtime.database, run_id) == {
                    "status": "cancelled",
                    "execution_fence": 2,
                    "attempt_count": 1,
                    "result_count": 0,
                }
            finally:
                release_stale.set()
            assert future.result(timeout=30) is True

        assert client.get(f"/api/research-runs/{run_id}").json() == cancelled.json()
        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert runtime.research_runs.process_next() is False

    with TestClient(create_app(settings)) as restarted:
        replay = restarted.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": "ticket-24-running-cancel"},
        )
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert restarted.app.state.core_runtime.research_runs.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_running_cancel_fences_a_late_failure_write() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    entered = Event()
    release_failure = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-24-late-failure")

        def delayed_failure(_run_input: RunInput) -> RunOutput:
            entered.set()
            if not release_failure.wait(timeout=30):
                raise TimeoutError("late failure was not released")
            raise ValueError("secret-late-failure-detail")

        stale = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=delayed_failure,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale.process_next)
            assert entered.wait(timeout=20)
            try:
                cancelled = client.post(
                    f"/api/research-runs/{run_id}/cancel",
                    json={"request_id": "ticket-24-late-failure-cancel"},
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelled"
            finally:
                release_failure.set()
            assert future.result(timeout=30) is True

        assert client.get(f"/api/research-runs/{run_id}").json() == cancelled.json()
        assert _attempt_status(runtime.database, run_id) == "cancelled"
        assert _run_storage(runtime.database, run_id)["result_count"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("terminal_status", ["succeeded", "failed"])
def test_terminal_winner_is_returned_without_overwrite(terminal_status: str) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id=f"ticket-24-{terminal_status}")
        service = runtime.research_runs
        if terminal_status == "failed":
            service = ResearchRunService(
                runtime.database,
                load_canonical=runtime.data.load_canonical,
                publication=runtime.publication,
                execute_kernel=_permanent_failure,
            )
        assert service.process_next() is True
        before = client.get(f"/api/research-runs/{run_id}").json()
        assert before["status"] == terminal_status

        outcome = client.post(
            f"/api/research-runs/{run_id}/cancel",
            json={"request_id": f"ticket-24-after-{terminal_status}"},
        )
        assert outcome.status_code == 200
        assert outcome.json()["id"] == run_id
        assert outcome.json()["status"] == terminal_status
        assert client.get(f"/api/research-runs/{run_id}").json() == before


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("worker_outcome", ["success", "failure"])
def test_cancel_races_a_terminal_worker_commit(worker_outcome: str) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    ready = Event()
    release_worker = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id=f"ticket-24-race-{worker_outcome}")

        def pause_success(stage: str, _run_id: str) -> None:
            if stage != "prepared":
                return
            ready.set()
            if not release_worker.wait(timeout=30):
                raise TimeoutError("success race was not released")

        def pause_failure(_run_input: RunInput) -> RunOutput:
            ready.set()
            if not release_worker.wait(timeout=30):
                raise TimeoutError("failure race was not released")
            raise ValueError("secret-raced-failure")

        worker = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=(
                pause_failure
                if worker_outcome == "failure"
                else run_kernel
            ),
            progress=pause_success if worker_outcome == "success" else None,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            worker_future = executor.submit(worker.process_next)
            assert ready.wait(timeout=20)
            cancel_future = executor.submit(
                client.post,
                f"/api/research-runs/{run_id}/cancel",
                json={"request_id": f"ticket-24-race-cancel-{worker_outcome}"},
            )
            release_worker.set()
            cancel_response = cancel_future.result(timeout=30)
            assert worker_future.result(timeout=30) is True

        assert cancel_response.status_code == 200
        final = client.get(f"/api/research-runs/{run_id}").json()
        assert cancel_response.json()["status"] == final["status"]
        assert final["status"] in {"cancelled", "succeeded", "failed"}
        expected_results = 1 if final["status"] == "succeeded" else 0
        assert _run_storage(runtime.database, run_id)["result_count"] == expected_results


def _permanent_failure(_run_input: RunInput) -> RunOutput:
    raise ValueError("secret-terminal-race-detail")


def _admit_run(client: TestClient, *, request_id: str) -> str:
    runtime = client.app.state.core_runtime
    if runtime.data.overview().latest_release is None:
        runtime.data.update(f"{request_id}-release")
        assert runtime.data.process_next_update() is True
    accepted = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
            "name": "Cancellable ResearchRun",
            "alpha": {
                "operator_id": "ts_mean",
                "operands": [
                    {"field_id": "price.close.adjusted"},
                    {"literal": 20},
                ],
            },
            "universe": "top1000",
            "neutralization": "industry",
            "holdings_count": 30,
            "rebalance_every_sessions": 5,
        },
    )
    assert accepted.status_code == 200
    return str(accepted.json()["run"]["id"])


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


def _drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS research_runs CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()
