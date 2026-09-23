import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import anyio
import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _publish_head,
    _stored_tracking_activation,
)
from test_core_research_agent_mcp_runs import _mcp_client
from test_python_direct_strategy import SESSIONS, SOURCE

from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.daily_track.models import DailyTrackOriginResultSectionInput
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_definition import default_simulation_costs

pytestmark = pytest.mark.skipif(
    not core_environment_is_configured(), reason="isolated Core runtime is not configured",
)

UNIVERSE = """
def decide(context, state, parameters):
    return {'output': {'reason': 'visible_candidates', 'instrument_ids': [
        item['instrument_id'] for item in context['candidates']]},
        'state': {'count': state.get('count', 0) + 1}}
"""
SIGNALS = """
def decide(context, state, parameters):
    return {'output': {'reason': 'fresh_opportunities', 'signals': [
        {'instrument_id': item['instrument_id'], 'value': 1.0, 'valid_for_sessions': 2}
        for item in context['candidates']]}, 'state': {'count': state.get('count', 0) + 1}}
"""
RISK = """
def decide(context, state, parameters):
    if context['session'] == parameters.get('fail_session'):
        raise ValueError('deliberate risk failure')
    return {'output': None, 'state': {'count': state.get('count', 0) + 1}}
"""


def command(request_id, *, end=SESSIONS[2], builtin_alpha=False, fail_session=None):
    modules = {
        stage: {'kind': 'python', 'program': {
            'source': source, 'parameters': {},
            'data_requirements': {'field_ids': [], 'history_sessions': 1},
        }}
        for stage, source in (
            ('universe_selection', UNIVERSE), ('alpha', SIGNALS),
            ('portfolio_construction', SOURCE), ('risk_management', RISK),
        )
    }
    modules['portfolio_construction']['program']['data_requirements']['field_ids'] = [
        'price.close.adjusted',
    ]
    if builtin_alpha:
        modules['alpha'] = 'alpha_formula/v1'
    if fail_session is not None:
        modules['risk_management']['program']['parameters'] = {'fail_session': fail_session}
    return {
        'request_id': request_id, 'folder_id': 'folder_default', 'name': 'Framework modules',
        'research_kind': 'strategy_backtest', 'strategy_mode': 'framework',
        'start_date': SESSIONS[0], 'end_date': end, 'universe': 'top300',
        'initial_cash_cny': '100000', 'modules': modules,
        **({'formula': '-close', 'neutralization': 'none'} if builtin_alpha else {}),
    }


def test_framework_track_origin_keeps_a_large_legal_module_state(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, sessions=SESSIONS[:2], price_offset=0)
    with TestClient(create_app(settings)) as client:
        submitted = command('large-framework-state', end=SESSIONS[1])
        submitted['modules']['risk_management']['program']['source'] = (
            "def decide(context, state, parameters):\n"
            "    return {'output': None, 'state': {'payload': 'x' * 200000}}"
        )
        admitted = client.post('/api/research-runs', json=submitted)
        assert admitted.status_code == 202, admitted.text
        run_id = admitted.json()['id']
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next()
        response = client.get(f'/api/research-runs/{run_id}')
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail['status'] == 'succeeded', detail
        tracked = client.post(
            f'/api/research-runs/{run_id}/daily-tracks',
            json={'request_id': 'large-state-track'},
        )
        assert tracked.status_code == 201, tracked.text
        origin = runtime.daily_tracks.get_result_section(
            TEST_RESEARCHER.researcher_id,
            DailyTrackOriginResultSectionInput(track_id=tracked.json()['id'], section='origin'),
        )
        assert origin.terminal_account.decision_state.module_states['risk_management'] == {
            'payload': 'x' * 200000,
        }
        mcp_result = anyio.run(
            _get_origin_through_mcp, settings, tracked.json()['id'],
            tmp_path / 'framework-origin-mcp.stderr.log',
        )
        assert not mcp_result.is_error
        assert (mcp_result.structured_content['terminal_account']['decision_state']
                ['module_states']['risk_management']) == {'payload': 'x' * 200000}
        assert json.loads(mcp_result.content[0].text) == mcp_result.structured_content


