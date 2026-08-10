import os
import subprocess
from dataclasses import replace

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.database_restart
def test_requested_research_dates_save_reopen_and_keep_drafts_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("THESISTRACE_DATABASE_RESTART_PHASE") != "1":
        pytest.skip("database restart acceptance runs in its isolated final phase")
    settings = CoreSettings.from_environment()
    _drop_definitions_schema(settings)
    app = create_app(settings)
    before = _execution_counts(settings)

    with TestClient(app) as client:
        empty = client.post("/api/definitions", json={})
        assert empty.status_code == 201
        assert empty.json()["start_date"] is None
        assert empty.json()["end_date"] is None

        start_only = client.post(
            "/api/definitions",
            json={"start_date": "2026-01-02"},
        )
        assert start_only.status_code == 201
        definition = start_only.json()
        assert definition["start_date"] == "2026-01-02"
        assert definition["end_date"] is None

        completed = client.put(
            f"/api/definitions/{definition['id']}",
            json={
                "expected_revision": 1,
                "end_date": "2026-12-31",
            },
        )
        assert completed.status_code == 200
        definition = completed.json()
        assert definition["revision"] == 2
        assert definition["start_date"] == "2026-01-02"
        assert definition["end_date"] == "2026-12-31"

    restarted_port = _restart_isolated_postgres()
    restarted_settings = replace(
        settings,
        database_url=(
            "postgresql://thesistrace:thesistrace-test@127.0.0.1:"
            f"{restarted_port}/thesistrace"
        ),
    )
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", restarted_settings.database_url)

    with TestClient(create_app(restarted_settings)) as restarted:
        reopened = restarted.get(f"/api/definitions/{definition['id']}")
        assert reopened.status_code == 200
        assert reopened.json() == definition

    assert _execution_counts(restarted_settings) == before


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_invalid_or_stale_date_edits_never_replace_the_durable_revision() -> None:
    settings = CoreSettings.from_environment()
    _drop_definitions_schema(settings)

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/definitions",
            json={"start_date": "2026-01-02", "end_date": "2026-06-30"},
        ).json()
        definition_id = created["id"]

        for command in (
            {"expected_revision": 1, "start_date": "2026-02-30"},
            {"expected_revision": 1, "start_date": "01/02/2026"},
            {"expected_revision": 1, "end_date": 20260630},
            {"expected_revision": 1, "start_date": True},
            {"expected_revision": 1, "research_period": "2026"},
        ):
            rejected = client.put(f"/api/definitions/{definition_id}", json=command)
            assert rejected.status_code == 422, (command, rejected.text)
            assert client.get(f"/api/definitions/{definition_id}").json() == created

        newer = client.put(
            f"/api/definitions/{definition_id}",
            json={"expected_revision": 1, "end_date": "2026-09-30"},
        )
        assert newer.status_code == 200

        stale = client.put(
            f"/api/definitions/{definition_id}",
            json={"expected_revision": 1, "start_date": "2025-01-02"},
        )
        assert stale.status_code == 409
        assert stale.json() == {"detail": {"current_revision": 2}}
        assert client.get(f"/api/definitions/{definition_id}").json() == newer.json()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_run_request_replay_fingerprint_includes_requested_dates() -> None:
    settings = CoreSettings.from_environment()
    _drop_definitions_schema(settings)

    command = {
        "request_id": "definition-dates-replay",
        "start_date": "2026-01-02",
        "end_date": "2026-06-30",
    }
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/definitions/run", json=command)
        replay = client.post("/api/definitions/run", json=command)
        conflict = client.post(
            "/api/definitions/run",
            json={**command, "end_date": "2026-12-31"},
        )

        assert first.status_code == 200
        assert first.json()["outcome"] == "rejected"
        assert first.json()["definition"]["start_date"] == "2026-01-02"
        assert first.json()["definition"]["end_date"] == "2026-06-30"
        assert replay.status_code == 200
        assert replay.json() == first.json()
        assert conflict.status_code == 409


def _drop_definitions_schema(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
    finally:
        database.close()


def _execution_counts(settings: CoreSettings) -> tuple[int, int, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM research_runs.runs) AS runs,
                    (SELECT count(*) FROM data.refresh_operations) AS refreshes,
                    (SELECT count(*) FROM data.bootstrap_operations) AS bootstraps
                """
            ).fetchone()
        assert row is not None
        return int(row["runs"]), int(row["refreshes"]), int(row["bootstraps"])
    finally:
        database.close()


def _restart_isolated_postgres() -> int:
    if not os.environ.get("THESISTRACE_TEST_PROJECT_NAME"):
        pytest.skip("an isolated Core Compose project is required for database restart")
    restarted = subprocess.run(
        ["./scripts/test-runtime", "restart-postgres"],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert restarted.returncode == 0, restarted.stderr
    host_port = restarted.stdout.strip().rsplit(":", maxsplit=1)[-1]
    assert host_port.isdigit(), restarted.stdout
    return int(host_port)
