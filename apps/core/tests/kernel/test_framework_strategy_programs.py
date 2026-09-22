import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from textwrap import indent
from time import monotonic

import pytest
from test_direct_strategy_execution import inputs
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _definition

from thesistrace.research_kernel.daily_strategy import prepare_daily_strategy
from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_kernel.strategy_program_runtime import StrategyProgramError
from thesistrace.research_series import slice_research_sessions

pytestmark = pytest.mark.bounded_process


def framework_inputs():
    data, direct = inputs()
    definition = _definition(selection_interval=5)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = direct["costs"]
    definition["strategy"]["environment"] = direct["strategy"]["environment"]
    definition["strategy"]["modules"]["portfolio_construction"] = {
        "kind": "python", "program": deepcopy(direct["strategy"]["program"]),
    }
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    return data, definition, matrix, direct


def test_framework_portfolio_program_matches_direct_condition_triggered_execution():
    data, definition, matrix, direct = framework_inputs()
    expected = transition_strategy(data, None, direct, origin_session=SESSIONS[0]).finalized
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized

    assert [(row["session"], row["instrument_id"], row["side"], row["quantity"])
            for row in result["fills"]] == [
        (SESSIONS[1], A, "buy", 10000),
        (SESSIONS[2], A, "sell", 10000),
        (SESSIONS[2], B, "buy", 10000),
    ]
    assert result["daily"] == expected["daily"]
    assert result["positions"] == expected["positions"]
    assert Decimal(result["daily"][-1]["net_nav"]) == Decimal("200000")
    assert result["decision_state"]["module_states"]["portfolio_construction"] == {"count": 4}
    assert result["pending_target"]["allocation"] == expected["pending_target"]["allocation"]
    assert result["pending_target"]["decision_session"] == SESSIONS[-1]


def python_module(source, *, parameters=None):
    return {"kind": "python", "program": {
        "source": source, "parameters": parameters or {},
        "data_requirements": {"field_ids": [], "history_sessions": 1},
    }}


def test_framework_module_observations_exclude_future_data_and_other_modules_fields():
    data, definition, matrix, _ = framework_inputs()
    financial = "financial.income.total_revenue.latest_fy"
    data.fields[financial] = {(day, item): "100" for day in SESSIONS for item in (A, B)}
    modules = definition["strategy"]["modules"]
    modules["portfolio_construction"] = python_module("""
def decide(context, state, parameters):
    history = context['history']
    return {'output': None, 'state': {'history': {
        'sessions': list(history['sessions']), 'instruments': list(history['instruments']),
        'fields': {key: [list(row) for row in values]
                   for key, values in history['fields'].items()}},
        'candidates': [dict(row) for row in context['candidates']]}}
""")
    modules["portfolio_construction"]["program"]["data_requirements"] = {
        "field_ids": ["price.close.adjusted", financial], "history_sessions": 2,
    }
    modules["risk_management"] = python_module("""
def decide(context, state, parameters):
    assert not context['history']['fields']
    return {'output': None, 'state': {}}
""")
    altered = deepcopy(data)
    future = "equity:future.SH"
    altered.instruments[future] = replace(data.instruments[A], board="star")
    altered.instruments[A] = replace(data.instruments[A], listed_to="2099-01-02")
    for day in SESSIONS[2:]:
        altered.universe_members[day] = (future,)
        altered.fields["price.close.adjusted"][(day, A)] = "999999"
        altered.fields[financial][(day, A)] = "999999"
        altered.industries[(day, A)] = "future-industry"
    altered.fields["undeclared"] = {(SESSIONS[1], A): "123"}

    def observe(dataset):
        policy = prepare_daily_strategy(dataset, matrix, definition)
        return policy.decide(
            session=SESSIONS[1], report_index=0, account={"positions": []},
            fills=[], rejections=[], previous=None,
        )

    before, after = observe(data), observe(altered)
    assert before == after
    observed = before.state["module_states"]["portfolio_construction"]
    assert observed["history"]["sessions"] == list(SESSIONS[:2])
    assert observed["history"]["fields"][financial] == [[100, 100], [100, 100]]
    assert all("listed_to" not in row for row in observed["candidates"])
    assert future not in str(observed)


