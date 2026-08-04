from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.definition import DefinitionRunCommand
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_valid_run_admission_is_atomic_immutable_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        runtime.data.update("ticket-19-release")
        assert runtime.data.process_next_update() is True
        first_release_id = client.get("/api/data").json()["latest_release"]["id"]
        runtime.data.update("ticket-19-later-release")
        assert runtime.data.process_next_update() is True
        release_id = client.get("/api/data").json()["latest_release"]["id"]
        assert release_id != first_release_id

        command = _valid_command("ticket-19-first", name="First immutable run")
        accepted = client.post("/api/definitions/run", json=command)

        assert accepted.status_code == 200
        outcome = accepted.json()
        assert outcome["outcome"] == "accepted"
        assert outcome["issues"] == []
        assert outcome["definition"]["revision"] == 1
        assert outcome["definition"]["hypothesis"] is None
        run = outcome["run"]
        assert run == {
            "id": run["id"],
            "status": "queued",
            "definition_id": outcome["definition"]["id"],
            "definition_revision": 1,
            "dataset_release_id": release_id,
        }

        stored = _stored_run(settings, run["id"])
        assert stored["status"] == "queued"
        assert stored["immutable_input"] == {
            "definition": {
                "id": outcome["definition"]["id"],
                "revision": 1,
                "content": {
                    "name": "First immutable run",
                    "hypothesis": None,
                    "alpha": command["alpha"],
                    "universe": "top1000",
                    "neutralization": "industry",
                    "holdings_count": 30,
                    "rebalance_every_sessions": 5,
                },
            },
            "dataset_release_id": release_id,
            "field_bindings": {
                "market.turnover.cny": "turnover_amount_cny",
                "market.volume.shares": "volume_shares",
                "price.close.adjusted": "close_adj",
                "price.high.adjusted": "high_adj",
                "price.low.adjusted": "low_adj",
                "price.open.adjusted": "open_adj",
            },
            "strategy": {
                "kind": "long_only_top_n_equal_weight",
                "holdings_count": 30,
                "rebalance_every_sessions": 5,
                "initial_cash_cny": "10000000",
                "execution": "next_open_full_fill",
            },
            "costs": {
                "commission_rate_all_in": "0.0003",
                "commission_min_cny": "5",
                "stamp_duty_sell_rate": "0.0005",
                "transfer_fee_rate": "0.00001",
            },
            "risk_free_rate": "0",
            "numeric_execution_contract": "thesistrace-numeric-v1",
            "semantic_versions": {
                "alpha": "alpha-v1",
                "factor": "factor-v1",
                "strategy": "strategy-v1",
                "kernel": "kernel-v1",
                "operator_catalog": "1.0.0",
            },
        }
        assert "snapshot" not in str(stored).lower()

        replay = client.post("/api/definitions/run", json=command)
        assert replay.status_code == 200
        assert replay.json() == outcome
        assert _counts(settings) == {"definitions": 1, "receipts": 1, "runs": 1}

        conflict = client.post(
            "/api/definitions/run",
            json={**command, "name": "Conflicting reuse"},
        )
        assert conflict.status_code == 409
        assert _counts(settings) == {"definitions": 1, "receipts": 1, "runs": 1}

        second = client.post(
            f"/api/definitions/{outcome['definition']['id']}/run",
            json=_valid_command(
                "ticket-19-edited",
                expected_revision=1,
                name="Edited second run",
                holdings_count=40,
            ),
        )
        assert second.status_code == 200
        second_outcome = second.json()
        assert second_outcome["outcome"] == "accepted"
        assert second_outcome["definition"]["revision"] == 2
        assert second_outcome["run"]["id"] != run["id"]
        assert _stored_run(settings, run["id"])["immutable_input"] == stored[
            "immutable_input"
        ]
        assert _stored_run(settings, second_outcome["run"]["id"])["immutable_input"][
            "strategy"
        ]["holdings_count"] == 40

        original_admit: Callable[..., object] = runtime.definitions._admit_run

        def fail_admission(
            transaction: PostgresTransaction,
            immutable_input: object,
        ) -> object:
            original_admit(transaction, immutable_input)
            raise RuntimeError("forced ResearchRun admission failure")

        monkeypatch.setattr(runtime.definitions, "_admit_run", fail_admission)
        before_failure = _counts(settings)
        with pytest.raises(RuntimeError, match="forced ResearchRun admission failure"):
            runtime.definitions.run(
                None,
                DefinitionRunCommand.model_validate(
                    _valid_command("ticket-19-rollback", name="Must roll back")
                ),
            )
        assert _counts(settings) == before_failure
        monkeypatch.setattr(runtime.definitions, "_admit_run", original_admit)

        detail = client.get(f"/api/research-runs/{run['id']}")
        assert detail.status_code == 200
        assert detail.json() == run
        listing = client.get("/api/research-runs").json()
        assert {item["id"] for item in listing["items"]} == {
            run["id"],
            second_outcome["run"]["id"],
        }
        assert client.post("/api/research-runs", json={}).status_code in {404, 405}
        assert client.put(f"/api/research-runs/{run['id']}", json={}).status_code in {
            404,
            405,
        }
        assert client.delete(f"/api/research-runs/{run['id']}").status_code in {
            404,
            405,
        }
        assert client.get("/api/snapshots").status_code == 404
        assert client.get("/api/definition-snapshots").status_code == 404


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_run_rejects_an_alpha_field_absent_from_the_latest_release() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        runtime.data.update("ticket-19-field-release")
        assert runtime.data.process_next_update() is True
        release_id = client.get("/api/data").json()["latest_release"]["id"]
        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                DELETE FROM data.release_fields
                WHERE release_id = %s AND field_id = 'price.close.adjusted'
                """,
                (release_id,),
            )

        rejected = client.post(
            "/api/definitions/run",
            json=_valid_command("ticket-19-missing-field", name="Unavailable field"),
        )

        assert rejected.status_code == 200
        assert rejected.json()["outcome"] == "rejected"
        assert rejected.json()["issues"] == [
            {
                "code": "FIELD_UNAVAILABLE_IN_RELEASE",
                "field": "alpha",
                "message": "Alpha field is unavailable in the latest Dataset Release",
            }
        ]
        assert _counts(settings) == {"definitions": 1, "receipts": 1, "runs": 0}


def _valid_command(
    request_id: str,
    *,
    expected_revision: int | None = None,
    name: str,
    holdings_count: int = 30,
) -> dict[str, object]:
    command: dict[str, object] = {
        "request_id": request_id,
        "name": name,
        "alpha": {
            "operator_id": "ts_mean",
            "operands": [
                {"field_id": "price.close.adjusted"},
                {"literal": 20},
            ],
        },
        "universe": "top1000",
        "neutralization": "industry",
        "holdings_count": holdings_count,
        "rebalance_every_sessions": 5,
    }
    if expected_revision is not None:
        command["expected_revision"] = expected_revision
    return command


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


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, status, immutable_input
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
    finally:
        database.close()
    assert row is not None
    return row


def _counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM definitions.records) AS definitions,
                    (SELECT count(*) FROM definitions.run_receipts) AS receipts,
                    (SELECT count(*) FROM research_runs.runs) AS runs
                """
            ).fetchone()
    finally:
        database.close()
    assert row is not None
    return {name: int(row[name]) for name in ("definitions", "receipts", "runs")}