async def _get_origin_through_mcp(settings, track_id, stderr_path):
    async with _mcp_client(settings, stderr_path) as mcp:
        return await mcp.call_tool(
            'get_daily_track_result', {'track_id': track_id, 'section': 'origin'},
        )


@pytest.mark.parametrize('builtin_alpha,builtin_risk,holding_periods,take_profit', [
    (False, False, False, False), (True, False, False, False),
    (False, True, False, False), (True, True, False, False),
    (True, True, True, False), (True, True, False, True),
])
def test_framework_run_reuse_and_track_preserve_frozen_modules_and_account(
    tmp_path, builtin_alpha, builtin_risk, holding_periods, take_profit,
):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        submitted = command('framework-run', builtin_alpha=builtin_alpha)
        if builtin_risk:
            submitted['modules']['risk_management'] = {
                'kind': 'builtin_risk/v1', 'stop_loss_threshold': 0.01,
            }
        if holding_periods:
            submitted['modules']['portfolio_construction'] = {
                'kind': 'periodic_top_n/v1', 'minimum_holding_sessions': 2,
            }
            submitted['modules']['risk_management']['maximum_holding_sessions'] = 3
            submitted.update(holdings_count=1, selection_every_sessions=1,
                             weighting='equal_weight', volatility_window=20,
                             exposure_expression='1')
        if take_profit:
            submitted['modules']['risk_management'] = {
                'kind': 'builtin_risk/v1', 'take_profit_tiers': [
                    {'profit_threshold': 0.0001, 'cumulative_reduction': 0.3},
                    {'profit_threshold': 0.5, 'cumulative_reduction': 0.6},
                ],
            }
        costs = {**default_simulation_costs().model_dump(),
                 'commission_min_cny': '2',
                 'slippage_bps': '0' if take_profit else ('1000' if builtin_risk else '15')}
        submitted['costs'] = costs
        diagnosed = client.post('/api/research/diagnostics', json={
            key: value for key, value in submitted.items()
            if key not in {'request_id', 'folder_id', 'name'}
        })
        assert diagnosed.status_code == 200, diagnosed.text
        assert diagnosed.json()['valid'], diagnosed.text
        admitted = client.post('/api/research-runs', json=submitted)
        assert admitted.status_code == 202, admitted.text
        run_id = admitted.json()['id']
        assert runtime.research_runs.process_next()
        response = client.get(f'/api/research-runs/{run_id}')
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail['status'] == 'succeeded', detail
        assert detail['input']['modules'] == submitted['modules']
        assert detail['input']['costs'] == costs
        assert ('holdings_count' in detail['input']) == holding_periods
        expected = {stage: {'count': 3} for stage in submitted['modules']}
        if builtin_alpha:
            expected['alpha'] = {}
        if builtin_risk:
            expected['risk_management'] = {}
        actual_states = (
            detail['result']['terminal_strategy_state']['decision_state']['module_states']
        )
        if take_profit:
            cycles = actual_states['risk_management']['take_profit_cycles']
            assert cycles
            assert any(float(cycle['executed_reduction_units']) > 0 for cycle in cycles.values())
            expected['risk_management'] = actual_states['risk_management']
        if holding_periods:
            assert (actual_states['portfolio_construction']['selection']['signal_session']
                    == SESSIONS[2])
            expected['portfolio_construction'] = actual_states['portfolio_construction']
        assert actual_states == expected
        event_path = f'/api/research-runs/{run_id}/events/query'
        events = client.post(event_path, json={'section': 'strategy_framework', 'limit': 50})
        assert events.status_code == 200, events.text
        original_events = events.json()['rows']
        assert [row['decision_session'] for row in original_events] == list(SESSIONS[:3])
        assert original_events[0]['universe']['reason'] == 'visible_candidates'
        assert original_events[0]['alpha']['kind'] == ('formula' if builtin_alpha else 'signals')
        assert original_events[0]['risk_adjustment'] is None
        if builtin_risk and not take_profit:
            triggered = original_events[1]['risk_adjustment']
            assert triggered['mode'] == 'holding_risk'
            assert triggered['observations'][0]['holding_age'] == 1
            assert triggered['observations'][0]['stop_loss_threshold'] == '1e-2'
            assert detail['result']['terminal_strategy_state']['positions'] == []
        if take_profit:
            observation = original_events[1]['risk_adjustment']['observations'][0]
            assert observation['reason'] == 'take_profit'
            assert observation['cumulative_reduction'] == '3e-1'
            assert float(observation['remaining_reduction_units']) > 0
        if holding_periods:
            retention = original_events[1]['portfolio_retentions'][0]
            assert retention['holding_age'] == 1
            assert retention['minimum_holding_sessions'] == 2
        for row in original_events:
            if row['target_id'] is not None:
                target = client.post(event_path, json={
                    'section': 'strategy_targets', 'target_id': row['target_id'],
                })
                assert target.status_code == 200, target.text
                assert target.json()['rows'][0]['decision_session'] == row['decision_session']
        reused = deepcopy(detail['input'])
        reused['costs']['slippage_bps'] = '25'
        if holding_periods:
            reused['modules']['portfolio_construction']['minimum_holding_sessions'] = 1
        else:
            reused['modules']['portfolio_construction']['program']['parameters']['edited'] = True
        response = client.post('/api/research-runs', json={
            **reused, 'request_id': 'reuse', 'folder_id': 'folder_default',
        })
        assert response.status_code == 202, response.text
        assert runtime.research_runs.process_next()
        reused_detail = client.get(f"/api/research-runs/{response.json()['id']}").json()
        assert reused_detail['status'] == 'succeeded', reused_detail
        assert reused_detail['input']['costs']['slippage_bps'] == '25'
        assert client.get(f'/api/research-runs/{run_id}').json()['input']['costs'] == costs
        assert client.get(f'/api/research-runs/{run_id}').json()['input']['modules'] == (
            submitted['modules']
        )
        tracked = client.post(
            f'/api/research-runs/{run_id}/daily-tracks', json={'request_id': 'track'},
        )
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()['id']
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        response = client.post(
            f'/api/daily-tracks/{track_id}/refresh', json={'request_id': 'advance'},
        )
        assert response.status_code == 202, response.text
        assert runtime.daily_tracks.process_next()
        track = client.get(f'/api/daily-tracks/{track_id}').json()
        for ordinal in range(1, len(SESSIONS) + 1):
            if track['strategy_session'] == SESSIONS[-1]:
                break
            continuation = client.post(
                f'/api/daily-tracks/{track_id}/refresh',
                json={'request_id': f'advance-{ordinal}'},
            )
            assert continuation.status_code == 202, continuation.text
            assert runtime.daily_tracks.process_next()
            track = client.get(f'/api/daily-tracks/{track_id}').json()
        assert track['strategy_session'] == SESSIONS[-1], track
        full = client.post('/api/research-runs', json={
            **submitted, 'request_id': 'full', 'end_date': SESSIONS[-1],
        })
        assert full.status_code == 202, full.text
        assert runtime.research_runs.process_next()
        full_result = client.get(f"/api/research-runs/{full.json()['id']}").json()
        assert full_result['status'] == 'succeeded', full_result
        terminal = full_result['result']['terminal_strategy_state']
        assert track['observation']['net_asset_value_cny'] == terminal['net_nav']
        assert track['observation']['decision_state'] == terminal['decision_state']
        track_events = client.post(f'/api/daily-tracks/{track_id}/events/query', json={
            'section': 'strategy_framework', 'limit': 50,
        })
        full_events = client.post(f"/api/research-runs/{full.json()['id']}/events/query", json={
            'section': 'strategy_framework', 'limit': 50,
        })
        assert track_events.status_code == full_events.status_code == 200
        assert track_events.json()['rows'] == full_events.json()['rows']
        assert track_events.json()['rows'][:3] == original_events
        track_fills = client.post(f'/api/daily-tracks/{track_id}/events/query', json={
            'section': 'strategy_fills', 'limit': 50,
        })
        full_fills = client.post(f"/api/research-runs/{full.json()['id']}/events/query", json={
            'section': 'strategy_fills', 'limit': 50,
        })
        assert track_fills.status_code == full_fills.status_code == 200
        assert track_fills.json()['rows']
        assert track_fills.json()['rows'] == full_fills.json()['rows']
        assert runtime.research_runs.get_detail(UUID(int=1234), run_id) is None
        assert runtime.daily_tracks.get(UUID(int=1234), track_id) is None