@pytest.mark.parametrize("replacement", [None, B])
def test_framework_risk_explicitly_replaces_or_cancels_the_portfolio(replacement):
    data, definition, matrix, _ = framework_inputs()
    definition["strategy"]["modules"]["risk_management"] = python_module("""
def decide(context, state, parameters):
    item = parameters['replacement']
    target = None if item is None else {
        'reason': 'replacement_portfolio', 'allocation': {
            'mode': 'rebalance', 'instrument_ids': [item],
            'relative_weights': {item: '1'}, 'exposure': 1.0}, 'position_limits': {}}
    return {'output': {'mode': 'replace', 'reason': 'explicit_override', 'target': target},
            'state': {}}
""", parameters={"replacement": replacement})
    result = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    ).finalized
    assert [(row["instrument_id"], row["side"], row["quantity"])
            for row in result["fills"]] == ([] if replacement is None else [(B, "buy", 10000)])
    assert result["decision_state"]["retained_proposal"]["allocation"]["instrument_ids"] == (
        [B] if replacement is None else [A]
    )
    assert (result["pending_target"] is None) is (replacement is None)


@pytest.mark.parametrize("stage", [
    "universe_selection", "alpha", "portfolio_construction", "risk_management",
])
def test_each_framework_module_uses_the_actual_isolated_guest(stage, tmp_path, monkeypatch):
    data, definition, matrix, _ = framework_inputs()
    definition["strategy"]["modules"]["portfolio_construction"] = "periodic_top_n/v1"
    paths = [tmp_path / name for name in ("host", "dataset", "other-researcher")]
    for path in paths:
        path.write_text("private sentinel")
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "private credential")
    definition["strategy"]["modules"][stage] = python_module("""
import os
def decide(context, state, parameters):
    denied = []
    for path in parameters['paths']:
        try:
            open(path).read()
        except OSError:
            denied.append(path)
    try:
        import socket
        network = True
    except ImportError:
        network = False
    try:
        context['account']['cash_cny'] = '999999'
        writable = True
    except TypeError:
        writable = False
    return {'output': None, 'state': {
        'denied': denied, 'network': network, 'writable': writable,
        'credential': os.environ.get('THESISTRACE_DATABASE_URL')}}
""", parameters={"paths": [str(path) for path in paths]})
    result = transition_strategy(
        slice_research_sessions(data, SESSIONS[:1]), matrix, definition,
        origin_session=SESSIONS[0],
    ).finalized
    assert result["decision_state"]["module_states"][stage] == {
        "denied": [str(path) for path in paths], "network": False, "writable": False,
        "credential": None,
    }
    assert Decimal(result["daily"][0]["net_cash"]) == Decimal("100000")
    assert [path.read_text() for path in paths] == ["private sentinel"] * 3


