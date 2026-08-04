from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import (
    PublicationPreparationError,
    PublicationUnavailableError,
    PublicationVerificationError,
)
from thesistrace.research_kernel.kernel_run import RunInput, RunOutput
from thesistrace.research_run import ResearchRunService


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_transient_infrastructure_retry_survives_restart_under_one_run() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as first_process:
        runtime = first_process.app.state.core_runtime
        run_id = _admit_run(first_process, request_id="ticket-23-restart")
        unavailable = ResearchRunService(
            runtime.database,
            load_canonical=_unavailable_data,
            publication=runtime.publication,
        )

        assert unavailable.process_next() is True
        retrying = first_process.get(f"/api/research-runs/{run_id}").json()
        assert retrying == {
            "id": run_id,
            "status": "running",
            "definition_id": retrying["definition_id"],
            "definition_revision": 1,
            "dataset_release_id": retrying["dataset_release_id"],
        }
        assert _attempt_statuses(runtime.database, run_id) == ["failed"]

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        assert runtime.research_runs.process_next() is True
        succeeded = restarted_process.get(f"/api/research-runs/{run_id}").json()
        assert succeeded["id"] == run_id
        assert succeeded["status"] == "succeeded"
        assert "result" in succeeded
        assert "failure_reason" not in succeeded
        assert _attempt_statuses(runtime.database, run_id) == [
            "failed",
            "succeeded",
        ]
        assert runtime.research_runs.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_transient_retry_exhaustion_is_bounded_and_sanitized() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-23-exhaustion")
        unavailable = ResearchRunService(
            runtime.database,
            load_canonical=_unavailable_data,
            publication=runtime.publication,
        )

        for attempt_number in range(1, 4):
            assert unavailable.process_next() is True
            detail = client.get(f"/api/research-runs/{run_id}").json()
            if attempt_number < 3:
                assert detail["status"] == "running"
                assert "failure_reason" not in detail
            else:
                assert detail["status"] == "failed"
                assert detail["failure_reason"] == (
                    "Research execution could not access required infrastructure."
                )
                assert "result" not in detail
            assert "secret-object-store-endpoint" not in str(detail)

        assert _attempt_statuses(runtime.database, run_id) == [
            "failed",
            "failed",
            "failed",
        ]
        assert unavailable.process_next() is False

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        detail = restarted_process.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "failed"
        assert detail["failure_reason"] == (
            "Research execution could not access required infrastructure."
        )
        assert runtime.research_runs.process_next() is False
        assert _attempt_statuses(runtime.database, run_id) == [
            "failed",
            "failed",
            "failed",
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_permanent_failure_is_terminal_without_automatic_retry() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-23-permanent")
        broken_kernel = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=_invalid_calculation,
        )

        assert broken_kernel.process_next() is True
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == "Research execution failed."
        assert "secret-alpha-value" not in str(failed)
        assert _attempt_statuses(runtime.database, run_id) == ["failed"]
        assert broken_kernel.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "error_type",
    [PublicationPreparationError, PublicationVerificationError, PermissionError],
)
def test_deterministic_publication_and_permission_errors_do_not_retry(
    error_type: type[Exception],
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(
            client,
            request_id=f"ticket-23-{error_type.__name__.lower()}",
        )

        def deterministic_failure(_release_id: str) -> dict[str, object]:
            raise error_type("secret-deterministic-publication-detail")

        broken = ResearchRunService(
            runtime.database,
            load_canonical=deterministic_failure,
            publication=runtime.publication,
        )

        assert broken.process_next() is True
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == "Research execution failed."
        assert "secret-deterministic-publication-detail" not in str(failed)
        assert _attempt_statuses(runtime.database, run_id) == ["failed"]
        assert broken.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_resource_exhaustion_allows_at_most_one_more_attempt() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-23-resource")
        exhausted = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=_resource_exhausted,
        )

        assert exhausted.process_next() is True
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
        assert exhausted.process_next() is True
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == (
            "Research execution exceeded its resource limit."
        )
        assert _attempt_statuses(runtime.database, run_id) == ["failed", "failed"]
        assert exhausted.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_resource_limit_survives_a_different_second_failure() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-23-resource-mixed")
        exhausted = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=_resource_exhausted,
        )
        unavailable = ResearchRunService(
            runtime.database,
            load_canonical=_unavailable_data,
            publication=runtime.publication,
        )

        assert exhausted.process_next() is True
        assert client.get(f"/api/research-runs/{run_id}").json()["status"] == "running"
        assert unavailable.process_next() is True
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == (
            "Research execution exceeded its resource limit."
        )
        assert _attempt_statuses(runtime.database, run_id) == ["failed", "failed"]
        assert unavailable.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_resource_limit_survives_worker_loss_on_the_second_attempt() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id="ticket-23-resource-worker-loss")
        exhausted = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            execute_kernel=_resource_exhausted,
        )
        lost_worker = ResearchRunService(
            runtime.database,
            load_canonical=runtime.data.load_canonical,
            publication=runtime.publication,
            progress=lambda stage, _run_id: _lose_process(stage),
        )

        assert exhausted.process_next() is True
        with pytest.raises(SystemExit, match="simulated worker loss"):
            lost_worker.process_next()
        _expire_live_attempt(runtime.database, run_id)

        assert runtime.research_runs.process_next() is False
        failed = client.get(f"/api/research-runs/{run_id}").json()
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == (
            "Research execution exceeded its resource limit."
        )
        assert _attempt_statuses(runtime.database, run_id) == ["failed", "failed"]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize("terminal_status", ["succeeded", "failed", "cancelled"])
