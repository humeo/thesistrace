from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import anyio
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
def test_actual_initial_cash_publishes_independent_runs_batch_and_track(tmp_path: Path) -> None:
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "data",
        benchmark_mount=tmp_path / "benchmark",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=5)
    BenchmarkSnapshotStore(settings.benchmark_mount).publish(
        (
            BenchmarkLevel("2010-01-04", "3500"),
            *(BenchmarkLevel(session, "4000") for session in sessions),
        ),
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    head = _publish_head(
        settings, sessions=sessions[:3], expected_manifest=None, operation_id="cash-seed"
    )
    with TestClient(create_app(settings)) as client:
        commands = {}
        results = {}
        ids = {}
        for cash, quantity, cost in (
            ("100000", 9900, "30.69"),
            ("10000000", 999600, "3098.76"),
            ("0.01", 0, "0"),
        ):
            command = {
                **_run_command("cash-" + cash, start_date=sessions[0], end_date=sessions[2]),
                "initial_cash_cny": cash,
            }
            commands[cash] = command
            accepted = client.post("/api/research-runs", json=command)
            assert accepted.status_code == 202, accepted.text
            ids[cash] = accepted.json()["id"]
            worker = _run_worker_once(settings, "research")
            assert worker.returncode == 0, worker.stdout + worker.stderr
            detail = client.get(f"/api/research-runs/{ids[cash]}").json()
            assert detail["status"] == "succeeded", detail
            assert detail["input"]["initial_cash_cny"] == cash
            result = detail["result"]
            results[cash] = result
            account = result["terminal_strategy_state"]
            assert (
                sum(position["execution_shares"] for position in account["positions"]) == quantity
            )
            assert Decimal(account["net_cash"]) == Decimal(cash) - quantity * 10 - Decimal(cost)
            assert Decimal(account["net_nav"]) == Decimal(cash) - Decimal(cost)
            assert Decimal(account["cumulative_transaction_cost"]) == Decimal(cost)

        repeated = client.post(
            "/api/research-runs", json={**commands["100000"], "request_id": "cash-repeat"}
        )
        assert repeated.status_code == 202, repeated.text
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        repeated_result = client.get(f"/api/research-runs/{repeated.json()['id']}").json()["result"]
        assert repeated_result["strategy"] == results["100000"]["strategy"]
        assert (
            repeated_result["terminal_strategy_state"]
            == results["100000"]["terminal_strategy_state"]
        )

        batch = client.post(
            "/api/research-batches",
            json={
                "request_id": "cash-sweep",
                "batch_kind": "strategy_sweep",
                "start_date": sessions[0],
                "end_date": sessions[2],
                "universe": "top300",
                "neutralization": "none",
                "alpha": {"formula": "close"},
                "strategies": [
                    {"weighting": "equal_weight",
                        "item_key": cash,
                        "holdings_count": 1,
                        "selection_every_sessions": 1,
                        "initial_cash_cny": cash,
                    }
                    for cash in ("100000", "10000000")
                ],
            },
        )
        assert batch.status_code == 202, batch.text
        worker = _run_worker_once(settings, "batch-research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        detail = client.get(f"/api/research-batches/{batch.json()['id']}").json()
        assert detail["status"] == "succeeded", detail
        for item in detail["items"]:
            result = client.get(f"/api/research-runs/{item['research_run_id']}").json()["result"]
            assert (
                result["terminal_strategy_state"]
                == results[item["item_key"]]["terminal_strategy_state"]
            )

        started = client.post(
            f"/api/research-runs/{ids['100000']}/daily-tracks", json={"request_id": "cash-track"}
        )
        assert started.status_code == 201, started.text
        track_id = started.json()["id"]
        deleted = client.delete(f"/api/research-runs/{ids['100000']}")
        assert deleted.status_code in (200, 204), deleted.text
        _publish_head(settings, sessions=sessions, expected_manifest=head, operation_id="cash-next")
        _refresh_daily_track(client, track_id, "cash-refresh")
        worker = _run_worker_once(settings, "tracking")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        tracked = client.get(f"/api/daily-tracks/{track_id}").json()
        assert tracked["strategy_session"] == sessions[-1], tracked
        assert tracked["strategy"]["summary"]["metrics"]["net_cumulative_return"] == pytest.approx(
            -0.0003069
        )
        assert Decimal(tracked["strategy"]["observations"][-1]["net_nav"]) == Decimal("99969.31")

        mcp_run = anyio.run(_mcp_cash_contract, settings, tmp_path, track_id, commands["100000"])
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        detail = client.get(f"/api/research-runs/{mcp_run}").json()
        assert detail["status"] == "succeeded", detail
        assert detail["input"]["initial_cash_cny"] == "100000"
        assert (
            detail["result"]["terminal_strategy_state"]
            == results["100000"]["terminal_strategy_state"]
        )


async def _mcp_cash_contract(settings, tmp_path, track_id, command):
    from test_core_research_agent_mcp_runs import _mcp_client

    async with _mcp_client(settings, tmp_path / "cash-mcp.stderr.log") as client:
        provenance = await client.call_tool(
            "get_daily_track_result",
            {
                "track_id": track_id,
                "section": "provenance",
            },
        )
        assert not provenance.is_error, provenance
        assert (
            provenance.structured_content["frozen_research_input"]["initial_cash_cny"] == "100000"
        )
        invalid = await client.call_tool(
            "submit_research_run",
            {
                **command,
                "request_id": "cash-mcp-invalid",
                "initial_cash_cny": "100000.001",
            },
        )
        assert invalid.is_error and invalid.structured_content["code"] == "INVALID_INPUT"
        accepted = await client.call_tool(
            "submit_research_run",
            {
                **command,
                "request_id": "cash-mcp-valid",
                "initial_cash_cny": "100000.00",
            },
        )
        assert not accepted.is_error, accepted
        return accepted.structured_content["run_id"]
