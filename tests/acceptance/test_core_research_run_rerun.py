from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication.serialization import canonical_json_bytes


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_rerun_uses_the_selected_runs_exact_immutable_input() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        runtime.data.update("ticket-25-original-release")
        assert runtime.data.process_next_update() is True
        original_release_id = client.get("/api/data").json()["latest_release"]["id"]

        admitted = client.post(
            "/api/definitions/run",
            json=_valid_command("ticket-25-original-run", holdings_count=30),
        )
        assert admitted.status_code == 200
        original = admitted.json()["run"]
        assert original["dataset_release_id"] == original_release_id
        assert runtime.research_runs.process_next() is True
        original_before = client.get(f"/api/research-runs/{original['id']}").json()
        assert original_before["status"] == "succeeded"
        stored_original = _stored_run(settings, original["id"])

        edited = client.put(
            f"/api/definitions/{original['definition_id']}",
            json={
                "expected_revision": original["definition_revision"],
                "name": "Edited after the selected Run",
                "holdings_count": 40,
            },
        )
        assert edited.status_code == 200
        assert edited.json()["revision"] == original["definition_revision"] + 1
        assert edited.json()["holdings_count"] == 40

        runtime.data.update("ticket-25-newer-release")
        assert runtime.data.process_next_update() is True
        latest_release_id = client.get("/api/data").json()["latest_release"]["id"]
        assert latest_release_id != original_release_id

        rerun_command = {"request_id": "ticket-25-rerun"}
        accepted = client.post(
            f"/api/research-runs/{original['id']}/rerun",
            json=rerun_command,
        )

        assert accepted.status_code == 202
        rerun = accepted.json()
        assert rerun == {
            "id": rerun["id"],
            "status": "queued",
            "definition_id": original["definition_id"],
            "definition_revision": original["definition_revision"],
            "dataset_release_id": original_release_id,
            "rerun_of_id": original["id"],
        }
        assert rerun["id"] != original["id"]
        stored_rerun = _stored_run(settings, rerun["id"])
        assert stored_rerun["immutable_input"] == stored_original["immutable_input"]
        assert canonical_json_bytes(stored_rerun["immutable_input"]) == canonical_json_bytes(
            stored_original["immutable_input"]
        )
        assert stored_rerun["dataset_release_id"] == original_release_id
        assert stored_rerun["rerun_of_id"] == original["id"]
        assert client.get(f"/api/research-runs/{original['id']}").json() == original_before

        replay = client.post(
            f"/api/research-runs/{original['id']}/rerun",
            json=rerun_command,
        )
        assert replay.status_code == 202
        assert replay.json() == rerun
        assert _counts(settings) == {"runs": 2, "rerun_receipts": 1}

        conflict = client.post(
            f"/api/research-runs/{rerun['id']}/rerun",
            json=rerun_command,
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "ResearchRun Rerun request_id conflicts"
        assert _counts(settings) == {"runs": 2, "rerun_receipts": 1}

        missing = client.post(
            "/api/research-runs/run_00000000/rerun",
            json={"request_id": "ticket-25-missing"},
        )
        assert missing.status_code == 404
        assert _counts(settings) == {"runs": 2, "rerun_receipts": 1}

        before_malformed = _counts(settings)
        for body in ({}, {"request_id": "malformed", "extra": True}):
            malformed = client.post(
                f"/api/research-runs/{original['id']}/rerun",
                json=body,
            )
            assert malformed.status_code == 422
        assert _counts(settings) == before_malformed

        assert runtime.research_runs.process_next() is True
        completed = client.get(f"/api/research-runs/{rerun['id']}")
        assert completed.status_code == 200
        completed_detail = completed.json()
        assert completed_detail["status"] == "succeeded"
        assert completed_detail["rerun_of_id"] == original["id"]
        assert completed_detail["dataset_release_id"] == original_release_id
        assert completed_detail["result"]["provenance"] == {
            **original_before["result"]["provenance"],
            "research_run_id": rerun["id"],
        }
        expected_digest = hashlib.sha256(
            canonical_json_bytes(stored_original["immutable_input"])
        ).hexdigest()
        assert completed_detail["result"]["provenance"][
            "immutable_input_sha256"
        ] == expected_digest
        assert client.get(f"/api/research-runs/{original['id']}").json() == original_before


def _valid_command(request_id: str, *, holdings_count: int) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "Original exact input",
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


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT immutable_input, dataset_release_id, rerun_of_id
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
            assert row is not None
            return dict(row)
    finally:
        database.close()


def _counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            runs = transaction.execute(
                "SELECT count(*) AS count FROM research_runs.runs"
            ).fetchone()
            receipts = transaction.execute(
                "SELECT count(*) AS count FROM research_runs.rerun_receipts"
            ).fetchone()
            assert runs is not None and receipts is not None
            return {
                "runs": int(runs["count"]),
                "rerun_receipts": int(receipts["count"]),
            }
    finally:
        database.close()


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
