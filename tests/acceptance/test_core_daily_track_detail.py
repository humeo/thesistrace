from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas, internal_api_origin
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.data.canonical_mapping import field_catalog
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_detail_keeps_latest_504_sessions_and_full_origin_metrics(
    tmp_path: Path,
) -> None:
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "canonical-data",
        benchmark_mount=tmp_path / "benchmark-data",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=510)
    seed_sessions = sessions[:3]
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            *(BenchmarkLevel(session, "4000") for session in sessions),
        ),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    head_a = _publish_head(
        settings,
        sessions=seed_sessions,
        expected_manifest=None,
        operation_id="daily-track-504-head-a",
    )

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json=_run_command(
                "daily-track-504-run",
                start_date=seed_sessions[0],
                end_date=seed_sessions[-1],
            ),
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["id"]
        completed = _run_worker_once(settings, "research")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        research_events = _worker_events(completed)
        assert research_events[0]["event"] == "worker_started"
        assert research_events[0]["worker_role"] == "research"
        assert research_events[1]["event"] == "research_run_claimed"
        assert research_events[1]["run_id"] == run_id

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
        first_advance = _run_worker_once(settings, "tracking")
        assert first_advance.returncode == 0, first_advance.stdout + first_advance.stderr
        tracking_events = _worker_events(first_advance)
        assert tracking_events[0]["worker_role"] == "tracking"
        assert tracking_events[1]["event"] == "tracking_advance_claimed"
        assert tracking_events[1]["track_id"] == track_id
        first_detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert first_detail["strategy_session"] == sessions[66]
        assert first_detail["lag_sessions"] == 236
        for _ in range(4):
            catch_up = _run_worker_once(settings, "tracking")
            assert catch_up.returncode == 0, catch_up.stdout + catch_up.stderr
        assert client.get(f"/api/daily-tracks/{track_id}").json()[
            "strategy_session"
        ] == sessions[302]

        _publish_head(
            settings,
            sessions=sessions,
            expected_manifest=head_b,
            operation_id="daily-track-504-head-c",
        )
        for _ in range(4):
            second_advance = _run_worker_once(settings, "tracking")
            assert second_advance.returncode == 0, (
                second_advance.stdout + second_advance.stderr
            )
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

    # One share lot is bought on the second session at a constant CNY 10 open.
    # The hand-calculated oracle is independent of the batch Kernel and proves
    # that metrics still start at the Tracking Origin, before the retained window.
    actual_metrics = detail["strategy"]["summary"]["metrics"]
    initial_cash = Decimal("10000000")
    notional = Decimal(999_600) * Decimal(10)
    expected_cost = notional * (Decimal("0.0003") + Decimal("0.00001"))
    expected_wealth = (initial_cash - expected_cost) / initial_cash
    return_intervals = len(sessions) - 1
    comparison_intervals = len(sessions) - 2
    expected_net_return = float(expected_wealth - 1)
    expected_annualized_return = float(expected_wealth) ** (
        252 / comparison_intervals
    ) - 1

    assert actual_metrics["transaction_costs"]["cumulative_amount"] == float(
        expected_cost
    )
    assert actual_metrics["net_cumulative_return"] == expected_net_return
    assert actual_metrics["benchmark_cumulative_return"] == 0.0
    assert actual_metrics["annualized_excess_return"] == expected_annualized_return
    comparison = detail["strategy"]["comparison"]
    assert comparison["status"] == "available"
    assert comparison["entry"]["session"] == sessions[1]
    assert len(comparison["curves"]) == 504
    assert comparison["curves"][0]["session"] == expected_window[0]
    assert comparison["curves"][0]["net_strategy_return"] == expected_net_return
    assert comparison["curves"][0]["benchmark_relative_return"] == 0.0
    assert comparison["curves"][0]["net_excess_nav"] == float(expected_wealth)
    assert comparison["curves"][0]["net_excess_return"] == expected_net_return
    assert actual_metrics["sharpe"] == pytest.approx(
        -math.sqrt(252 / return_intervals),
        rel=1e-12,
    )


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
            {"session": session, "instrument_ids": [instrument_id]}
            for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _run_command(
    request_id: str,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "DailyTrack latest 504",
        "start_date": start_date,
        "end_date": end_date,
        "formula": "close",
        "universe": "top300",
        "neutralization": "none",
        "research_kind": "strategy_backtest",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _run_worker_once(
    settings: CoreSettings,
    role: str,
) -> subprocess.CompletedProcess[str]:
    environment = {
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
    }
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            role,
            "--once",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )


def _worker_events(
    completed: subprocess.CompletedProcess[str],
) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in completed.stderr.splitlines()
        if line.startswith("{")
    ]


def _business_sessions(start: date, *, count: int) -> tuple[str, ...]:
    sessions: list[str] = []
    cursor = start
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(sessions)
