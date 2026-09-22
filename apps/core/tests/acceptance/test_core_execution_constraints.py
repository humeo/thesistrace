from dataclasses import replace
from datetime import date
from decimal import Decimal

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
from test_core_research_agent_mcp_runs import _mcp_client

from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core


@pytest.mark.skipif(not core_environment_is_configured(), reason="isolated runtime required")
@pytest.mark.parametrize(
    "cash,planned,legal,submitted,reason",
    [
        ("100000", 10000, 10000, 9900, "insufficient_cash"),
        ("1000", 100, 100, 0, "insufficient_cash"),
        ("500", 50, 0, 0, "below_board_lot"),
    ],
)
def test_execution_constraints_publish_and_continue_through_tracking(
    tmp_path,
    cash,
    planned,
    legal,
    submitted,
    reason,
):
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path / "data",
        benchmark_mount=tmp_path / "benchmark",
    )
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    sessions = _business_sessions(date(2024, 8, 1), count=3)
    # This fixture has one ordinary A share at an Open of CNY 10.
    _publish_head(settings, sessions=sessions, expected_manifest=None, operation_id="constraints")
    section = "strategy_execution_constraints"
    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/research-runs",
            json={
                **_run_command("constraints", start_date=sessions[0], end_date=sessions[1]),
                "initial_cash_cny": cash,
                "exposure_expression": "1",
            },
        )
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        worker = _run_worker_once(settings, "research")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        detail = client.get(f"/api/research-runs/{run_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "succeeded", detail.text
        path = f"/api/research-runs/{run_id}/events/query"
        response = client.post(path, json={"section": section})
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["status"] == "recorded" and page["next_cursor"] is None
        assert len(page["rows"]) == 1
        row = page["rows"][0]
        assert row["decision_session"] == sessions[0] and row["session"] == sessions[1]
        assert row["reason"] == reason and row["mode"] == "rebalance"
        assert row["decision_reason"] == "selection"
        assert row["unrounded_quantity"] == planned
        assert row["legal_quantity"] == legal
        assert row["submitted_quantity"] == submitted
        assert Decimal(row["available_cash_cny"]) == Decimal(cash)
        targets = client.post(
            path, json={"section": "strategy_targets", "target_id": row["target_id"]}
        )
        assert targets.status_code == 200 and len(targets.json()["rows"]) == 1
        orders = client.post(
            path, json={"section": "strategy_orders", "target_id": row["target_id"]}
        )
        fills = client.post(path, json={"section": "strategy_fills", "target_id": row["target_id"]})
        assert orders.status_code == fills.status_code == 200
        if submitted:
            assert len(orders.json()["rows"]) == 1
            assert orders.json()["rows"][0]["order_id"] == row["order_id"]
            assert orders.json()["rows"][0]["legal_quantity"] == submitted
            assert orders.json()["rows"][0]["rejection_reason"] is None
            filtered = client.post(path, json={"section": section, "order_id": row["order_id"]})
            assert filtered.status_code == 200 and filtered.json()["rows"] == [row]
        else:
            assert row["order_id"] is None and orders.json()["rows"] == []
        assert sum(fill["quantity"] for fill in fills.json()["rows"]) == submitted
        assert (
            client.post(
                path, json={"section": section, "instrument_id": "equity:600000.SH"}
            ).json()["rows"]
            == []
        )

        started = client.post(
            f"/api/research-runs/{run_id}/daily-tracks", json={"request_id": "constraint-track"}
        )
        assert started.status_code == 201, started.text
        track_id = started.json()["id"]
        _refresh_daily_track(client, track_id, "constraint-refresh")
        worker = _run_worker_once(settings, "tracking")
        assert worker.returncode == 0, worker.stdout + worker.stderr
        track = client.get(f"/api/daily-tracks/{track_id}")
        assert track.status_code == 200 and track.json()["strategy_session"] == sessions[2]
        track_path = f"/api/daily-tracks/{track_id}/events/query"
        first = client.post(track_path, json={"section": section, "limit": 1})
        assert first.status_code == 200, first.text
        first = first.json()
        assert first["status"] == "recorded" and first["rows"] == [row]
        assert first["next_cursor"] is not None
        second = client.post(
            track_path, json={"section": section, "limit": 1, "cursor": first["next_cursor"]}
        )
        assert second.status_code == 200, second.text
        second = second.json()
        assert second["status"] == "recorded" and second["next_cursor"] is None
        assert len(second["rows"]) == 1
        assert second["rows"][0]["session"] == sessions[2]
        assert second["rows"][0]["constraint_id"] != row["constraint_id"]
        assert second["source"] == first["source"]
        filtered = client.post(track_path, json={"section": section, "start_session": sessions[2]})
        assert filtered.status_code == 200 and filtered.json()["rows"] == second["rows"]

        async def check_agent_queries():
            async with _mcp_client(settings, tmp_path / "constraints-mcp.stderr.log") as agent:
                run_page = await agent.call_tool(
                    "get_research_run_result",
                    {
                        "run_id": run_id,
                        "section": section,
                        "target_id": row["target_id"],
                    },
                )
                assert run_page.is_error is False, run_page
                assert run_page.structured_content["rows"] == [row]
                track_page = await agent.call_tool(
                    "get_daily_track_result",
                    {
                        "track_id": track_id,
                        "section": section,
                        "start_session": sessions[2],
                    },
                )
                assert track_page.is_error is False, track_page
                assert track_page.structured_content["rows"] == second["rows"]

        anyio.run(check_agent_queries)

        if cash == "100000":
            from thesistrace.entrypoints.runtime import open_core_runtime
            from thesistrace.publication.payload_retention import PayloadRetention

            before_report = client.get(f"/api/research-runs/{run_id}").json()["result"]
            with open_core_runtime(settings) as runtime:
                with runtime.database.transaction() as tx:
                    seed = tx.execute(
                        "SELECT result_manifest_sha256 sha FROM research_runs.runs WHERE id = %s",
                        (run_id,),
                    ).fetchone()["sha"]
                    tx.execute(
                        "UPDATE publication.payload_retention "
                        "SET published_at = now() - interval '8 days', "
                        "expires_at = now() - interval '1 day' WHERE manifest_sha256 = %s",
                        (seed,),
                    )
                retention = PayloadRetention(runtime.database, runtime.publication)
                with runtime.database.transaction() as tx:
                    assert retention.expire_one_in_transaction(tx)
                while runtime.publication.collect_one_pending_deletion():
                    pass

            expired = client.post(path, json={"section": section})
            assert expired.status_code == 200 and expired.json()["status"] == "expired"
            assert expired.json()["rows"] == [] and expired.json()["next_cursor"] is None
            assert client.get(f"/api/research-runs/{run_id}").json()["result"] == before_report
            recent = client.post(track_path, json={"section": section})
            assert recent.status_code == 200, recent.text
            assert recent.json()["status"] == "partially_expired"
            assert recent.json()["rows"] == second["rows"]
            assert client.get(f"/api/daily-tracks/{track_id}").status_code == 200
            # Each Run can seed only one Track, so use an untracked Run to prove activation.
            fresh = client.post("/api/research-runs", json={
                **_run_command("after-expiry", start_date=sessions[0], end_date=sessions[1]),
                "initial_cash_cny": cash, "exposure_expression": "1",
            })
            assert fresh.status_code == 202, fresh.text
            fresh_id = fresh.json()["id"]
            worker = _run_worker_once(settings, "research")
            assert worker.returncode == 0, worker.stdout + worker.stderr
            with open_core_runtime(settings) as runtime:
                with runtime.database.transaction() as tx:
                    tx.execute(
                        "UPDATE publication.payload_retention SET "
                        "published_at = now() - interval '8 days', "
                        "expires_at = now() - interval '1 day' WHERE manifest_sha256 = "
                        "(SELECT result_manifest_sha256 FROM research_runs.runs WHERE id = %s)",
                        (fresh_id,),
                    )
                    assert PayloadRetention(
                        runtime.database, runtime.publication,
                    ).expire_one_in_transaction(tx)
                while runtime.publication.collect_one_pending_deletion():
                    pass
            activated = client.post(
                f"/api/research-runs/{fresh_id}/daily-tracks",
                json={"request_id": "track-after-event-expiry"},
            )
            assert activated.status_code == 201, activated.text
            fresh_track = activated.json()["id"]
            _refresh_daily_track(client, fresh_track, "refresh-after-expiry")
            worker = _run_worker_once(settings, "tracking")
            assert worker.returncode == 0, worker.stdout + worker.stderr
            detail = client.get(f"/api/daily-tracks/{fresh_track}")
            assert detail.status_code == 200 and detail.json()["strategy_session"] == sessions[2]
