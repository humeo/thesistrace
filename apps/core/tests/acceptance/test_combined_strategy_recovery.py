"""Real publication fences preserve one combined risk account across interruption."""

import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _expire_current_tracking_attempt,
    _make_tracking_retry_eligible,
    _publish_head,
    _stored_tracking_activation,
)
from test_python_direct_strategy import command as direct_command
from test_python_framework_strategy import SESSIONS, command

from thesistrace.daily_track import DailyTrackProgressionFailed, DailyTrackService
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.publication.payload_retention import PayloadRetention
from thesistrace.research_definition import default_simulation_costs
from thesistrace.researcher import ResearcherIdentity, ResearcherService

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(), reason="isolated Core runtime is not configured",
)

COMBINED_DIRECT = '''
def decide(context, state, parameters):
    if context['session'] == parameters.get('fail_session'):
        raise ValueError('combined sibling failure')
    day = context['completed_sessions']
    positions = context['account']['positions']
    output = None
    if day == 1:
        item = context['candidates'][0]['instrument_id']
        output = {'reason': 'enter', 'allocation': {'mode': 'rebalance',
                  'instrument_ids': [item], 'relative_weights': {item: '1'}, 'exposure': 1.0},
                  'position_limits': {}}
    elif day in (2, 3):
        output = {'reason': 'local_and_global_caps', 'allocation': None,
                  'position_limits': {p['instrument_id']: p['execution_shares'] * 7 // 10
                                      for p in positions}, 'maximum_stock_exposure': 0.3}
    elif day == 4:
        output = {'reason': 'exit', 'allocation': None,
                  'position_limits': {p['instrument_id']: 0 for p in positions}}
    elif day == 5:
        item = context['candidates'][0]['instrument_id']
        output = {'reason': 'fresh_entry', 'allocation': {'mode': 'rebalance',
                  'instrument_ids': [item], 'relative_weights': {item: '1'}, 'exposure': 0.5},
                  'position_limits': {}}
    sold = state.get('sold', 0) + sum(
        f['quantity'] for f in context['fills'] if f['side'] == 'sell')
    return {'output': output, 'state': {'count': day, 'sold': sold}}
'''


def combined_command(request_id, *, end=SESSIONS[2]):
    value = command(request_id, end=end, builtin_alpha=True)
    value.update(holdings_count=1, selection_every_sessions=1, weighting="equal_weight",
                 volatility_window=20, exposure_expression="1",
                 costs={**default_simulation_costs().model_dump(), "slippage_bps": "0"})
    value["modules"].update({
        "portfolio_construction": {"kind": "periodic_top_n/v1", "minimum_holding_sessions": 1},
        "risk_management": {
            "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1, "maximum_holding_sessions": 5,
            "take_profit_tiers": [{"profit_threshold": 0.0001, "cumulative_reduction": 0.3}],
            "portfolio_drawdown": {"drawdown_threshold": 0.000001,
                                   "maximum_stock_exposure": 0.3, "cooldown_sessions": 2},
        },
    })
    return value


