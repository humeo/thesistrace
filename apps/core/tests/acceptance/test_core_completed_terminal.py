from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_daily_track_detail import (
    _business_sessions,
    _publish_head,
    _refresh_daily_track,
    _run_command,
    _run_worker_once,
)

from thesistrace.benchmark import BenchmarkLevel, BenchmarkSnapshotStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
@pytest.mark.parametrize(
    "formula", ["close", "if_else(close > 0 and not (close == 0), close, -close)"]
)
def test_one_session_cash_account_publishes_and_tracks_its_first_entry(tmp_path: Path, formula):
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "data",
        benchmark_mount=tmp_path / "benchmark",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=3)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            *(BenchmarkLevel(session, "4000") for session in sessions),
        ),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    _publish_head(settings, sessions=sessions, expected_manifest=None, operation_id="one-day")
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json={
                **_run_command("one-day", start_date=sessions[0], end_date=sessions[0]),
                "initial_cash_cny": "100000",
                "formula": formula,
            },
        )
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded", detail
        result = detail["result"]
        account = result["terminal_strategy_state"]
        assert account["positions"] == []
        assert Decimal(account["net_nav"]) == Decimal("100000")
        assert account["pending_signal"]["signal_session"] == sessions[0]
        assert result["strategy"]["summary"]["entry_session"] is None
        assert result["strategy"]["comparison"] == {
            "status": "unavailable",
            "reason": "no_entry_open",
        }
        started = client.post(
            f"/api/research-runs/{run_id}/daily-tracks", json={"request_id": "one-day-track"}
        )
        assert started.status_code == 201, started.text
        track_id = started.json()["id"]
        seed = client.get(f"/api/daily-tracks/{track_id}")
        assert seed.status_code == 200, seed.text
        assert seed.json()["strategy"]["comparison"]["reason"] == "no_entry_open"
        _refresh_daily_track(client, track_id, "first-entry")
        worker = _run_worker_once(settings, "tracking")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        tracked = client.get(f"/api/daily-tracks/{track_id}").json()
        assert tracked["strategy_session"] == sessions[-1], tracked
        assert tracked["strategy"]["comparison"]["entry"]["session"] == sessions[1]
        assert Decimal(tracked["strategy"]["observations"][-1]["net_nav"]) == Decimal("99969.31")
