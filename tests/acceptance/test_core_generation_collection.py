from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, internal_api_origin
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, GenerationStoreError, MountedGenerationStore
from thesistrace.data.canonical_mapping import field_catalog
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_private_collection_removes_retired_input_without_losing_run_or_track(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = ("2026-08-05", "2026-08-06", "2026-08-07")
    retired = _publish_head(
        settings,
        _canonical(sessions, price_offset=0),
        operation_id="collection-acceptance-retired",
    )

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json={
                "request_id": "collection-acceptance-run",
                "folder_id": "folder_default",
                "name": "Collected input remains an audit coordinate",
                "start_date": sessions[0],
                "end_date": sessions[-1],
                "formula": "close",
                "universe": "top300",
                "neutralization": "none",
                "research_kind": "strategy_backtest",
                "holdings_count": 1,
                "rebalance_every_sessions": 1,
            },
        )
        assert accepted.status_code == 202
        run_id = str(accepted.json()["id"])
        worker = _run_worker_once(settings)
        assert worker.returncode == 0, worker.stdout + worker.stderr
        tracking = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "collection-acceptance-track"},
        )
        assert tracking.status_code == 201
        track_id = str(tracking.json()["id"])
        before_run = client.get(f"/api/research-runs/{run_id}").json()
        before_track = client.get(f"/api/daily-tracks/{track_id}").json()
        assert _run_generation(settings, run_id) == retired

        current = _publish_head(
            settings,
            _canonical(sessions, price_offset=1),
            expected=retired,
            operation_id="collection-acceptance-current",
        )
        ordinary_worker = _run_worker_once(settings)
        assert ordinary_worker.returncode == 0, ordinary_worker.stdout + ordinary_worker.stderr
        with TestClient(create_app(settings)) as ordinary_restart:
            assert (
                ordinary_restart.get("/api/data").json()["market_research_readiness"]
                is True
            )
        assert (
            MountedGenerationStore(tmp_path).validate_generation(retired).manifest_sha256 == retired
        )
        outcome = _run_collection(settings, "collection-acceptance")

        assert outcome["status"] == "succeeded"
        assert int(outcome["deleted_file_count"]) > 0
        assert int(outcome["deleted_receipt_count"]) >= 0
        assert outcome["remaining_file_count"] == 0
        with pytest.raises(GenerationStoreError, match="missing"):
            MountedGenerationStore(tmp_path).validate_generation(retired)
        assert (
            MountedGenerationStore(tmp_path).validate_generation(current).manifest_sha256 == current
        )
        assert client.get(f"/api/research-runs/{run_id}").json() == before_run
        assert client.get(f"/api/daily-tracks/{track_id}").json() == before_track
        assert client.post("/api/data/collect").status_code == 404

    with TestClient(create_app(settings)) as reopened:
        assert reopened.get(f"/api/research-runs/{run_id}").json() == before_run
        assert reopened.get(f"/api/daily-tracks/{track_id}").json() == before_track
        overview = reopened.get("/api/data")
        assert overview.status_code == 200
        assert overview.json()["market_research_readiness"] is True
        assert overview.json()["data_through_session"] == sessions[-1]


def _canonical(sessions: tuple[str, ...], *, price_offset: int) -> dict[str, object]:
    template = build_minimal_canonical_fixture(price_offset=price_offset)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "field_catalog": [
            next(
                row
                for row in field_catalog(sessions[0])
                if row["field_id"] == "price.close.adjusted"
            )
        ],
        "research_calendar": list(sessions),
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _publish_head(
    settings: CoreSettings,
    canonical: dict[str, object],
    *,
    operation_id: str,
    expected: str | None = None,
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=datetime(2026, 8, 10, tzinfo=UTC),
        source_name="collection-acceptance",
        source_lineage={"operation_id": operation_id},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _run_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "research",
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "THESISTRACE_DATABASE_URL": settings.database_url,
            "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
            "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
            "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
            "THESISTRACE_S3_BUCKET": settings.s3_bucket,
            "THESISTRACE_S3_REGION": settings.s3_region,
            "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
            "THESISTRACE_INTERNAL_API_ORIGIN": internal_api_origin(settings),
            "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
                settings.batch_attempt_control_directory
            ),
        },
    )


def _run_collection(settings: CoreSettings, key: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.data_operator",
            "collect",
            "--idempotency-key",
            key,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "THESISTRACE_DATABASE_URL": settings.database_url,
            "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        },
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def _run_generation(settings: CoreSettings, run_id: str) -> str:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT result_provenance ->> 'data_generation_id' AS generation
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        assert row is not None
        return str(row["generation"])
    finally:
        database.close()
