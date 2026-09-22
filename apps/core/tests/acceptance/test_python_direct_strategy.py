from dataclasses import replace
from pathlib import Path
from uuid import UUID

import anyio
import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _publish_composite_head,
    _publish_head,
    _stored_tracking_activation,
)

from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="isolated Core runtime is not configured",
)

SESSIONS = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")
SOURCE = """
def decide(context, state, parameters):
    if context['session'] == parameters.get('fail_session'):
        raise ValueError('deliberate program failure')
    state['count'] = state.get('count', 0) + 1
    output = None
    if not context['account']['positions']:
        candidate = context['candidates'][0]['instrument_id']
        output = {
            'reason': 'enter_visible_candidate',
            'allocation': {'mode': 'rebalance', 'instrument_ids': [candidate],
                           'relative_weights': {candidate: '1'}, 'exposure': 1.0},
            'position_limits': {},
        }
    return {'output': output, 'state': state}
"""


def command(request_id, *, end=SESSIONS[2], parameters=None):
    return {
        "request_id": request_id,
        "folder_id": "folder_default",
        "name": "Direct Python",
        "research_kind": "strategy_backtest",
        "strategy_mode": "direct",
        "start_date": SESSIONS[0],
        "end_date": end,
        "universe": "top300",
        "initial_cash_cny": "100000",
        "program": {
            "source": SOURCE,
            "parameters": parameters or {},
            "data_requirements": {"field_ids": ["price.close.adjusted"], "history_sessions": 1},
        },
    }


def test_direct_track_origin_keeps_a_large_legal_explicit_state(tmp_path: Path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, sessions=SESSIONS[:2], price_offset=0)
    with TestClient(create_app(settings)) as client:
        submitted = command("large-direct-state", end=SESSIONS[1])
        submitted["program"]["source"] = (
            "def decide(context, state, parameters):\n"
            "    return {'output': None, 'state': {'payload': 'x' * 200000}}"
        )
        admitted = client.post("/api/research-runs", json=submitted)
        assert admitted.status_code == 202, admitted.text
        run_id = admitted.json()["id"]
        assert client.app.state.core_runtime.research_runs.process_next()
        tracked = client.post(
            f"/api/research-runs/{run_id}/daily-tracks", json={"request_id": "large-state-track"},
        )
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        from core_runtime import TEST_RESEARCHER

        from thesistrace.daily_track.models import DailyTrackOriginResultSectionInput

        origin = client.app.state.core_runtime.daily_tracks.get_result_section(
            TEST_RESEARCHER.researcher_id,
            DailyTrackOriginResultSectionInput(track_id=track_id, section="origin"),
        )
        assert origin.terminal_account.decision_state.state == {
            "payload": "x" * 200000,
        }


