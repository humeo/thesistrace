"""The risk matrix uses real Core persistence; browser tests own form/render checks."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import _publish_head, _run_command
from test_python_direct_strategy import SESSIONS

from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_definition import default_simulation_costs
from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(), reason="isolated Core runtime is not configured",
)


@pytest.mark.parametrize("policy", ["fees", "stop_loss", "holding", "take_profit", "drawdown"])
def test_builtin_policy_freezes_reuse_and_continues_published_events(tmp_path, policy):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    modules = dict(BUILTIN_FRAMEWORK_MODULES)
    risk = {"kind": "builtin_risk/v1"}
    if policy == "stop_loss":
        risk["stop_loss_threshold"] = 0.01
    elif policy == "holding":
        modules["portfolio_construction"] = {
            "kind": "periodic_top_n/v1", "minimum_holding_sessions": 2,
        }
        risk["maximum_holding_sessions"] = 2
    elif policy == "take_profit":
        risk["take_profit_tiers"] = [{"profit_threshold": 0.0001, "cumulative_reduction": 0.3}]
    elif policy == "drawdown":
        risk["portfolio_drawdown"] = {
            "drawdown_threshold": 0.01, "maximum_stock_exposure": 0.3, "cooldown_sessions": 2,
        }
    if policy != "fees":
        modules["risk_management"] = risk
    costs = {**default_simulation_costs().model_dump(), "commission_min_cny": "2",
             "slippage_bps": "1000" if policy in {"stop_loss", "drawdown"}
             else "15" if policy == "fees" else "0"}
    submitted = {**_run_command("policy-origin"), "modules": modules, "costs": costs}
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        admitted = client.post("/api/research-runs", json=submitted)
        assert admitted.status_code == 202, admitted.text
        run_id = admitted.json()["id"]
        assert runtime.research_runs.process_next()
        original = client.get(f"/api/research-runs/{run_id}").json()
        assert original["status"] == "succeeded", original
        assert original["input"]["costs"] == costs
        assert original["input"]["modules"] == modules

        def rows(resource, section):
            response = client.post(f"/api/{resource}/events/query",
                                   json={"section": section, "limit": 50})
            assert response.status_code == 200, response.text
            return response.json()["rows"]

        decisions = rows(f"research-runs/{run_id}", "strategy_framework")
        fills = rows(f"research-runs/{run_id}", "strategy_fills")
        assert fills
        if policy == "fees":
            for fill in fills:
                assert Decimal(fill["execution_price"]) != Decimal(fill["raw_open"])
                assert {"commission_cny", "stamp_duty_cny", "transfer_fee_cny"} <= fill.keys()
        if policy in {"stop_loss", "take_profit", "drawdown"}:
            reason = "portfolio_drawdown" if policy == "drawdown" else policy
            assert any(item["reason"] == reason for row in decisions
                       if row["risk_adjustment"]
                       for item in row["risk_adjustment"].get("observations", []))
        if policy == "holding":
            assert decisions[1]["portfolio_retentions"][0]["holding_age"] == 1
            assert decisions[1]["portfolio_retentions"][0]["minimum_holding_sessions"] == 2

        created = client.post(f"/api/research-runs/{run_id}/daily-tracks",
                              json={"request_id": "policy-track"})
        assert created.status_code == 201, created.text
        track_id = created.json()["id"]
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        for step in range(len(SESSIONS)):
            track = client.get(f"/api/daily-tracks/{track_id}").json()
            if track["strategy_session"] == SESSIONS[-1]:
                break
            refresh = client.post(f"/api/daily-tracks/{track_id}/refresh",
                                  json={"request_id": f"policy-refresh-{step}"})
            assert refresh.status_code == 202, refresh.text
            assert runtime.daily_tracks.process_next()
        assert track["strategy_session"] == SESSIONS[-1], track
        continued = rows(f"daily-tracks/{track_id}", "strategy_framework")
        assert continued[:len(decisions)] == decisions
        assert rows(f"daily-tracks/{track_id}", "strategy_fills")[:len(fills)] == fills
        observations = [item for row in continued if row["risk_adjustment"]
                        for item in row["risk_adjustment"].get("observations", [])]
        if policy == "stop_loss":
            assert any(item["reason"] == "stop_loss" for item in observations)
        elif policy == "holding":
            assert any(item["reason"] == "maximum_holding_period" and item["holding_age"] == 2
                       for item in observations)
        elif policy == "take_profit":
            assert any(item["reason"] == "take_profit"
                       and Decimal(item["executed_reduction_units"]) > 0 for item in observations)
        elif policy == "drawdown":
            assert any(item["reason"] == "portfolio_drawdown"
                       and item["status"] == "threshold_reached" for item in observations)
            assert any(item["reason"] == "portfolio_drawdown"
                       and item["completed_cooldown_sessions"] >= 2 for item in observations)

        reused = deepcopy(original["input"])
        reused["costs"]["slippage_bps"] = "25"
        response = client.post("/api/research-runs", json={
            **reused, "request_id": "policy-reuse", "folder_id": "folder_default",
        })
        assert response.status_code == 202, response.text
        frozen_reuse = client.get(f"/api/research-runs/{response.json()['id']}").json()
        assert frozen_reuse["input"]["modules"] == original["input"]["modules"]
        assert frozen_reuse["input"]["costs"]["slippage_bps"] == "25"
        source = client.get(f"/api/research-runs/{run_id}").json()
        assert source["input"] == original["input"]
        assert source["result"] == original["result"]
