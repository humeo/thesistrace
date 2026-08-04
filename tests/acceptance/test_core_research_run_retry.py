from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublicationVerificationError
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
@pytest.mark.parametrize("terminal_status", ["succeeded", "failed", "cancelled"])
def test_terminal_state_is_not_claimed_or_overwritten(terminal_status: str) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run_id = _admit_run(client, request_id=f"ticket-23-{terminal_status}")
        _set_terminal_state(runtime.database, run_id, terminal_status)

        assert runtime.research_runs.process_next() is False
        listed = client.get("/api/research-runs").json()["items"]
        summary = next(item for item in listed if item["id"] == run_id)
        assert summary["status"] == terminal_status
        assert _attempt_statuses(runtime.database, run_id) == []


def _unavailable_data(_release_id: str) -> dict[str, object]:
    raise PublicationVerificationError(
        "secret-object-store-endpoint refused the canonical payload"
    )


def _invalid_calculation(_run_input: RunInput) -> RunOutput:
    raise ValueError("secret-alpha-value is invalid")


def _resource_exhausted(_run_input: RunInput) -> RunOutput:
    raise MemoryError("secret-resource-pressure-detail")


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


def _set_terminal_state(
    database: PostgresDatabase,
    run_id: str,
    terminal_status: str,
) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            "UPDATE research_runs.runs SET status = %s WHERE id = %s",
            (terminal_status, run_id),
        )


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