def test_direct_run_freezes_program_and_continues_the_same_account_in_daily_track(tmp_path: Path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        submitted = command("direct-run")
        diagnosed = client.post(
            "/api/research/diagnostics",
            json={
                key: value
                for key, value in submitted.items()
                if key not in {"request_id", "folder_id", "name"}
            },
        )
        assert diagnosed.status_code == 200, diagnosed.text
        assert diagnosed.json()["valid"]
        admitted = client.post("/api/research-runs", json=submitted)
        assert admitted.status_code == 202, admitted.text
        run_id = admitted.json()["id"]
        assert runtime.research_runs.process_next()
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded", detail
        assert detail["input"]["program"] == submitted["program"]
        terminal = detail["result"]["terminal_strategy_state"]
        assert terminal["decision_state"]["state"] == {"count": 3}
        assert terminal["pending_target"] is None
        tracked = client.post(
            f"/api/research-runs/{run_id}/daily-tracks", json={"request_id": "track"}
        )
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        refreshed = client.post(
            f"/api/daily-tracks/{track_id}/refresh", json={"request_id": "advance"}
        )
        assert refreshed.status_code == 202, refreshed.text
        assert runtime.daily_tracks.process_next()
        track = client.get(f"/api/daily-tracks/{track_id}").json()
        assert track["strategy_session"] == SESSIONS[-1], track
        assert track["observation"]["decision_state"]["state"] == {"count": 5}
        assert track["observation"]["selection_interval"] is None
        full = client.post("/api/research-runs", json=command("full", end=SESSIONS[-1]))
        assert full.status_code == 202, full.text
        assert runtime.research_runs.process_next()
        full_result = client.get(f"/api/research-runs/{full.json()['id']}").json()
        assert full_result["status"] == "succeeded", full_result
        full_terminal = full_result["result"]["terminal_strategy_state"]
        assert track["observation"]["net_asset_value_cny"] == full_terminal["net_nav"]
        assert track["observation"]["decision_state"] == full_terminal["decision_state"]


def test_direct_batch_item_failure_does_not_mutate_its_successful_sibling(tmp_path: Path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        good = command("good")
        bad = command("bad", parameters={"fail_session": SESSIONS[1]})
        batch = client.post(
            "/api/research-batches",
            json={
                "batch_kind": "strategy_sweep",
                "request_id": "two-programs",
                "start_date": SESSIONS[0],
                "end_date": SESSIONS[2],
                "universe": "top300",
                "strategies": [
                    {
                        "item_key": key,
                        **{
                            name: item[name]
                            for name in (
                                "strategy_mode",
                                "initial_cash_cny",
                                "program",
                            )
                        },
                    }
                    for key, item in [("good", good), ("bad", bad)]
                ],
            },
        )
        assert batch.status_code == 202, batch.text
        assert runtime.research_batches.process_next()
        detail = client.get(f"/api/research-batches/{batch.json()['id']}").json()
        assert detail["status"] == "completed_with_failures", detail
        items = {item["item_key"]: item for item in detail["items"]}
        assert items["good"]["status"] == "succeeded"
        assert items["bad"]["status"] == "failed"
        assert "2026-08-04" in items["bad"]["diagnostic"]["message"]
        good_run = client.get(f"/api/research-runs/{items['good']['research_run_id']}").json()
        assert good_run["result"]["terminal_strategy_state"]["decision_state"]["state"] == {
            "count": 3
        }
        bad_run = client.get(f"/api/research-runs/{items['bad']['research_run_id']}").json()
        assert "result" not in bad_run
        standalone = client.post("/api/research-runs", json=good)
        assert standalone.status_code == 202, standalone.text
        assert runtime.research_runs.process_next()
        reference = client.get(f"/api/research-runs/{standalone.json()['id']}").json()
        assert (
            good_run["result"]["terminal_strategy_state"]
            == reference["result"]["terminal_strategy_state"]
        )


def test_direct_program_failure_does_not_publish_a_tracking_head_and_keeps_location(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        bad = client.post(
            "/api/research-runs",
            json=command(
                "bad-run",
                parameters={"fail_session": SESSIONS[1]},
            ),
        )
        assert bad.status_code == 202, bad.text
        assert runtime.research_runs.process_next()
        failure = client.get(f"/api/research-runs/{bad.json()['id']}").json()
        assert failure["status"] == "failed", failure
        assert "2026-08-04" in failure["failure_reason"]
        assert "line 4" in failure["failure_reason"]
        assert "result" not in failure
        seed = client.post(
            "/api/research-runs",
            json=command(
                "bad-track-seed",
                parameters={"fail_session": SESSIONS[3]},
            ),
        )
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        tracked = client.post(
            f"/api/research-runs/{seed.json()['id']}/daily-tracks",
            json={"request_id": "failing-track"},
        )
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        before = _stored_tracking_activation(settings, track_id)
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        response = client.post(
            f"/api/daily-tracks/{track_id}/refresh", json={"request_id": "failed-advance"}
        )
        assert response.status_code == 202, response.text
        with pytest.raises(DailyTrackProgressionFailed):
            runtime.daily_tracks.process_next()
        after = _stored_tracking_activation(settings, track_id)
        assert (
            after["current_checkpoint_manifest_sha256"]
            == before["current_checkpoint_manifest_sha256"]
        )
        assert after["terminal_strategy_state"] == before["terminal_strategy_state"]
        assert after["checkpoint_count"] == 1
        assert after["failed_attempt_count"] == 1
        detail = client.get(f"/api/daily-tracks/{track_id}").json()
        assert detail["status"] == "blocked", detail
        assert "2026-08-06" in detail["blocked_reason"]
        # Private source, parameters and state use the same ownership boundary.
        assert runtime.research_runs.get_detail(UUID(int=1234), seed.json()["id"]) is None
        assert runtime.daily_tracks.get(UUID(int=1234), track_id) is None
        legal = client.post("/api/research-runs", json=command("after-failed-program"))
        assert legal.status_code == 202, legal.text
        assert runtime.research_runs.process_next()
        assert (
            client.get(f"/api/research-runs/{legal.json()['id']}").json()["status"] == "succeeded"
        )


def test_direct_mcp_admission_runs_declared_financial_fields_through_the_real_worker(tmp_path):
    from test_core_research_agent_mcp_runs import _mcp_client

    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_composite_head(settings, sessions=("2010-01-04", "2010-04-21", *SESSIONS[:3]))
    value = command("direct-mcp")
    value["program"] = {
        "source": "def decide(context, state, parameters):\n"
        "    return {'output': None, 'state': {'revenue': "
        "context['history']['fields']['financial.income.total_revenue.latest_fy']}}",
        "parameters": {},
        "data_requirements": {
            "field_ids": ["financial.income.total_revenue.latest_fy"],
            "history_sessions": 1,
        },
    }

    async def submit():
        async with _mcp_client(settings, tmp_path / "direct-mcp.stderr.log") as mcp:
            response = await mcp.call_tool("submit_research_run", value)
            assert not response.is_error, response
            assert response.structured_content["outcome"] == "accepted", response
            return response.structured_content["run_id"]

    with TestClient(create_app(settings)) as client:
        run_id = anyio.run(submit)
        assert client.app.state.core_runtime.research_runs.process_next()
        detail = client.get(f"/api/research-runs/{run_id}").json()
        assert detail["status"] == "succeeded", detail
        assert detail["result"]["terminal_strategy_state"]["decision_state"]["state"] == {
            "revenue": [[100], [200]],
        }