@pytest.mark.parametrize("body", [
    "while True:\n    pass",
    "bytearray(512 * 1024 * 1024)",
    "return {'output': None, 'state': {'large': 'x' * (300 * 1024)}}",
])
def test_framework_resource_failure_is_bounded_and_the_next_strategy_succeeds(body):
    data, definition, matrix, _ = framework_inputs()
    bounded = slice_research_sessions(data, SESSIONS[:1])
    definition["strategy"]["modules"]["risk_management"] = python_module(
        "def decide(context, state, parameters):\n" + indent(body, "    "),
    )
    started = monotonic()
    with pytest.raises(StrategyProgramError, match="risk_management") as caught:
        transition_strategy(bounded, matrix, definition, origin_session=SESSIONS[0])
    assert monotonic() - started < 20
    assert caught.value.session == SESSIONS[0]
    definition["strategy"]["modules"]["risk_management"] = python_module(
        "def decide(context, state, parameters):\n"
        "    return {'output': None, 'state': {'ok': True}}",
    )
    result = transition_strategy(bounded, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert result["decision_state"]["module_states"]["risk_management"] == {"ok": True}


def test_signal_expiry_is_a_portfolio_input_not_an_automatic_exit():
    data, definition, _, _ = framework_inputs()
    modules = definition["strategy"]["modules"]
    modules["universe_selection"] = python_module("""
def decide(context, state, parameters):
    item = parameters['a'] if context['completed_sessions'] < 4 else parameters['b']
    return {'output': {'reason': 'selected_candidates', 'instrument_ids': [item]},
            'state': {}}
""", parameters={"a": A, "b": B})
    modules["alpha"] = python_module("""
def decide(context, state, parameters):
    output = None
    if context['completed_sessions'] in (1, 4):
        output = {'reason': 'new_signal', 'signals': [{
            'instrument_id': context['framework']['universe'][0],
            'value': 1.0, 'valid_for_sessions': 2}]}
    return {'output': output, 'state': {'count': state.get('count', 0) + 1}}
""")
    modules["portfolio_construction"] = python_module("""
def decide(context, state, parameters):
    framework = context['framework']
    state.setdefault('expired', []).extend(framework['expired_signals'])
    state.setdefault('updates', []).append(framework['signals_updated'])
    output = None
    if framework['signals_updated'] and framework['signals']:
        item = framework['signals'][0]['instrument_id']
        output = {'reason': 'signal_change', 'allocation': {
            'mode': 'rebalance', 'instrument_ids': [item],
            'relative_weights': {item: '1'}, 'exposure': 1.0}, 'position_limits': {}}
    return {'output': output, 'state': state}
""")
    result = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    assert [(row["session"], row["instrument_id"], row["side"])
            for row in result["fills"]] == [(SESSIONS[1], A, "buy")]
    assert result["positions"][0]["instrument_id"] == A
    assert result["pending_target"]["allocation"]["instrument_ids"] == [B]
    state = result["decision_state"]
    assert state["universe"] == [B]
    assert state["module_states"]["alpha"] == {"count": 4}
    assert state["module_states"]["portfolio_construction"] == {
        "expired": [A], "updates": [True, False, False, True],
    }
    assert state["signals"] == [{
        "instrument_id": B, "value": 1.0, "created_session": SESSIONS[3],
        "created_session_number": 4, "valid_for_sessions": 2,
    }]
    # Resume just before the signal expires in a fresh interpreter and guest.
    # No event log or Python heap crosses this continuation boundary.
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), None, definition,
        origin_session=SESSIONS[0],
    ).resumable
    script = """
import json, sys
payload = json.load(sys.stdin)
sys.path[:0] = payload['paths']
from test_framework_strategy_programs import framework_inputs, SESSIONS
from thesistrace.research_kernel.strategy import transition_strategy
data, _, _, _ = framework_inputs()
result = transition_strategy(data, None, payload['definition'], origin_session=SESSIONS[0],
                             continuation=payload['continuation']).finalized
print(json.dumps(result))
"""
    recovered = subprocess.run(
        [sys.executable, "-c", script], input=json.dumps({
            "paths": sys.path, "definition": definition, "continuation": prefix,
        }), text=True, capture_output=True, timeout=60, check=True,
    )
    assert json.loads(recovered.stdout) == result