@pytest.mark.parametrize('builtin_alpha', [False, True])
def test_framework_batch_failure_keeps_sibling_module_state_independent(tmp_path, builtin_alpha):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        good = command('good', builtin_alpha=builtin_alpha)
        bad = command('bad', builtin_alpha=builtin_alpha, fail_session=SESSIONS[1])
        batch = client.post('/api/research-batches', json={
            'batch_kind': 'strategy_sweep', 'request_id': 'modules',
            'start_date': SESSIONS[0], 'end_date': SESSIONS[2], 'universe': 'top300',
            **({'alpha': {'formula': '-close'}, 'neutralization': 'none'} if builtin_alpha else {}),
            'strategies': [{
                'item_key': key, **{name: item[name] for name in (
                    'strategy_mode', 'initial_cash_cny', 'modules',
                )},
            } for key, item in [('good', good), ('bad', bad)]],
        })
        assert batch.status_code == 202, batch.text
        assert runtime.research_batches.process_next()
        detail = client.get(f"/api/research-batches/{batch.json()['id']}").json()
        assert detail['status'] == 'completed_with_failures', detail
        items = {item['item_key']: item for item in detail['items']}
        assert items['good']['status'] == 'succeeded'
        assert items['bad']['status'] == 'failed'
        assert 'risk_management' in items['bad']['diagnostic']['message']
        assert SESSIONS[1] in items['bad']['diagnostic']['message']
        good_run = client.get(f"/api/research-runs/{items['good']['research_run_id']}").json()
        bad_run = client.get(f"/api/research-runs/{items['bad']['research_run_id']}").json()
        assert 'result' not in bad_run
        standalone = client.post('/api/research-runs', json=good)
        assert standalone.status_code == 202, standalone.text
        assert runtime.research_runs.process_next()
        reference = client.get(f"/api/research-runs/{standalone.json()['id']}").json()
        assert reference['status'] == 'succeeded', reference
        assert good_run['result']['terminal_strategy_state'] == (
            reference['result']['terminal_strategy_state']
        )


