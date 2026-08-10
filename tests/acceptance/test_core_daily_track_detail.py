from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from core_runtime import create_migrated_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.research_kernel import RunInput, run


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_detail_keeps_latest_504_sessions_and_full_origin_metrics(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=510)
    seed_sessions = sessions[:3]
    head_a = _publish_head(
        settings,
        sessions=seed_sessions,
        expected_manifest=None,
        operation_id="daily-track-504-head-a",
    )

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/definitions/run",
            json=_run_command(
                "daily-track-504-run",
                start_date=seed_sessions[0],
                end_date=seed_sessions[-1],
            ),
        )
        assert accepted.status_code == 200
        run_id = accepted.json()["run"]["id"]
        completed = _run_worker_once(settings)
        assert completed.returncode == 0, completed.stdout + completed.stderr

        started = client.post(
            f"/api/research-runs/{run_id}/daily-tracks",
            json={"request_id": "daily-track-504-start"},
        )
        assert started.status_code == 201
        track_id = started.json()["id"]
        seed_detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert [item["session"] for item in seed_detail["strategy"]["observations"]] == list(
            seed_sessions
        )

        head_b = _publish_head(
            settings,
            sessions=sessions[:303],
            expected_manifest=head_a,
            operation_id="daily-track-504-head-b",
        )
        first_advance = _run_worker_once(settings)
        assert first_advance.returncode == 0, first_advance.stdout + first_advance.stderr
        assert client.get(f"/api/daily-tracks/{track_id}").json()["strategy_session"] == (
            sessions[302]
        )

        _publish_head(
            settings,
            sessions=sessions,
            expected_manifest=head_b,
            operation_id="daily-track-504-head-c",
        )
        second_advance = _run_worker_once(settings)
        assert second_advance.returncode == 0, second_advance.stdout + second_advance.stderr
        detail = client.get(f"/api/daily-tracks/{track_id}").json()

    expected_window = list(sessions[-504:])
    observations = detail["strategy"]["observations"]
    assert [item["session"] for item in observations] == expected_window
    assert detail["strategy_session"] == sessions[-1]
    assert detail["data_through_session"] == sessions[-1]
    for horizon in ("1", "5", "20"):
        assert detail["factor"]["horizons"][horizon]["coverage"][
            "signal_session_count"
        ] == 504

    canonical = _canonical(sessions)
    reference = run(
        _kernel_input(
            canonical,
            start_session=sessions[0],
            end_session=sessions[-1],
        )
    ).artifacts_snapshot()["strategy_backtest"]
    actual_metrics = detail["strategy"]["summary"]["metrics"]
    for name in (
        "net_cumulative_return",
        "benchmark_cumulative_return",
        "annualized_excess_return",
        "sharpe",
    ):
        assert actual_metrics[name] == reference["metrics"][name]
    assert actual_metrics["transaction_costs"]["cumulative_amount"] == reference[
        "metrics"
    ]["transaction_costs"]["cumulative_amount"]


def _publish_head(
    settings: CoreSettings,
    *,
    sessions: tuple[str, ...],
    expected_manifest: str | None,
    operation_id: str,
) -> str:
    generation = MountedGenerationStore(settings.data_mount).materialize(
        _canonical(sessions),
        prepared_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        source_name="daily-track-window-test",
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
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _canonical(sessions: tuple[str, ...]) -> dict[str, object]:
    template = build_minimal_canonical_fixture()
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "research_calendar": list(sessions),
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]}
            for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _kernel_input(
    canonical: dict[str, object],
    *,
    start_session: str,
    end_session: str,
) -> RunInput:
    return RunInput(
        canonical_data=canonical,
        alpha_expression={"field_id": "price.close.adjusted"},
        field_bindings={"price.close.adjusted": "close_adj"},
        universe="top300",
        neutralization="none",
        holdings_count=1,
        rebalance_interval=1,
        initial_cash_cny="10000000",
        commission_rate_all_in="0.0003",
        commission_min_cny="5",
        stamp_duty_sell_rate="0.0005",
        transfer_fee_rate="0.00001",
        research_start_session=start_session,
        research_end_session=end_session,
    )


def _run_command(
    request_id: str,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "DailyTrack latest 504",
        "start_date": start_date,
        "end_date": end_date,
        "alpha": {"field_id": "price.close.adjusted"},
        "universe": "top300",
        "neutralization": "none",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _run_worker_once(settings: CoreSettings) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
    }
    return subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )


def _business_sessions(start: date, *, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(sessions)
