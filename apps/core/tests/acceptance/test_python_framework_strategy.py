from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from test_core_current_head_research_run_execution import (
    _publish_head,
    _stored_tracking_activation,
)
from test_python_direct_strategy import SESSIONS, SOURCE

from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core

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


@pytest.mark.parametrize('builtin_alpha', [False, True])
def test_framework_run_reuse_and_track_preserve_frozen_modules_and_account(tmp_path, builtin_alpha):
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    head = _publish_head(settings, sessions=SESSIONS[:3], price_offset=0)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        submitted = command('framework-run', builtin_alpha=builtin_alpha)
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
        detail = client.get(f'/api/research-runs/{run_id}').json()
        assert detail['status'] == 'succeeded', detail
        assert detail['input']['modules'] == submitted['modules']
        assert 'holdings_count' not in detail['input']
        expected = {stage: {'count': 3} for stage in submitted['modules']}
        if builtin_alpha:
            expected['alpha'] = {}
        assert detail['result']['terminal_strategy_state']['decision_state']['module_states'] == (
            expected
        )
        reused = deepcopy(detail['input'])
        reused['modules']['portfolio_construction']['program']['parameters']['edited'] = True
        response = client.post('/api/research-runs', json={
            **reused, 'request_id': 'reuse', 'folder_id': 'folder_default',
        })
        assert response.status_code == 202, response.text
        assert runtime.research_runs.process_next()
        reused_detail = client.get(f"/api/research-runs/{response.json()['id']}").json()
        assert reused_detail['status'] == 'succeeded', reused_detail
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
        assert track['strategy_session'] == SESSIONS[-1], track
        full = client.post('/api/research-runs', json=command(
            'full', end=SESSIONS[-1], builtin_alpha=builtin_alpha,
        ))
        assert full.status_code == 202, full.text
        assert runtime.research_runs.process_next()
        full_result = client.get(f"/api/research-runs/{full.json()['id']}").json()
        assert full_result['status'] == 'succeeded', full_result
        terminal = full_result['result']['terminal_strategy_state']
        assert track['observation']['net_asset_value_cny'] == terminal['net_nav']
        assert track['observation']['decision_state'] == terminal['decision_state']
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
