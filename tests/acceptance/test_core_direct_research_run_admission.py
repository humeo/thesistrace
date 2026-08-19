from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionSnapshot, DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.research_run import ResearchRunService
from thesistrace.research_run.models import ResearchRunAdmissionCommand

SESSIONS = (
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-10",
    "2026-08-11",
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_formula_rejection_matches_preview_and_leaves_no_durable_admission_state() -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        preview = client.post(
            "/api/alpha/diagnostics",
            json={"source": "unknown_field"},
        )
        rejected = client.post(
            "/api/research-runs",
            json={**_valid_command("direct-invalid"), "formula": "unknown_field"},
        )

        assert preview.status_code == 200
        assert rejected.status_code == 422
        diagnostic = preview.json()["diagnostics"][0]
        issue = rejected.json()["issues"][0]
        assert issue["code"] == diagnostic["code"]
        assert issue["range"] == diagnostic["range"]
        assert issue["field"] == "formula"
        assert client.get("/api/definitions").status_code == 404
        assert (
            client.post(
                "/api/research-runs/run_missing/rerun",
                json={"request_id": "removed-rerun"},
            ).status_code
            == 404
        )

    assert _admission_counts(settings) == {"requests": 0, "runs": 0}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_every_data_or_folder_rejection_leaves_no_durable_admission_state(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        not_ready = client.post(
            "/api/research-runs",
            json=_valid_command("direct-data-not-ready"),
        )
        assert _only_issue_code(not_ready) == "DATA_NOT_READY"
        assert _admission_counts(settings) == {"requests": 0, "runs": 0}

        _publish_current_data(settings)
        cases = (
            (
                {"start_date": "2026-08-02"},
                "RESEARCH_PERIOD_OUTSIDE_COVERAGE",
            ),
            (
                {"start_date": "2026-08-08", "end_date": "2026-08-09"},
                "RESEARCH_PERIOD_HAS_NO_SESSIONS",
            ),
            ({"formula": "volume_shares"}, "FIELD_UNAVAILABLE_IN_CURRENT_DATA"),
            (
                {"formula": "ts_mean(close_adj, 2)"},
                "INSUFFICIENT_CALCULATION_WARMUP",
            ),
            ({"folder_id": "folder_missing"}, "FOLDER_NOT_FOUND"),
        )
        for index, (changes, expected_code) in enumerate(cases):
            command = {
                **_valid_command(f"direct-rejection-{index}"),
                **changes,
            }
            rejected = client.post("/api/research-runs", json=command)
            assert _only_issue_code(rejected) == expected_code
            assert _admission_counts(settings) == {"requests": 0, "runs": 0}

        incomplete = _valid_command("direct-folder-required")
        incomplete.pop("folder_id")
        missing_folder = client.post("/api/research-runs", json=incomplete)
        assert missing_folder.status_code == 422
        assert _admission_counts(settings) == {"requests": 0, "runs": 0}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL runtime is not configured",
)
def test_long_research_is_admitted_by_peak_capacity_and_freezes_its_chunk_plan() -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)
    sessions = tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(505))
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=sessions[-1],
        coverage_start=sessions[0],
        coverage_end=sessions[-1],
        research_sessions=sessions,
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda _universe, _start, _end: 3000,
    )
    command = ResearchRunAdmissionCommand.model_validate(
        {
            **_valid_command("direct-over-budget"),
            "formula": "ts_mean(close_adj, 252)",
            "start_date": sessions[252],
            "end_date": sessions[-1],
            "universe": "top3000",
        }
    )

    with TestClient(create_app(settings)) as client:
        service = ResearchRunService(
            client.app.state.core_runtime.database,
            compile_formula=alpha_language.compile,
            current_dataset=lambda: snapshot,
        )
        admitted = service.admit(command)

    assert admitted.status == "queued"
    frozen = _stored_run(settings, admitted.id)["immutable_input"]
    assert frozen["alpha_admission"]["estimated_run_work"] > 15_000_000
    plan = frozen["execution_plan"]
    assert plan["execution_memory_bytes"] == 1536 * 1024**2
    assert 1 <= plan["chunk_session_count"] <= 64
    assert plan["calculation_sessions"] == [session.isoformat() for session in sessions[1:]]
    assert plan["research_session_offset"] == 251
    assert plan["research_session_count"] == 253
    assert plan["chunks"][0]["first_session"] == sessions[1].isoformat()
    assert plan["chunks"][-1]["last_session"] == sessions[-1].isoformat()
    assert all(
        chunk["session_count"] == plan["chunk_session_count"] for chunk in plan["chunks"][:-1]
    )
    assert _admission_counts(settings) == {"requests": 1, "runs": 1}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_direct_admission_is_atomic_idempotent_and_executes_the_frozen_expression(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _valid_command("direct-success")
        accepted = client.post("/api/research-runs", json=command)
        replay = client.post("/api/research-runs", json=command)
        conflict = client.post(
            "/api/research-runs",
            json={**command, "formula": "volume_shares"},
        )

        assert accepted.status_code == 202
        queued = accepted.json()
        assert replay.status_code == 202
        assert replay.json() == queued
        assert conflict.status_code == 409
        assert queued == {
            "id": queued["id"],
            "status": "queued",
            "name": "Direct Research",
            "folder_id": "folder_default",
            "created_at": queued["created_at"],
            "start_date": "2026-08-03",
            "end_date": "2026-08-04",
            "formula_summary": "close_adj",
        }

        concurrent_command = _valid_command("direct-concurrent")
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(
                executor.map(
                    lambda _index: client.post(
                        "/api/research-runs",
                        json=concurrent_command,
                    ),
                    range(8),
                )
            )
        assert {response.status_code for response in responses} == {202}
        assert len({response.json()["id"] for response in responses}) == 1
        assert _admission_counts(settings) == {"requests": 2, "runs": 2}

        frozen = _stored_run(settings, queued["id"])
        assert frozen["name"] == "Direct Research"
        assert frozen["folder_id"] == "folder_default"
        assert frozen["immutable_input"] == {
            "formula_source": "close_adj",
            "alpha_expression": {"kind": "field", "field_id": "price.close.adjusted"},
            "hypothesis": None,
            "requested_start_date": "2026-08-03",
            "requested_end_date": "2026-08-04",
            "field_bindings": {"price.close.adjusted": "close_adj"},
            "universe": "top300",
            "neutralization": "none",
            "strategy": {
                "kind": "long_only_top_n_equal_weight",
                "holdings_count": 1,
                "rebalance_every_sessions": 1,
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
                "factor": "factor-v1",
                "strategy": "strategy-v1",
                "kernel": "kernel-v4",
            },
            "alpha_admission": {
                "effective_lookback": 0,
                "node_count": 1,
                "depth": 1,
                "formula_work": 1,
                "estimated_run_work": 2,
            },
            "data_admission": {
                "generation_manifest_sha256": frozen["immutable_input"]["data_admission"][
                    "generation_manifest_sha256"
                ],
                "data_through_session": "2026-08-11",
                "coverage_start": "2026-08-03",
                "coverage_end": "2026-08-11",
                "first_research_session": "2026-08-03",
                "last_research_session": "2026-08-04",
                "calculation_session_count": 2,
                "universe_instrument_count": 1,
            },
            "execution_plan": {
                "execution_memory_bytes": 1536 * 1024**2,
                "chunk_time_target_seconds": 30,
                "chunk_session_count": 64,
                "time_target_exceeded": False,
                "estimated_peak_bytes": 67_163_968,
                "estimated_chunk_work": 2_112,
                "maximum_universe_cardinality": 1,
                "calculation_sessions": ["2026-08-03", "2026-08-04"],
                "research_session_offset": 0,
                "research_session_count": 2,
                "chunks": [
                    {
                        "ordinal": 1,
                        "first_session": "2026-08-03",
                        "last_session": "2026-08-04",
                        "session_count": 2,
                        "warmup_session_count": 0,
                        "research_session_count": 2,
                    }
                ],
            },
        }
        _assert_obsolete_schema_is_absent(settings)

        with open_core_runtime(settings) as runtime:
            assert runtime.research_runs.process_next() is True
        completed = client.get(f"/api/research-runs/{queued['id']}")
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"
        assert completed.json()["input"] == {
            "formula": "close_adj",
            "hypothesis": None,
            "start_date": "2026-08-03",
            "end_date": "2026-08-04",
            "universe": "top300",
            "neutralization": "none",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        }
        assert completed.json()["result"]["provenance"]["research_run_id"] == queued["id"]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_research_organization_changes_without_changing_evidence(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        first = client.post(
            "/api/research-runs",
            json=_valid_command("organization-first"),
        ).json()
        second = client.post(
            "/api/research-runs",
            json=_valid_command("organization-second"),
        ).json()
        assert client.app.state.core_runtime.research_runs.process_next() is True
        before = _stored_evidence(settings, first["id"])

        folder = client.post("/api/research-folders", json={"name": "Signals"}).json()
        duplicate_name = client.patch(
            f"/api/research-runs/{first['id']}",
            json={"name": second["name"]},
        )
        moved = client.patch(
            f"/api/research-runs/{first['id']}",
            json={"folder_id": folder["id"]},
        )
        missing = client.patch(
            f"/api/research-runs/{first['id']}",
            json={"folder_id": "folder_missing"},
        )

        assert duplicate_name.status_code == 200
        assert moved.status_code == 200
        assert moved.json()["name"] == second["name"]
        assert moved.json()["folder_id"] == folder["id"]
        assert missing.status_code == 409
        assert client.get(f"/api/research-runs/{first['id']}").json()["folder_id"] == folder["id"]
        assert _stored_evidence(settings, first["id"]) == before

        custom_page = client.get(
            "/api/research-runs",
            params={"folder_id": folder["id"], "limit": 1},
        ).json()
        default_page = client.get(
            "/api/research-runs",
            params={"folder_id": "folder_default", "limit": 1},
        ).json()
        assert [item["id"] for item in custom_page["items"]] == [first["id"]]
        assert [item["id"] for item in default_page["items"]] == [second["id"]]
        assert (
            client.get("/api/research-runs", params={"cursor": "not-a-cursor"}).status_code == 422
        )


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_research_organization_updates_compose_concurrently_and_cursor_is_stable(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        created = [
            client.post(
                "/api/research-runs",
                json=_valid_command(f"organization-page-{index}"),
            ).json()
            for index in range(3)
        ]
        folder = client.post("/api/research-folders", json={"name": "Signals"}).json()
        first_page = client.get("/api/research-runs", params={"limit": 1}).json()
        assert len(first_page["items"]) == 1
        assert first_page["next_cursor"] is not None

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda change: client.patch(
                        f"/api/research-runs/{created[0]['id']}",
                        json=change,
                    ),
                    ({"name": "Duplicate"}, {"folder_id": folder["id"]}),
                )
            )
        assert {response.status_code for response in responses} == {200}
        organized = client.get(f"/api/research-runs/{created[0]['id']}").json()
        assert organized["name"] == "Duplicate"
        assert organized["folder_id"] == folder["id"]

        second_page = client.get(
            "/api/research-runs",
            params={"limit": 1, "cursor": first_page["next_cursor"]},
        ).json()
        assert len(second_page["items"]) == 1
        assert second_page["items"][0]["id"] != first_page["items"][0]["id"]
        assert second_page["next_cursor"] is not None


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.database_restart
def test_direct_admission_reopens_and_replays_after_database_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("THESISTRACE_DATABASE_RESTART_PHASE") != "1":
        pytest.skip("database restart acceptance runs in its isolated final phase")
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    command = _valid_command("direct-restart")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        accepted = client.post("/api/research-runs", json=command)
        assert accepted.status_code == 202
        expected = accepted.json()

    restarted_port = _restart_isolated_postgres()
    restarted_settings = replace(
        settings,
        database_url=(
            f"postgresql://thesistrace:thesistrace-test@127.0.0.1:{restarted_port}/thesistrace"
        ),
    )
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", restarted_settings.database_url)

    with TestClient(create_app(restarted_settings)) as restarted:
        assert restarted.get(f"/api/research-runs/{expected['id']}").status_code == 200
        replay = restarted.post("/api/research-runs", json=command)
        assert replay.status_code == 202
        assert replay.json() == expected
    assert _admission_counts(restarted_settings) == {"requests": 1, "runs": 1}


def _valid_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "Direct Research",
        "formula": "close_adj",
        "hypothesis": None,
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "universe": "top300",
        "neutralization": "none",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _only_issue_code(response: object) -> str:
    assert hasattr(response, "status_code") and response.status_code == 422
    issues = response.json()["issues"]
    assert len(issues) == 1
    return str(issues[0]["code"])


def _admission_counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM research_runs.admission_requests) AS requests,
                    (SELECT count(*) FROM research_runs.runs) AS runs
                """
            ).fetchone()
        assert row is not None
        return {name: int(row[name]) for name in ("requests", "runs")}
    finally:
        database.close()


def _stored_evidence(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT immutable_input::text AS immutable_input,
                       status, execution_fence, result_manifest_sha256,
                       result_provenance::text AS result_provenance,
                       failure_reason,
                       (SELECT count(*) FROM research_runs.attempts
                        WHERE run_id = %s) AS attempt_count
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id, run_id),
            ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        database.close()


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT * FROM research_runs.runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        assert row is not None
        return row
    finally:
        database.close()


def _assert_obsolete_schema_is_absent(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT to_regnamespace('definitions') AS definitions,
                       to_regclass('research_runs.rerun_receipts') AS rerun_receipts
                """
            ).fetchone()
        assert row == {"definitions": None, "rerun_receipts": None}
    finally:
        database.close()


def _publish_current_data(settings: CoreSettings) -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        try:
            s3.create_bucket(Bucket=settings.s3_bucket)
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass
    finally:
        s3.close()
    template = build_minimal_canonical_fixture()
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    canonical = {
        **template,
        "research_calendar": list(SESSIONS),
        "prices": [{**price, "session": session} for session in SESSIONS],
        "trading_states": [{**state, "session": session} for session in SESSIONS],
        "price_limits": [{**limit, "session": session} for session in SESSIONS],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in SESSIONS
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in SESSIONS]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        source_name="direct-admission-test",
        source_lineage={"contract": "direct-research-run"},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id="direct-admission-head",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="direct-admission-head",
        )
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