def test_framework_risk_runs_without_a_new_portfolio_and_only_exits_a():
    data, definition, matrix, _ = framework_inputs()
    c = "equity:600003.SH"
    data.instruments[c] = data.instruments[B]
    for session in SESSIONS:
        data.universe_members[session] = (A, B, c)
        data.historical_universe_members[session] = (A, B, c)
        for values in data.fields.values():
            if (session, B) in values:
                values[(session, c)] = values[(session, B)]
        for values in (data.execution_prices, data.trading_states, data.price_limits):
            values[(session, c)] = values[(session, B)]
    definition["strategy"]["modules"]["portfolio_construction"] = python_module("""
def decide(context, state, parameters):
    output = None
    if context['completed_sessions'] == 1:
        ids = parameters['ids']
        output = {'reason': 'initial_portfolio', 'allocation': {
            'mode': 'rebalance', 'instrument_ids': list(ids),
            'relative_weights': {item: '1/3' for item in ids}, 'exposure': 1.0},
            'position_limits': {}}
    return {'output': output, 'state': {}}
""", parameters={"ids": [A, B, c]})
    definition["strategy"]["modules"]["risk_management"] = python_module("""
def decide(context, state, parameters):
    output = None
    if context['completed_sessions'] == 3:
        assert context['framework']['proposal'] is None
        assert context['framework']['retained_proposal'] is not None
        assert len(context['account']['positions']) == 3
        output = {'mode': 'limit_positions', 'reason': 'exit_a',
                  'position_limits': {parameters['a']: 0}}
    return {'output': output, 'state': {'count': state.get('count', 0) + 1}}
""", parameters={"a": A})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(row["session"], row["instrument_id"], row["side"], row["quantity"])
            for row in result["fills"]] == [
        (SESSIONS[1], A, "buy", 3300), (SESSIONS[1], B, "buy", 3300),
        (SESSIONS[1], c, "buy", 3300), (SESSIONS[3], A, "sell", 3300),
    ]
    assert {row["instrument_id"]: row["execution_shares"]
            for row in result["positions"]} == {B: 3300, c: 3300}
    assert Decimal(result["daily"][-1]["net_cash"]) == Decimal("34000")
    assert result["pending_target"] is None
    assert result["decision_state"]["module_states"]["risk_management"] == {"count": 4}


def test_builtin_portfolio_keeps_its_interval_when_custom_signals_change_daily():
    data, definition, _, _ = framework_inputs()
    modules = definition["strategy"]["modules"]
    modules["portfolio_construction"] = "periodic_top_n/v1"
    modules["alpha"] = python_module("""
def decide(context, state, parameters):
    item = parameters['a'] if context['completed_sessions'] == 1 else parameters['b']
    return {'output': {'reason': 'daily_signal', 'signals': [{
        'instrument_id': item, 'value': 1.0, 'valid_for_sessions': 1}]}, 'state': {}}
""", parameters={"a": A, "b": B})
    modules["risk_management"] = python_module("""
def decide(context, state, parameters):
    return {'output': None, 'state': {'count': state.get('count', 0) + 1}}
""")
    result = transition_strategy(data, None, definition, origin_session=SESSIONS[0]).finalized
    assert [(row["session"], row["instrument_id"], row["side"], row["quantity"])
            for row in result["fills"]] == [(SESSIONS[1], A, "buy", 10000)]
    assert result["pending_target"] is None
    assert result["decision_state"]["signals"][0]["instrument_id"] == B
    assert result["decision_state"]["module_states"]["risk_management"] == {"count": 4}


def test_invalid_risk_increase_cannot_be_hidden_by_a_stricter_portfolio_cap():
    data, definition, matrix, _ = framework_inputs()
    definition["strategy"]["modules"]["portfolio_construction"] = python_module("""
def decide(context, state, parameters):
    item = parameters['a']
    if context['completed_sessions'] == 1:
        output = {'reason': 'enter', 'allocation': {
            'mode': 'rebalance', 'instrument_ids': [item],
            'relative_weights': {item: '1'}, 'exposure': 1.0}, 'position_limits': {}}
    else:
        output = {'reason': 'exit', 'allocation': None, 'position_limits': {item: 0}}
    return {'output': output, 'state': {}}
""", parameters={"a": A})
    definition["strategy"]["modules"]["risk_management"] = python_module("""
def decide(context, state, parameters):
    output = None
    if context['account']['positions']:
        output = {'mode': 'limit_positions', 'reason': 'invalid_increase',
                  'position_limits': {parameters['a']: 10001}}
    return {'output': output, 'state': {}}
""", parameters={"a": A})
    with pytest.raises(StrategyProgramError, match="risk_management.*reduce an actual holding"):
        transition_strategy(
            slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
            origin_session=SESSIONS[0],
        )