def test_framework_failed_refresh_does_not_replace_the_authoritative_head(tmp_path):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed = client.post('/api/research-runs', json=command(
            'failing-track-seed', fail_session=SESSIONS[3],
        ))
        assert seed.status_code == 202, seed.text
        assert runtime.research_runs.process_next()
        tracked = client.post(
            f"/api/research-runs/{seed.json()['id']}/daily-tracks", json={'request_id': 'track'},
        )
        assert tracked.status_code == 201, tracked.text
        track_id = tracked.json()['id']
        before = _stored_tracking_activation(settings, track_id)
        _publish_head(settings, sessions=SESSIONS, price_offset=0, expected_manifest=head)
        response = client.post(
            f'/api/daily-tracks/{track_id}/refresh', json={'request_id': 'failed-advance'},
        )
        assert response.status_code == 202, response.text
        with pytest.raises(DailyTrackProgressionFailed):
            runtime.daily_tracks.process_next()
        after = _stored_tracking_activation(settings, track_id)
        assert after['current_checkpoint_manifest_sha256'] == (
            before['current_checkpoint_manifest_sha256']
        )
        assert after['terminal_strategy_state'] == before['terminal_strategy_state']
        assert after['checkpoint_count'] == 1
        assert after['failed_attempt_count'] == 1
        detail = client.get(f'/api/daily-tracks/{track_id}').json()
        assert detail['status'] == 'blocked', detail
        assert 'risk_management' in detail['blocked_reason']