@pytest.mark.parametrize("mode", ["framework", "direct"])
def test_combined_batch_sibling_failure_matches_run_and_segmented_track(tmp_path, mode):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    good = combined_command("combined-mode-seed") if mode == "framework" else direct_command(
        "combined-mode-seed",
    )
    if mode == "direct":
        good["program"]["source"] = COMBINED_DIRECT
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed = client.post("/api/research-runs", json=good)
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        seeded = client.get(f"/api/research-runs/{seed.json()['id']}").json()
        assert seeded["status"] == "succeeded", seeded
        track = client.post(f"/api/research-runs/{seed.json()['id']}/daily-tracks",
                            json={"request_id": "combined-mode-track"})
        assert track.status_code == 201, track.text
        track_id = track.json()["id"]
        for count in (4, 5):
            head = _publish_head(settings, sessions=SESSIONS[:count], price_offset=0,
                                 expected_manifest=head)
            refresh = client.post(f"/api/daily-tracks/{track_id}/refresh",
                                  json={"request_id": f"combined-mode-refresh-{count}"})
            assert refresh.status_code == 202, refresh.text
            assert runtime.daily_tracks.process_next()
        good.update(request_id="combined-mode-full", end_date=SESSIONS[-1])
        bad = deepcopy(good)
        program = (bad["modules"]["universe_selection"]["program"]
                   if mode == "framework" else bad["program"])
        if mode == "framework":
            program["source"] = program["source"].replace(
                "    return", "    if context['session'] == parameters['fail_session']:\n"
                "        raise ValueError('combined sibling failure')\n    return", 1,
            )
        program["parameters"]["fail_session"] = SESSIONS[3]
        excluded = {"request_id", "folder_id", "name", "research_kind", "start_date", "end_date",
                    "universe", "formula", "neutralization"}
        payload = {
            "batch_kind": "strategy_sweep", "request_id": "combined-mode-batch",
            "start_date": SESSIONS[0], "end_date": SESSIONS[-1], "universe": "top300",
            "strategies": [{"item_key": key,
                            **{k: v for k, v in value.items() if k not in excluded}}
                           for key, value in (("good", good), ("bad", bad))],
        }
        if mode == "framework":
            payload.update(alpha={"formula": good["formula"]}, neutralization="none")
        batch = client.post("/api/research-batches", json=payload)
        assert batch.status_code == 202, batch.text
        assert runtime.research_batches.process_next()
        detail = client.get(f"/api/research-batches/{batch.json()['id']}").json()
        assert detail["status"] == "completed_with_failures", detail
        items = {item["item_key"]: item for item in detail["items"]}
        assert items["good"]["status"] == "succeeded"
        assert items["bad"]["status"] == "failed"
        assert "combined sibling failure" in items["bad"]["diagnostic"]["message"]
        failed = client.get(f"/api/research-runs/{items['bad']['research_run_id']}").json()
        assert "result" not in failed
        foreign = ResearcherIdentity(researcher_id=UUID(int=1234),
                                     email="combined-foreign@example.test", display_label="foreign")
        ResearcherService(runtime.database).bootstrap(foreign)
        assert runtime.research_batches.get(foreign.researcher_id, batch.json()["id"]) is None
        assert runtime.daily_tracks.get(foreign.researcher_id, track_id) is None
        for item in items.values():
            assert runtime.research_runs.get_detail(
                foreign.researcher_id, item["research_run_id"],
            ) is None
        full = client.post("/api/research-runs", json=good)
        assert full.status_code == 202, full.text
        assert runtime.research_runs.process_next()
        actual = _stored_tracking_activation(settings, track_id)["terminal_strategy_state"]
        references = (("batch", items["good"]["research_run_id"]), ("full", full.json()["id"]))
        for key, run_id in references:
            reference = client.post(f"/api/research-runs/{run_id}/daily-tracks",
                                    json={"request_id": f"combined-mode-{key}"})
            assert reference.status_code == 201, reference.text
            expected = _stored_tracking_activation(settings, reference.json()["id"])
            assert actual == expected["terminal_strategy_state"]
            fills = client.post(f"/api/research-runs/{run_id}/events/query",
                                json={"section": "strategy_fills", "limit": 50})
            track_fills = client.post(f"/api/daily-tracks/{track_id}/events/query",
                                      json={"section": "strategy_fills", "limit": 50})
            assert fills.status_code == track_fills.status_code == 200
            assert fills.json()["rows"] == track_fills.json()["rows"]
            assert any(row["side"] == "sell" for row in fills.json()["rows"])