@pytest.mark.parametrize("custom_alpha", [False, True])
def test_framework_programs_survive_public_kernel_run_and_advance(custom_alpha):
    from thesistrace.daily_track.checkpoint import (
        project_tracking_checkpoint,
        restore_tracking_checkpoint,
    )
    from thesistrace.daily_track.observation_state import (
        TrackingObservationState,
        initial_tracking_observation_state,
    )
    from thesistrace.research_kernel import (
        AdvanceInput,
        advance,
        continuation_snapshot,
        run,
    )
    from thesistrace.research_series import slice_research_sessions

    data, request = framework_run_input(custom_alpha=custom_alpha)
    whole = run(request)
    expected = whole.artifacts_snapshot()
    assert ("alpha_matrix" in expected) is not custom_alpha
    prefix = run(request.with_research_data(
        slice_research_sessions(data, SESSIONS[:2]), research_end_session=SESSIONS[1],
    )).track_state
    continued = advance(AdvanceInput(
        prior_state=prefix, target_research_data=data, appended_sessions=list(SESSIONS[2:]),
        continuation=continuation_snapshot(prefix), calculation_scope="research_period",
    ))
    assert continued.output_snapshot() == expected
    state = expected["strategy_backtest"]["decision_state"]
    assert state["module_states"]["portfolio_construction"] == {"count": 4}
    initial = initial_tracking_observation_state(SESSIONS[0], "100000")
    checkpoint = project_tracking_checkpoint(
        prefix, retained_strategy_sessions=SESSIONS[1:2], prior_observation_state=initial,
    )
    restored = restore_tracking_checkpoint(
        checkpoint, research_data=slice_research_sessions(data, SESSIONS[:2]),
    )
    recovered = advance(AdvanceInput(
        prior_state=restored, target_research_data=data, appended_sessions=list(SESSIONS[2:]),
        continuation=continuation_snapshot(restored), calculation_scope="forward_tracking",
    ))
    recovered_checkpoint = project_tracking_checkpoint(
        recovered, retained_strategy_sessions=SESSIONS[2:],
        prior_observation_state=TrackingObservationState.model_validate(
            checkpoint["tracking_observation_state"],
        ),
    )
    full_checkpoint = project_tracking_checkpoint(
        whole.track_state, retained_strategy_sessions=SESSIONS[1:], prior_observation_state=initial,
    )
    assert (recovered_checkpoint["strategy_state"]["terminal"]
            == full_checkpoint["strategy_state"]["terminal"])