def test_stale_attempt_cannot_overwrite_a_terminal_state(terminal_status: str) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id=f"ticket-23-{terminal_status}")

        def pause_after_prepare(stage: str, _current_run_id: str) -> None:
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
            stale_future = executor.submit(stale.process_next)
            assert prepared.wait(timeout=20)
            try:
                if terminal_status == "succeeded":
                    _expire_live_attempt(runtime.database, run_id)
                    assert runtime.research_runs.process_next() is True
                else:
                    _commit_terminal_and_fence(
                        runtime.database,
                        run_id,
                        terminal_status,
                    )
                winning_summary = _listed_summary(client, run_id)
                assert winning_summary["status"] == terminal_status
            finally:
                release_stale.set()
            assert stale_future.result(timeout=30) is True

        assert _listed_summary(client, run_id) == winning_summary
        assert runtime.research_runs.process_next() is False
        if terminal_status == "succeeded":
            assert _attempt_statuses(runtime.database, run_id) == [
                "failed",
                "succeeded",
            ]
            assert _research_result_manifest_count(runtime.database) == 1
        else:
            assert _attempt_statuses(runtime.database, run_id) == [terminal_status]
            assert _research_result_manifest_count(runtime.database) == 0


def _unavailable_data(_release_id: str) -> dict[str, object]:
    raise PublicationUnavailableError(
        "secret-object-store-endpoint refused the canonical payload"
    )


def _invalid_calculation(_run_input: RunInput) -> RunOutput:
    raise ValueError("secret-alpha-value is invalid")


def _resource_exhausted(_run_input: RunInput) -> RunOutput:
    raise MemoryError("secret-resource-pressure-detail")


def _lose_process(stage: str) -> None:
    if stage == "claimed":
        raise SystemExit("simulated worker loss")


def _admit_run(client: TestClient, *, request_id: str) -> str:
    runtime = client.app.state.core_runtime
    runtime.data.update(f"{request_id}-release")
    assert runtime.data.process_next_update() is True
    accepted = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
            "name": "Bounded retry ResearchRun",
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


def _attempt_statuses(database: PostgresDatabase, run_id: str) -> list[str]:
    with database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT status
            FROM research_runs.attempts
            WHERE run_id = %s
            ORDER BY ordinal
            """,
            (run_id,),
        ).fetchall()
    return [str(row["status"]) for row in rows]


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


def _commit_terminal_and_fence(
    database: PostgresDatabase,
    run_id: str,
    terminal_status: str,
) -> None:
    attempt_status = "cancelled" if terminal_status == "cancelled" else "failed"
    with database.transaction() as transaction:
        attempt = transaction.execute(
            """
            UPDATE research_runs.attempts
            SET status = %s, lease_expires_at = now(), finished_at = now(),
                failure_reason = %s
            WHERE run_id = %s AND status = 'running'
            """,
            (attempt_status, "TerminalFenceTest", run_id),
        )
        run = transaction.execute(
            """
            UPDATE research_runs.runs
            SET status = %s, execution_fence = execution_fence + 1,
                failure_reason = %s, updated_at = now()
            WHERE id = %s AND status = 'running'
            """,
            (
                terminal_status,
                "Research execution failed." if terminal_status == "failed" else None,
                run_id,
            ),
        )
    assert attempt.rowcount == 1
    assert run.rowcount == 1


def _listed_summary(client: TestClient, run_id: str) -> dict[str, object]:
    listed = client.get("/api/research-runs").json()["items"]
    return next(item for item in listed if item["id"] == run_id)


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