@pytest.mark.parametrize("fault", ["checkpoint_insert", "before_publish", "after_publish"])
def test_combined_risk_publication_and_head_commit_once_after_interruption(tmp_path, fault):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        admitted = client.post("/api/research-runs", json=combined_command("combined-seed"))
        assert admitted.status_code == 202, admitted.text
        assert runtime.research_runs.process_next()
        run_id = admitted.json()["id"]
        run = client.get(f"/api/research-runs/{run_id}").json()
        assert run["status"] == "succeeded", run
        seeded_risk = run["result"]["terminal_strategy_state"]["decision_state"]["module_states"][
            "risk_management"
        ]
        assert seeded_risk["take_profit_cycles"]
        assert any(Decimal(row["executed_reduction_units"]) > 0
                   for row in seeded_risk["take_profit_cycles"].values())
        tracked = client.post(f"/api/research-runs/{run_id}/daily-tracks",
                              json={"request_id": "combined-track"})
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        before = _stored_tracking_activation(settings, track_id)
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        requested = client.post(f"/api/daily-tracks/{track_id}/refresh",
                                json={"request_id": "combined-refresh"})
        assert requested.status_code == 202, requested.text
        observed = []

        def observe(stage, _track, _generation):
            observed.append(stage)

        processor = DailyTrackService(
            runtime.database, publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount), progress=observe,
        )
        if fault == "checkpoint_insert":
            with runtime.database.transaction() as transaction:
                transaction.execute("""
                    CREATE FUNCTION daily_tracks.reject_combined_checkpoint() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN
                        RAISE EXCEPTION 'injected transient checkpoint publication failure'
                            USING ERRCODE = '08006';
                    END $$;
                    CREATE TRIGGER reject_combined_checkpoint BEFORE INSERT
                    ON daily_tracks.session_checkpoints FOR EACH ROW
                    EXECUTE FUNCTION daily_tracks.reject_combined_checkpoint();
                """)
        try:
            if fault == "checkpoint_insert":
                with pytest.raises(DailyTrackProgressionFailed):
                    processor.process_next()
            else:
                worker = subprocess.run(
                    [sys.executable, "-c", '''
import os, signal, sys
from pathlib import Path
from dataclasses import replace
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.daily_track import DailyTrackService
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
settings = replace(CoreSettings.from_environment(), data_mount=Path(sys.argv[1]))
def interrupt(stage, track, generation):
    print('BOUNDARY:' + stage, flush=True)
    if stage == sys.argv[2]:
        os.kill(os.getpid(), signal.SIGKILL)
with open_core_runtime(settings) as runtime:
    processor = DailyTrackService(
        runtime.database, publication=runtime.publication,
        dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
        generation_store=MountedGenerationStore(settings.data_mount), progress=interrupt)
    processor.process_next()
''', str(settings.data_mount),
                     "prepared" if fault == "before_publish" else "published"],
                    capture_output=True, text=True, timeout=60,
                )
                assert worker.returncode == -signal.SIGKILL, worker.stdout + worker.stderr
                observed.extend(
                    line.removeprefix("BOUNDARY:") for line in worker.stdout.splitlines()
                    if line.startswith("BOUNDARY:")
                )
        finally:
            if fault == "checkpoint_insert":
                with runtime.database.transaction() as transaction:
                    transaction.execute("""
                        DROP TRIGGER reject_combined_checkpoint ON daily_tracks.session_checkpoints;
                        DROP FUNCTION daily_tracks.reject_combined_checkpoint();
                    """)
        interrupted = _stored_tracking_activation(settings, track_id)
        assert "prepared" in observed
        if fault != "after_publish":
            assert interrupted["current_checkpoint_manifest_sha256"] == (
                before["current_checkpoint_manifest_sha256"]
            )
            assert interrupted["terminal_strategy_state"] == before["terminal_strategy_state"]
            assert interrupted["checkpoint_count"] == 1
            if fault == "before_publish":
                _expire_current_tracking_attempt(settings, track_id)
                recovery_events = []
                assert runtime.daily_tracks.process_next(on_execution_event=recovery_events.append)
                assert [event["event"] for event in recovery_events] == [
                    "tracking_attempt_failed", "tracking_retry_scheduled",
                ]
                recovered = _stored_tracking_activation(settings, track_id)
                assert recovered["terminal_strategy_state"] == before["terminal_strategy_state"]
                assert recovered["checkpoint_count"] == 1
                assert recovered["latest_attempt_failure_reason"] == "WorkerLost"
                assert runtime.daily_tracks.process_next() is False
            _make_tracking_retry_eligible(settings, track_id)
            assert runtime.daily_tracks.process_next()
        else:
            assert "published" in observed
            assert interrupted["checkpoint_count"] == 2
        assert runtime.daily_tracks.process_next() is False
        after = _stored_tracking_activation(settings, track_id)
        assert after["checkpoint_count"] == 2
        assert after["succeeded_progression_count"] == 1
        standalone = client.post("/api/research-runs", json=combined_command(
            "combined-reference", end=SESSIONS[-1],
        ))
        assert standalone.status_code == 202, standalone.text
        assert runtime.research_runs.process_next()
        reference = client.get(f"/api/research-runs/{standalone.json()['id']}").json()
        assert reference["status"] == "succeeded", reference
        reference_track = client.post(
            f"/api/research-runs/{standalone.json()['id']}/daily-tracks",
            json={"request_id": "reference-terminal"},
        )
        assert reference_track.status_code == 201, reference_track.text
        reference_state = _stored_tracking_activation(settings, reference_track.json()["id"])
        actual_metrics = after["terminal_strategy_state"]["metric_state"]
        expected_metrics = reference_state["terminal_strategy_state"]["metric_state"]
        assert {key: (actual_metrics.get(key), expected_metrics.get(key))
                for key in set(actual_metrics) | set(expected_metrics)
                if actual_metrics.get(key) != expected_metrics.get(key)} == {}
        assert after["terminal_strategy_state"] == reference_state["terminal_strategy_state"]
        track_fills = client.post(f"/api/daily-tracks/{track_id}/events/query",
                                 json={"section": "strategy_fills", "limit": 50})
        run_fills = client.post(f"/api/research-runs/{standalone.json()['id']}/events/query",
                               json={"section": "strategy_fills", "limit": 50})
        assert track_fills.status_code == run_fills.status_code == 200
        assert track_fills.json()["rows"] == run_fills.json()["rows"]