def framework_run_input(*, custom_alpha=False, builtin_portfolio=False, exposure_source=None):
    from contracts import CLOSE_ADJUSTED, FIELD_BINDINGS

    from thesistrace.alpha_language import alpha_language
    from thesistrace.research_kernel import RunInput, StrategyRunInput
    from thesistrace.research_kernel.serialization import canonical_json_bytes

    data, definition, _, _ = framework_inputs()
    strategy = definition["strategy"]
    if builtin_portfolio:
        strategy["modules"]["portfolio_construction"] = "periodic_top_n/v1"
        strategy["modules"]["risk_management"] = python_module(
            "def decide(context, state, parameters):\n    return {'output': None, 'state': {}}",
        )
    if custom_alpha:
        strategy["modules"]["alpha"] = python_module(
            "def decide(context, state, parameters):\n    return {'output': None, 'state': {}}",
        )
    exposure = (alpha_language.compile(exposure_source, context="exposure")
                if exposure_source else None)
    lookback = exposure.effective_lookback if exposure else 0
    return data, RunInput(
        research_data=data, alpha_expression=None if custom_alpha else CLOSE_ADJUSTED,
        field_bindings=FIELD_BINDINGS,
        effective_lookback=lookback, universe="manual",
        neutralization=None if custom_alpha else "none",
        research_kind="strategy_backtest",
        strategy=StrategyRunInput(
            holdings_count=1 if builtin_portfolio else None,
            selection_interval=5 if builtin_portfolio else None, initial_cash_cny="100000",
            modules_json=canonical_json_bytes(strategy["modules"]),
            environment_json=canonical_json_bytes(strategy["environment"]),
            exposure_expression_json=(canonical_json_bytes(exposure.expression)
                                      if exposure else None),
            **definition["costs"],
        ),
        research_start_session=SESSIONS[lookback], research_end_session=SESSIONS[-1],
    )


@pytest.mark.parametrize("columnar", [False, True])
@pytest.mark.parametrize("custom_alpha", [False, True])
def test_framework_preserves_common_exposure_evidence_across_run_and_tracking(
    columnar, custom_alpha,
):
    from functools import partial

    from thesistrace.daily_track.checkpoint import (
        project_tracking_checkpoint,
        restore_tracking_checkpoint,
    )
    from thesistrace.daily_track.models import KernelStateCheckpoint
    from thesistrace.daily_track.observation_state import (
        TrackingObservationState,
        initial_tracking_observation_state,
    )
    from thesistrace.research_kernel import AdvanceInput, advance, continuation_snapshot, run
    from thesistrace.research_kernel.kernel_run import run_columnar_chunk
    from thesistrace.research_kernel.tracking_advance import advance_tracking

    data, request = framework_run_input(
        custom_alpha=custom_alpha, builtin_portfolio=True,
        exposure_source="universe_advancing_fraction()",
    )
    if columnar:
        import numpy as np
        from test_research_chunk_continuation import _ColumnarFixture

        data = _ColumnarFixture(
            sessions=data.sessions, instruments=data.instruments,
            universe_members=data.universe_members, industries=data.industries,
            execution_prices=data.execution_prices, trading_states=data.trading_states,
            price_limits=data.price_limits,
            matrices={field: np.asarray([
                [float(values.get((session, item), "nan")) for session in data.sessions]
                for item in data.instruments
            ]) for field, values in data.fields.items()},
        )
        request = request.with_research_data(data)
    calculate = partial(run_columnar_chunk, cancellation_check=lambda: None) if columnar else run
    whole = calculate(request)
    initial = initial_tracking_observation_state(SESSIONS[0], "100000")
    checkpoint = project_tracking_checkpoint(
        whole.track_state, retained_strategy_sessions=SESSIONS[1:], prior_observation_state=initial,
    )
    observations = checkpoint["common_input_observations"]
    assert [(row["session"], row["identifier"], row["value"], row["valid_count"])
            for row in observations] == [
        (SESSIONS[1], "universe_advancing_fraction", 0.5, 2),
        (SESSIONS[2], "universe_advancing_fraction", 0.0, 2),
        (SESSIONS[3], "universe_advancing_fraction", 0.5, 2),
    ]
    KernelStateCheckpoint.model_validate(checkpoint)
    assert ("alpha_matrix" in whole.artifacts_snapshot()) is not custom_alpha
    prefix = calculate(request.with_research_data(
        slice_research_sessions(data, SESSIONS[:2]), research_end_session=SESSIONS[1],
    )).track_state
    prefix_checkpoint = project_tracking_checkpoint(
        prefix, retained_strategy_sessions=SESSIONS[1:2], prior_observation_state=initial,
    )
    restored = restore_tracking_checkpoint(
        prefix_checkpoint, research_data=slice_research_sessions(data, SESSIONS[:2]),
    )
    continued = (advance_tracking if columnar else advance)(AdvanceInput(
        prior_state=restored, target_research_data=data, appended_sessions=list(SESSIONS[2:]),
        continuation=continuation_snapshot(restored), calculation_scope="forward_tracking",
    ))
    suffix = project_tracking_checkpoint(
        continued, retained_strategy_sessions=SESSIONS[2:],
        prior_observation_state=TrackingObservationState.model_validate(
            prefix_checkpoint["tracking_observation_state"],
        ),
    )
    KernelStateCheckpoint.model_validate(suffix)
    assert suffix["common_input_observations"] == observations[1:]
    assert suffix["strategy_state"]["terminal"] == checkpoint["strategy_state"]["terminal"]


