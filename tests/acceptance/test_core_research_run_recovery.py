from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient
from fixture_release import publish_fixture_release

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_kernel.kernel_run import RunInput, RunOutput
from thesistrace.research_kernel.kernel_run import run as run_kernel
from thesistrace.research_run import ResearchRunService


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fresh_runtime_recovers_one_expired_running_run_without_new_identity() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as first_process:
        runtime = first_process.app.state.core_runtime
        run_id = _admit_run(first_process, request_id="ticket-22-restart")

        lost_worker = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            progress=lambda stage, _run_id: _lose_process(stage),
        )
        with pytest.raises(SystemExit, match="simulated worker loss"):
            lost_worker.process_next()
        assert first_process.get(f"/api/research-runs/{run_id}").json()[
            "status"
        ] == "running"
        _expire_live_attempt(runtime.database, run_id)

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        assert runtime.research_runs.process_next() is True

        detail = restarted_process.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == run_id
        assert detail.json()["status"] == "succeeded"
        assert set(detail.json()) == {
            "id",
            "status",
            "definition_id",
            "definition_revision",
            "dataset_release_id",
            "result",
        }
        assert _attempt_counts(runtime.database, run_id) == {
            "failed": 1,
            "succeeded": 1,
        }
        assert runtime.research_runs.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_two_workers_and_duplicate_delivery_publish_one_terminal_result() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    entered = Event()
    release = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-22-duplicate")

        def block_kernel(run_input: RunInput) -> RunOutput:
            entered.set()
            if not release.wait(timeout=30):
                raise TimeoutError("blocked Kernel was not released")
            return run_kernel(run_input)

        owner = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=block_kernel,
        )
        duplicate = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(owner.process_next)
            assert entered.wait(timeout=10)
            try:
                assert duplicate.process_next() is False
            finally:
                release.set()
            assert future.result(timeout=30) is True

        assert duplicate.process_next() is False
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded"
        assert _attempt_counts(runtime.database, run_id) == {"succeeded": 1}
        assert _research_result_manifest_count(runtime.database) == 1


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_live_worker_renews_its_lease_and_cannot_be_recovered() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    entered = Event()
    release = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-22-heartbeat")

        def block_kernel(run_input: RunInput) -> RunOutput:
            entered.set()
            if not release.wait(timeout=30):
                raise TimeoutError("live Kernel was not released")
            return run_kernel(run_input)

        owner = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=block_kernel,
            lease_seconds=1,
            heartbeat_seconds=0.05,
        )
        duplicate = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(owner.process_next)
            assert entered.wait(timeout=10)
            try:
                assert _wait_for_lease_renewal(runtime.database, run_id)
                assert duplicate.process_next() is False
            finally:
                release.set()
            assert future.result(timeout=30) is True

        assert client.get(f"/api/research-runs/{run_id}").json()[
            "status"
        ] == "succeeded"
        assert _attempt_counts(runtime.database, run_id) == {"succeeded": 1}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_recovered_winner_fences_a_stale_prepared_worker() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-22-stale")

        def pause_after_prepare(stage: str, current_run_id: str) -> None:
            if stage != "prepared":
                return
            _expire_live_attempt(runtime.database, current_run_id)
            prepared.set()
            if not release_stale.wait(timeout=30):
                raise TimeoutError("stale worker was not released")

        stale = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            progress=pause_after_prepare,
        )
        winner = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            stale_future = executor.submit(stale.process_next)
            assert prepared.wait(timeout=20)
            try:
                assert winner.process_next() is True
                winning_detail = client.get(f"/api/research-runs/{run_id}").json()
                assert winning_detail["status"] == "succeeded"
            finally:
                release_stale.set()
            assert stale_future.result(timeout=30) is True

        assert client.get(f"/api/research-runs/{run_id}").json() == winning_detail
        assert _attempt_counts(runtime.database, run_id) == {
            "failed": 1,
            "succeeded": 1,
        }
        assert _research_result_manifest_count(runtime.database) == 1
        product_text = str(winning_detail).lower().replace("_", " ").split()
        assert not {
            "attempt",
            "claim",
            "lease",
            "heartbeat",
            "fence",
            "recovery",
        }.intersection(product_text)


def _lose_process(stage: str) -> None:
    if stage == "claimed":
        raise SystemExit("simulated worker loss")


def _admit_run(client: TestClient, *, request_id: str) -> str:
    publish_fixture_release(client)
    accepted = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
            "name": "Recoverable ResearchRun",
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


def _expire_live_attempt(database: PostgresDatabase, run_id: str) -> None:
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


def _attempt_counts(database: PostgresDatabase, run_id: str) -> dict[str, int]:
    with database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT status, count(*) AS count
            FROM research_runs.attempts
            WHERE run_id = %s
            GROUP BY status
            """,
            (run_id,),
        ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _research_result_manifest_count(database: PostgresDatabase) -> int:
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


def _wait_for_lease_renewal(database: PostgresDatabase, run_id: str) -> bool:
    poll = Event()
    for _ in range(150):
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT heartbeat_at > started_at AS heartbeat_advanced,
                       now() > started_at + interval '1 second' AS initial_expired,
                       lease_expires_at > now() AS lease_live
                FROM research_runs.attempts
                WHERE run_id = %s AND status = 'running'
                """,
                (run_id,),
            ).fetchone()
        if row == {
            "heartbeat_advanced": True,
            "initial_expired": True,
            "lease_live": True,
        }:
            return True
        poll.wait(0.02)
    return False


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