def test_invalid_alpha_output_preserves_combined_account_and_blocks_without_fallback(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    submitted = combined_command("invalid-alpha-seed")
    submitted.pop("formula")
    submitted.pop("neutralization")
    submitted["modules"]["alpha"] = {"kind": "python", "program": {
        "source": '''
def decide(context, state, parameters):
    signals = [{'instrument_id': item['instrument_id'], 'value': 1.0, 'valid_for_sessions': 2}
               for item in context['candidates']]
    if context['session'] == parameters['fail_session']:
        signals = 'invalid signal output'
    return {'output': {'reason': 'opportunities', 'signals': signals},
            'state': {'count': state.get('count', 0) + 1}}
''', "parameters": {"fail_session": SESSIONS[3]},
        "data_requirements": {"field_ids": [], "history_sessions": 1},
    }}
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed = client.post("/api/research-runs", json=submitted)
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        detail = client.get(f"/api/research-runs/{seed.json()['id']}").json()
        assert detail["status"] == "succeeded", detail
        risk = detail["result"]["terminal_strategy_state"]["decision_state"]["module_states"][
            "risk_management"
        ]
        assert risk["take_profit_cycles"] and risk["portfolio_drawdown"]
        tracked = client.post(f"/api/research-runs/{seed.json()['id']}/daily-tracks",
                              json={"request_id": "invalid-alpha-track"})
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        before = _stored_tracking_activation(settings, track_id)
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        response = client.post(f"/api/daily-tracks/{track_id}/refresh",
                               json={"request_id": "invalid-alpha-refresh"})
        assert response.status_code == 202, response.text
        with pytest.raises(DailyTrackProgressionFailed):
            runtime.daily_tracks.process_next()
        after = _stored_tracking_activation(settings, track_id)
        assert after["current_checkpoint_manifest_sha256"] == (
            before["current_checkpoint_manifest_sha256"]
        )
        assert after["terminal_strategy_state"] == before["terminal_strategy_state"]
        assert after["checkpoint_count"] == 1
        assert after["failed_attempt_count"] == 1
        assert runtime.daily_tracks.process_next() is False
        blocked = client.get(f"/api/daily-tracks/{track_id}").json()
        assert blocked["status"] == "blocked"
        assert "alpha" in blocked["blocked_reason"]


def test_expired_trading_events_preserve_combined_checkpoint_and_continuation(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed = client.post("/api/research-runs", json=combined_command("expiry-seed"))
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        run_id = seed.json()["id"]
        run_path = f"/api/research-runs/{run_id}"
        before_report = client.get(run_path).json()["result"]
        tracked = client.post(f"{run_path}/daily-tracks", json={"request_id": "expiry-track"})
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()["id"]
        before = _stored_tracking_activation(settings, track_id)
        with runtime.database.transaction() as tx:
            manifest = tx.execute(
                "SELECT result_manifest_sha256 FROM research_runs.runs WHERE id = %s",
                (run_id,),
            ).fetchone()["result_manifest_sha256"]
            updated = tx.execute(
                "UPDATE publication.payload_retention "
                "SET published_at = now() - interval '8 days', "
                "expires_at = now() - interval '1 day' WHERE manifest_sha256 = %s",
                (manifest,),
            )
            assert updated.rowcount == 1
        retention = PayloadRetention(runtime.database, runtime.publication)
        with runtime.database.transaction() as tx:
            assert retention.expire_one_in_transaction(tx)
        while runtime.publication.collect_one_pending_deletion():
            pass

        def retention_metadata():
            with runtime.database.transaction() as tx:
                return tx.execute(
                    "SELECT * FROM publication.payload_retention WHERE manifest_sha256 = %s",
                    (manifest,),
                ).fetchone()

        expired_metadata = retention_metadata()
        assert client.get(run_path).json()["result"] == before_report
        assert client.get(f"/api/daily-tracks/{track_id}").status_code == 200
        events = client.post(f"{run_path}/events/query", json={"section": "strategy_fills"})
        assert events.status_code == 200, events.text
        assert events.json()["status"] == "expired" and events.json()["rows"] == []
        assert retention_metadata() == expired_metadata
        assert _stored_tracking_activation(settings, track_id)["terminal_strategy_state"] == (
            before["terminal_strategy_state"]
        )
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        refresh = client.post(f"/api/daily-tracks/{track_id}/refresh",
                              json={"request_id": "expiry-refresh"})
        assert refresh.status_code == 202, refresh.text
        assert runtime.daily_tracks.process_next()
        after = _stored_tracking_activation(settings, track_id)
        assert after["checkpoint_count"] == 2
        reference = client.post("/api/research-runs", json=combined_command(
            "expiry-reference", end=SESSIONS[-1],
        ))
        assert reference.status_code == 202, reference.text
        assert runtime.research_runs.process_next()
        reference_track = client.post(f"/api/research-runs/{reference.json()['id']}/daily-tracks",
                                      json={"request_id": "expiry-reference-track"})
        assert reference_track.status_code == 201, reference_track.text
        expected = _stored_tracking_activation(settings, reference_track.json()["id"])
        assert after["terminal_strategy_state"] == expected["terminal_strategy_state"]
        assert retention_metadata() == expired_metadata


def test_combined_refresh_claim_keeps_frozen_dataset_when_head_moves(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed = client.post("/api/research-runs", json=combined_command("frozen-seed"))
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        track = client.post(f"/api/research-runs/{seed.json()['id']}/daily-tracks",
                            json={"request_id": "frozen-track"})
        assert track.status_code == 201, track.text
        track_id = track.json()["id"]
        frozen_head = _publish_head(settings, sessions=SESSIONS, price_offset=0,
                                    expected_manifest=head)
        reference = client.post("/api/research-runs", json=combined_command(
            "frozen-reference", end=SESSIONS[-1],
        ))
        assert reference.status_code == 202, reference.text
        assert runtime.research_runs.process_next()
        reference_track = client.post(f"/api/research-runs/{reference.json()['id']}/daily-tracks",
                                      json={"request_id": "frozen-reference-track"})
        assert reference_track.status_code == 201, reference_track.text
        expected = _stored_tracking_activation(settings, reference_track.json()["id"])

        def refresh(index):
            return client.post(f"/api/daily-tracks/{track_id}/refresh",
                               json={"request_id": f"concurrent-refresh-{index}"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(refresh, (1, 2)))
        assert sorted(response.status_code for response in responses) == [202, 409]
        observed = []

        def move_head(stage, current_track, generation):
            if stage != "claimed":
                return
            assert current_track == track_id and generation == frozen_head
            assert runtime.daily_tracks.process_next() is False
            assert refresh(3).status_code == 409
            observed.append(_publish_head(settings, sessions=SESSIONS, price_offset=9,
                                           expected_manifest=frozen_head))

        processor = DailyTrackService(
            runtime.database, publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount), progress=move_head,
        )
        assert processor.process_next()
        assert len(observed) == 1 and observed[0] != frozen_head
        actual = _stored_tracking_activation(settings, track_id)
        assert actual["checkpoint_count"] == 2
        assert actual["attempt_count"] == 1
        assert actual["succeeded_progression_count"] == 1
        assert actual["active_pin_count"] == 0
        assert actual["terminal_strategy_state"] == expected["terminal_strategy_state"]


def test_stop_after_combined_calculation_cannot_publish_new_account(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed = client.post("/api/research-runs", json=combined_command("stopped-seed"))
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        track = client.post(f"/api/research-runs/{seed.json()['id']}/daily-tracks",
                            json={"request_id": "stopped-track"})
        assert track.status_code == 201, track.text
        track_id = track.json()["id"]
        before = _stored_tracking_activation(settings, track_id)
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        refresh = client.post(f"/api/daily-tracks/{track_id}/refresh",
                              json={"request_id": "stopped-refresh"})
        assert refresh.status_code == 202, refresh.text
        observed = []

        def stop_prepared(stage, _track, _generation):
            if stage != "prepared":
                return
            response = client.post(f"/api/daily-tracks/{track_id}/stop",
                                   json={"request_id": "stop-before-commit"})
            assert response.status_code == 202, response.text
            observed.append(response.json()["status"])

        processor = DailyTrackService(
            runtime.database, publication=runtime.publication,
            dataset_lifecycle=DatasetLifecycle(runtime.database, settings.data_mount),
            generation_store=MountedGenerationStore(settings.data_mount), progress=stop_prepared,
        )
        assert processor.process_next()
        assert observed == ["stopping"]
        after = _stored_tracking_activation(settings, track_id)
        assert after["track_status"] == "stopped"
        assert after["terminal_strategy_state"] == before["terminal_strategy_state"]
        assert after["current_checkpoint_manifest_sha256"] == (
            before["current_checkpoint_manifest_sha256"]
        )
        assert after["checkpoint_count"] == 1
        assert after["cancelled_progression_count"] == 1
        assert after["active_pin_count"] == 0
        assert runtime.daily_tracks.process_next() is False