@pytest.mark.parametrize("custom_alpha", [False, True])
def test_framework_advance_preserves_observed_exposure_when_prior_data_is_revised(custom_alpha):
    from thesistrace.research_kernel import AdvanceInput, advance, continuation_snapshot, run

    data, request = framework_run_input(
        custom_alpha=custom_alpha, builtin_portfolio=True,
        exposure_source="universe_advancing_fraction()",
    )
    prefix = run(request.with_research_data(
        slice_research_sessions(data, SESSIONS[:2]), research_end_session=SESSIONS[1],
    )).track_state
    corrected = data.snapshot()
    corrected.fields["price.close.adjusted"][(SESSIONS[0], B)] = "50"
    continued = advance(AdvanceInput(
        prior_state=prefix, target_research_data=corrected, appended_sessions=list(SESSIONS[2:]),
        continuation=continuation_snapshot(prefix), calculation_scope="research_period",
    ))
    observed = continued.output_snapshot()["common_inputs"]["sessions"]
    assert [(row["session"], row["common_inputs"][0]["value"]) for row in observed] == [
        (SESSIONS[1], 0.5), (SESSIONS[2], 0.0), (SESSIONS[3], 0.5),
    ]


def test_checkpoint_rejects_corrupt_builtin_portfolio_state_in_a_mixed_framework():
    from thesistrace.daily_track.checkpoint import (
        project_tracking_checkpoint,
        restore_tracking_checkpoint,
    )
    from thesistrace.daily_track.observation_state import initial_tracking_observation_state
    from thesistrace.research_kernel import run

    data, request = framework_run_input(builtin_portfolio=True)
    bounded = slice_research_sessions(data, SESSIONS[:2])
    prefix = run(request.with_research_data(bounded, research_end_session=SESSIONS[1])).track_state
    checkpoint = project_tracking_checkpoint(
        prefix, retained_strategy_sessions=SESSIONS[1:2],
        prior_observation_state=initial_tracking_observation_state(SESSIONS[0], "100000"),
    )
    for field, value in (
        ("signal_session", "2099-01-01"),
        ("contract_checksum", "0" * 64),
        ("selected_instrument_ids", ["equity:missing.SH"]),
    ):
        corrupted = deepcopy(checkpoint)
        selection = corrupted["strategy_state"]["terminal"]["decision_state"]["module_states"][
            "portfolio_construction"
        ]["selection"]
        selection[field] = value
        with pytest.raises(ValueError):
            restore_tracking_checkpoint(corrupted, research_data=bounded)
    corrupted = deepcopy(checkpoint)
    corrupted["strategy_state"]["terminal"]["decision_state"]["module_states"][
        "portfolio_construction"
    ]["exposure"] = 2.0
    with pytest.raises(ValueError):
        restore_tracking_checkpoint(corrupted, research_data=bounded)
    corrupted = deepcopy(checkpoint)
    corrupted["strategy_state"]["terminal"]["decision_state"]["selection_interval"] = None
    with pytest.raises(ValueError):
        restore_tracking_checkpoint(corrupted, research_data=bounded)
