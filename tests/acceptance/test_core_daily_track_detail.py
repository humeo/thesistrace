from __future__ import annotations

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
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackService
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture
from thesistrace.research_run.result import read_result_bundle


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_daily_track_detail_keeps_latest_504_sessions_and_full_origin_metrics(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=525)
    seed_sessions = sessions[:23]
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
                start_date=seed_sessions[20],
                end_date=seed_sessions[-1],
                alpha={
                    "operator_id": "ts_mean",
                    "operands": [
                        {"field_id": "price.close.adjusted"},
                        {"literal": 20},
                    ],
                },
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
            seed_sessions[20:]
        )

        head_b = _publish_head(
            settings,
            sessions=sessions[:303],
            expected_manifest=head_a,
            operation_id="daily-track-504-head-b",
        )
        first_advance = _run_worker_once(settings)
        assert first_advance.returncode == 0, first_advance.stdout + first_advance.stderr
        first_detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert first_detail["strategy_session"] == sessions[302]

        head_c = _publish_head(
            settings,
            sessions=sessions[:-1],
            expected_manifest=head_b,
            operation_id="daily-track-504-head-c",
        )
        cache_root = tmp_path / "rolling-working-cache"
        processor = DailyTrackService(
            client.app.state.core_runtime.database,
            publication=client.app.state.core_runtime.publication,
            dataset_lifecycle=DatasetLifecycle(
                client.app.state.core_runtime.database,
                settings.data_mount,
            ),
            generation_store=MountedGenerationStore(settings.data_mount),
            read_result_bundle=read_result_bundle,
            working_cache_root=cache_root,
        )
        assert processor.process_next() is True
        second_detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert second_detail["strategy_session"] == sessions[-2]
        cache_path = next(cache_root.glob("*.json"))
        cache_path.write_text("{", encoding="utf-8")

        _publish_head(
            settings,
            sessions=sessions,
            expected_manifest=head_c,
            operation_id="daily-track-504-head-d",
        )
        assert processor.process_next() is True
        detail = client.get(f"/api/daily-tracks/{track_id}").json()

    expected_window = list(sessions[-504:])
    observations = detail["strategy"]["observations"]
    assert [item["session"] for item in observations] == expected_window
    assert detail["strategy_session"] == sessions[-1]
    assert detail["data_through_session"] == sessions[-1]
    for horizon in ("1", "5", "20"):
        assert detail["factor"]["horizons"][horizon]["coverage"]["signal_session_count"] == 504

    # One share lot is bought on the second session at a constant CNY 10 open.
    # The hand-calculated oracle is independent of the batch Kernel and proves
    # that metrics still start at the Tracking Origin, before the retained window.
    actual_metrics = detail["strategy"]["summary"]["metrics"]
    initial_cash = Decimal("10000000")
    notional = Decimal(999_600) * Decimal(10)
    expected_cost = notional * (Decimal("0.0003") + Decimal("0.00001"))
    expected_wealth = (initial_cash - expected_cost) / initial_cash
    return_intervals = len(sessions) - 21
    expected_net_return = float(expected_wealth - 1)
    expected_annualized_return = float(expected_wealth) ** (252 / return_intervals) - 1

    assert actual_metrics["transaction_costs"]["cumulative_amount"] == float(expected_cost)
    assert actual_metrics["net_cumulative_return"] == expected_net_return
    assert actual_metrics["benchmark_cumulative_return"] == 0.0
    assert actual_metrics["annualized_excess_return"] == expected_annualized_return
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


def _run_command(
    request_id: str,
    *,
    start_date: str,
    end_date: str,
    alpha: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "DailyTrack latest 504",
        "start_date": start_date,
        "end_date": end_date,
        "alpha": alpha or {"field_id": "price.close.adjusted"},
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
