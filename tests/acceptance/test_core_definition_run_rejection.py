from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_rejected_run_saves_once_and_replays_without_a_research_run(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    _drop_definitions_schema(settings)

    with TestClient(create_app(settings)) as client:
        malformed = client.post(
            "/api/definitions/run",
            json={"request_id": "malformed-run", "alpha": []},
        )
        assert malformed.status_code == 422
        assert _durable_counts(settings) == {
            "definitions": 0,
            "run_receipts": 0,
            "research_runs": 0,
        }

        command = {"request_id": "rejected-new-run", "name": "Needs Alpha"}
        rejected = client.post("/api/definitions/run", json=command)

        assert rejected.status_code == 200
        outcome = rejected.json()
        assert outcome["outcome"] == "rejected"
        assert outcome["definition"]["revision"] == 1
        assert outcome["definition"]["name"] == "Needs Alpha"
        assert outcome["definition"]["hypothesis"] is None
        assert {issue["field"] for issue in outcome["issues"]} == {
            "start_date",
            "end_date",
            "alpha",
            "universe",
            "neutralization",
            "holdings_count",
            "rebalance_every_sessions",
        }
        assert "hypothesis" not in {issue["field"] for issue in outcome["issues"]}
        assert _durable_counts(settings) == {
            "definitions": 1,
            "run_receipts": 1,
            "research_runs": 0,
        }

        replay = client.post("/api/definitions/run", json=command)
        assert replay.status_code == 200
        assert replay.json() == outcome
        assert _durable_counts(settings)["definitions"] == 1
        assert _durable_counts(settings)["run_receipts"] == 1

        conflict = client.post(
            "/api/definitions/run",
            json={**command, "name": "Different fingerprint"},
        )
        assert conflict.status_code == 409
        assert _durable_counts(settings)["definitions"] == 1
        assert _durable_counts(settings)["run_receipts"] == 1

        definition_id = outcome["definition"]["id"]
        second = client.post(
            f"/api/definitions/{definition_id}/run",
            json={
                "request_id": "rejected-existing-run",
                "expected_revision": 1,
                "name": "Still needs Alpha",
            },
        )
        assert second.status_code == 200
        assert second.json()["definition"]["revision"] == 2
        assert second.json()["definition"]["name"] == "Still needs Alpha"
        assert _durable_counts(settings)["definitions"] == 1
        assert _durable_counts(settings)["run_receipts"] == 2

        malformed_existing = client.post(
            f"/api/definitions/{definition_id}/run",
            json={
                "request_id": "malformed-existing-run",
                "expected_revision": 2,
                "alpha": {"operator_id": "ts_mean", "operands": []},
            },
        )
        assert malformed_existing.status_code == 422
        assert client.get(f"/api/definitions/{definition_id}").json() == second.json()[
            "definition"
        ]
        assert _durable_counts(settings)["run_receipts"] == 2

        complete_without_hypothesis = {
            "request_id": "only-data-is-missing",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
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
        }
        data_rejected = client.post(
            "/api/definitions/run",
            json=complete_without_hypothesis,
        )
        assert data_rejected.status_code == 200
        assert data_rejected.json()["issues"] == [
            {
                "code": "DATA_NOT_READY",
                "field": "data",
                "message": "Current Dataset is not ready",
            }
        ]
        assert data_rejected.json()["definition"]["hypothesis"] is None

        replay_after_data_check = client.post(
            "/api/definitions/run",
            json=complete_without_hypothesis,
        )
        assert replay_after_data_check.json() == data_rejected.json()
        assert client.post("/api/definitions/run", json=command).json() == outcome


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_concurrent_request_ids_serialize_without_pool_reentry(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    _drop_definitions_schema(settings)

    with TestClient(create_app(settings)) as client_a, TestClient(create_app(settings)) as client_b:
        matching = {"request_id": "concurrent-matching", "name": "Matching"}
        start = Barrier(3)

        def submit(client: TestClient, command: dict[str, object]):
            start.wait(timeout=10)
            return client.post("/api/definitions/run", json=command)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(submit, client_a, matching),
                executor.submit(submit, client_b, matching),
            )
            start.wait(timeout=10)
            matching_responses = [future.result(timeout=10) for future in futures]
        assert [response.status_code for response in matching_responses] == [200, 200]
        assert matching_responses[0].json() == matching_responses[1].json()
        assert _durable_counts(settings)["definitions"] == 1
        assert _durable_counts(settings)["run_receipts"] == 1

        conflicting = Barrier(3)

        def conflict(client: TestClient, name: str):
            conflicting.wait(timeout=10)
            return client.post(
                "/api/definitions/run",
                json={"request_id": "concurrent-conflict", "name": name},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(conflict, client_a, "Conflict A"),
                executor.submit(conflict, client_b, "Conflict B"),
            )
            conflicting.wait(timeout=10)
            conflict_responses = [future.result(timeout=10) for future in futures]
        assert sorted(response.status_code for response in conflict_responses) == [200, 409]
        assert _durable_counts(settings)["definitions"] == 2
        assert _durable_counts(settings)["run_receipts"] == 2

    with TestClient(create_app(settings)) as shared_client:
        pool_start = Barrier(5)

        def unique(index: int):
            pool_start.wait(timeout=10)
            return shared_client.post(
                "/api/definitions/run",
                json={"request_id": f"pool-run-{index}", "name": f"Pool {index}"},
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(unique, index) for index in range(4)]
            pool_start.wait(timeout=10)
            responses = [future.result(timeout=10) for future in futures]
        assert [response.status_code for response in responses] == [200, 200, 200, 200]


def _drop_definitions_schema(settings: CoreSettings) -> None:
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


def _durable_counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM definitions.records) AS definitions,
                    (SELECT count(*) FROM definitions.run_receipts) AS run_receipts,
                    (SELECT count(*) FROM research_runs.runs) AS research_runs
                """
            ).fetchone()
    finally:
        database.close()
    assert row is not None
    return {
        "definitions": int(row["definitions"]),
        "run_receipts": int(row["run_receipts"]),
        "research_runs": int(row["research_runs"]),
    }
