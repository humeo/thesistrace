"""Independent shared-account ledgers for simultaneous policy decisions."""

from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import (
    A,
    B,
    _alpha_matrix,
    _canonical,
    _definition,
    _set_alpha_closes,
)

from thesistrace.research_kernel.strategy import transition_strategy

SESSIONS = (
    "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12",
    "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-19", "2026-01-20",
)


def combined_inputs(*, interval=5, blocked=False):
    canonical = _canonical(
        sessions=SESSIONS, opens={session: {A: "10", B: "10"} for session in SESSIONS},
        limit_overrides={(SESSIONS[3], A): ("12", "10")} if blocked else None,
    )
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "10", B: "20"},
                                 SESSIONS[2]: {A: "12", B: "10"}})
    definition = _definition(holdings_count=2, selection_interval=interval)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"].update({
        "portfolio_construction": {"kind": "periodic_top_n/v1", "minimum_holding_sessions": 3},
        "risk_management": {
            "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
            "maximum_holding_sessions": 5,
            "take_profit_tiers": [{"profit_threshold": 0.1, "cumulative_reduction": 0.3}],
            "portfolio_drawdown": {"drawdown_threshold": 0.2, "maximum_stock_exposure": 0.3,
                                   "cooldown_sessions": 2},
        },
    })
    return (aligned_market_data(canonical, universe="manual"),
            _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS}), definition)


@pytest.mark.parametrize("interval,reentry", [(1, 7), (5, 11)])
def test_same_close_take_profit_and_drawdown_produce_one_difference_then_fresh_reentry(
    interval, reentry,
):
    data, matrix, definition = combined_inputs(interval=interval)
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(row["session"], row["instrument_id"], row["side"], row["quantity"])
            for row in result["fills"]] == [
        (SESSIONS[1], A, "buy", 5000), (SESSIONS[1], B, "buy", 5000),
        (SESSIONS[2], B, "sell", 1500),
        (SESSIONS[3], A, "sell", 3500), (SESSIONS[3], B, "sell", 2000),
        (SESSIONS[6], A, "sell", 1500), (SESSIONS[6], B, "sell", 1500),
        (SESSIONS[reentry], A, "buy", 5000), (SESSIONS[reentry], B, "buy", 5000),
    ]
    facts = result["framework_events"][2]["risk_adjustment"]["observations"]
    assert [(row["reason"], row.get("instrument_id")) for row in facts] == [
        ("take_profit", A), ("take_profit", B), ("portfolio_drawdown", None),
    ]
    assert Decimal(facts[-1]["peak_close_nav_cny"]) == 150000
    assert Decimal(facts[-1]["close_risk_nav_cny"]) == 110000
    assert facts[-1]["status"] == "threshold_reached"
    assert result["framework_events"][4]["risk_adjustment"]["observations"][-1]["status"] == (
        "new_portfolio_recovery" if interval == 1 else "awaiting_new_portfolio"
    )
    assert {row["reason"] for row in result["framework_events"][5]["risk_adjustment"][
        "observations"
    ]} == {"maximum_holding_period", "take_profit", "portfolio_drawdown"}
    assert all(Decimal(row["net_nav"]) == 100000 for row in result["daily"])
    assert all(position["holding_cycle_started_session"] == SESSIONS[reentry]
               for position in result["positions"])


def test_blocked_combined_sale_does_not_consume_progress_or_substitute_another_sale():
    from thesistrace.research_series import slice_research_sessions

    data, matrix, definition = combined_inputs(blocked=True)
    result = transition_strategy(slice_research_sessions(data, SESSIONS[:4]), matrix, definition,
                                 origin_session=SESSIONS[0]).finalized
    last_fills = [row for row in result["fills"] if row["session"] == SESSIONS[3]]
    assert [(row["instrument_id"], row["side"], row["quantity"]) for row in last_fills] == [
        (B, "sell", 2000),
    ]
    assert result["rejections"][-1]["instrument_id"] == A
    assert result["rejections"][-1]["reason"] == "lower_limit_sell"
    assert {row["instrument_id"]: row["execution_shares"] for row in result["positions"]} == {
        A: 5000, B: 1500,
    }
    cycles = result["decision_state"]["module_states"]["risk_management"]["take_profit_cycles"]
    assert Decimal(cycles[A]["executed_reduction_units"]) == 0
    assert Decimal(cycles[B]["executed_reduction_units"]) == 3500
    assert Decimal(result["daily"][-1]["net_cash"]) == 35000


DIRECT_SOURCE = '''
def decide(context, state, parameters):
    day = context['completed_sessions'] - 1
    holdings = {p['instrument_id']: p['execution_shares'] for p in context['account']['positions']}
    a, b = parameters['ids']
    output = None
    if day in (0, 10):
        output = {'reason': 'fresh_portfolio', 'allocation': {
            'mode': 'rebalance', 'instrument_ids': [a, b],
            'relative_weights': {a: '1/2', b: '1/2'}, 'exposure': 1.0}, 'position_limits': {}}
    elif day == 1:
        output = {'reason': 'first_local_cap', 'allocation': None, 'position_limits': {b: 3500}}
    elif day in (2, 3, 4):
        output = {'reason': 'combined_constraints', 'allocation': None,
                  'position_limits': {item: min(shares, 3500) for item, shares in holdings.items()},
                  'maximum_stock_exposure': 0.3}
    elif day == 5:
        output = {'reason': 'expiry', 'allocation': None,
                  'position_limits': {item: 0 for item in holdings}}
    sold = dict(state.get('sold', {}))
    for fill in context['fills']:
        if fill['side'] == 'sell':
            item = fill['instrument_id']
            sold[item] = sold.get(item, 0) + fill['quantity']
    return {'output': output, 'state': {'completed': day + 1, 'sold': sold}}
'''


@pytest.mark.bounded_process
@pytest.mark.parametrize("mode", ["framework", "framework_signals", "direct"])
def test_combined_account_state_and_pending_restore_at_every_boundary_in_new_process(
    tmp_path, mode,
):
    import os
    import pickle
    import subprocess
    import sys

    from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime
    from thesistrace.research_series import slice_research_sessions

    data, matrix, definition = combined_inputs(blocked=True)
    if mode == "framework_signals":
        from test_framework_strategy_programs import python_module

        definition["strategy"]["environment"] = get_strategy_runtime().identity()
        definition["strategy"]["modules"]["alpha"] = python_module('''
def decide(context, state, parameters):
    output = None
    if context['completed_sessions'] in (1, 6, 11):
        output = {'reason': 'fresh_rankings', 'signals': [
            {'instrument_id': item, 'value': 2.0 - index, 'valid_for_sessions': 2}
            for index, item in enumerate(parameters['ids'])]}
    return {'output': output, 'state': {'count': context['completed_sessions']}}
''', parameters={"ids": [A, B]})
        matrix = None
    if mode == "direct":
        definition["strategy"] = {
            "mode": "direct", "initial_cash_cny": "100000",
            "environment": get_strategy_runtime().identity(),
            "program": {"source": DIRECT_SOURCE, "parameters": {"ids": [A, B]},
                        "data_requirements": {"field_ids": [], "history_sessions": 1}},
        }
        matrix = None
    whole = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    if mode == "framework_signals":
        expired = whole.finalized["framework_events"][2]
        assert expired["alpha"]["expired_signals"] == [A, B]
        assert expired["alpha"]["signals"] == []
        assert expired["proposal"] is None
        assert {row["reason"] for row in expired["risk_adjustment"]["observations"]} == {
            "take_profit", "portfolio_drawdown",
        }
    assert [(row["session"], row["instrument_id"], row["side"], row["quantity"])
            for row in whole.finalized["fills"]] == [
        (SESSIONS[1], A, "buy", 5000), (SESSIONS[1], B, "buy", 5000),
        (SESSIONS[2], B, "sell", 1500), (SESSIONS[3], B, "sell", 2000),
        (SESSIONS[4], A, "sell", 2900), (SESSIONS[4], B, "sell", 600),
        (SESSIONS[6], A, "sell", 2100), (SESSIONS[6], B, "sell", 900),
        (SESSIONS[11], A, "buy", 5000), (SESSIONS[11], B, "buy", 5000),
    ]
    code = '''
import pickle, sys
from pathlib import Path
from thesistrace.research_kernel.strategy import transition_strategy
data, matrix, definition, prior = pickle.loads(Path(sys.argv[1]).read_bytes())
result = transition_strategy(data, matrix, definition, origin_session=None, continuation=prior)
Path(sys.argv[2]).write_bytes(pickle.dumps((result.finalized, result.resumable)))
'''
    for cut in (2, 3, 4, 5, 6, len(SESSIONS)):
        prefix = transition_strategy(slice_research_sessions(data, SESSIONS[:cut]), matrix,
                                     definition, origin_session=SESSIONS[0])
        payload, output = tmp_path / f"checkpoint-{cut}.pkl", tmp_path / f"restored-{cut}.pkl"
        payload.write_bytes(pickle.dumps((data, matrix, definition, prefix.resumable)))
        subprocess.run([sys.executable, "-c", code, str(payload), str(output)], check=True,
                       capture_output=True, timeout=60,
                       env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
        assert pickle.loads(output.read_bytes()) == (whole.finalized, whole.resumable)


@pytest.mark.bounded_process
@pytest.mark.parametrize("proposal", ["no_new", "increase", "stricter_cap"])
def test_local_risk_composes_with_proposal_without_selling_untargeted_names(proposal):
    from test_framework_strategy_programs import python_module

    from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime

    sessions, c = SESSIONS[:4], "equity:600003.SH"
    canonical = _canonical(sessions=sessions,
                           opens={session: {A: "10", B: "10"} for session in sessions})
    for section in ("instruments", "prices", "trading_states", "price_limits"):
        canonical[section].extend({**row, "instrument_id": c} for row in list(canonical[section])
                                  if row["instrument_id"] == B)
    for universe in canonical["liquidity_universes"]["manual"]:
        universe["instrument_ids"].append(c)
    _set_alpha_closes(canonical, {sessions[1]: {A: "11" if proposal == "stricter_cap" else "8"}})
    definition = _definition(holdings_count=3)
    definition["strategy"]["initial_cash_cny"] = "60000"
    definition["strategy"]["environment"] = get_strategy_runtime().identity()
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["portfolio_construction"] = python_module('''
def decide(context, state, parameters):
    day = context['completed_sessions']
    output = None
    if day == 1:
        output = {'reason': 'initial', 'allocation': {
            'mode': 'rebalance', 'instrument_ids': parameters['ids'],
            'relative_weights': {item: '1/3' for item in parameters['ids']}, 'exposure': 0.5},
            'position_limits': {}}
    elif day == 2 and parameters['proposal'] == 'stricter_cap':
        output = {'reason': 'ordinary_400_cap', 'allocation': None,
                  'position_limits': {parameters['ids'][0]: 400}}
    elif day == 2 and parameters['proposal'] == 'increase':
        a = parameters['ids'][0]
        output = {'reason': 'ordinary_increase', 'allocation': {
            'mode': 'increase', 'instrument_ids': [a], 'relative_weights': {a: '1'},
            'exposure': 0.8}, 'position_limits': {}}
    return {'output': output, 'state': {}}
''', parameters={"ids": [A, B, c], "proposal": proposal})
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
        "take_profit_tiers": [{"profit_threshold": 0.1, "cumulative_reduction": 0.3}],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 3), (B, 2), (c, 1)) for session in sessions})
    result = transition_strategy(data, matrix, definition, origin_session=sessions[0]).finalized
    assert [(row["instrument_id"], row["side"], row["quantity"]) for row in result["fills"]] == [
        (A, "buy", 1000), (B, "buy", 1000), (c, "buy", 1000),
        (A, "sell", 600 if proposal == "stricter_cap" else 1000),
    ]
    expected = {B: 1000, c: 1000}
    if proposal == "stricter_cap":
        expected[A] = 400
    assert {row["instrument_id"]: row["execution_shares"]
            for row in result["positions"]} == expected
    event = result["framework_events"][1]
    assert event["risk_adjustment"]["position_limits"] == {
        A: 400 if proposal == "stricter_cap" else 0,
    }
    if proposal == "stricter_cap":
        assert event["proposal"]["reason"] == "ordinary_400_cap"
        assert event["risk_adjustment"]["observations"][0]["reason"] == "take_profit"
        assert event["risk_adjustment"]["observations"][0]["position_limit"] == 700
    elif proposal == "increase":
        assert event["proposal"]["allocation"]["mode"] == "increase"
    else:
        assert event["proposal"] is None


def test_metric_checkpoint_cost_has_one_encoding_for_equal_decimal_values():
    from thesistrace.research_kernel.strategy import (
        advance_strategy_metric_state,
        run_strategy_with_metric_state,
    )

    data, matrix, definition = combined_inputs()
    prior = run_strategy_with_metric_state(data, matrix, definition,
                                          origin_session=SESSIONS[0])["metric_state"]
    states = [advance_strategy_metric_state(
        prior, initial_cash=Decimal("100000"), daily=[], turnover_events=[],
        cumulative_cost=Decimal(value), rejections=[],
    ) for value in ("86.58", "86.580000000")]
    assert states[0] == states[1]
    assert states[0]["cumulative_cost"] == "8658e-2"


@pytest.mark.bounded_process
@pytest.mark.parametrize("mode", ["direct", "framework"])
def test_combined_columnar_chunks_preserve_complete_result_and_terminal_state(mode):
    import numpy as np
    from test_framework_strategy_programs import python_module
    from test_research_chunk_continuation import _ColumnarFixture

    from thesistrace.research_kernel import DirectStrategyRunInput, RunInput, StrategyRunInput, run
    from thesistrace.research_kernel.numeric import NUMERIC_CONTRACT_ID
    from thesistrace.research_kernel.research_chunks import (
        AlphaFactorExecutionBinding,
        empty_research_continuation,
        execute_research_chunk,
        validated_research_continuation,
    )
    from thesistrace.research_kernel.serialization import canonical_json_bytes
    from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime
    from thesistrace.research_run.result import build_result_payload

    data, _, definition = combined_inputs(blocked=True)
    common = {"initial_cash_cny": "100000", **definition["costs"],
              "environment_json": canonical_json_bytes(get_strategy_runtime().identity())}
    if mode == "direct":
        strategy = DirectStrategyRunInput(program_json=canonical_json_bytes({
            "source": DIRECT_SOURCE, "parameters": {"ids": [A, B]},
            "data_requirements": {"field_ids": [], "history_sessions": 1},
        }), **common)
    else:
        modules = definition["strategy"]["modules"]
        modules["alpha"] = python_module('''
def decide(context, state, parameters):
    output = None
    if context['completed_sessions'] in (1, 6, 11):
        output = {'reason': 'rankings', 'signals': [
            {'instrument_id': item, 'value': 2.0 - index, 'valid_for_sessions': 2}
            for index, item in enumerate(parameters['ids'])]}
    return {'output': output, 'state': {'count': context['completed_sessions']}}
''', parameters={"ids": [A, B]})
        strategy = StrategyRunInput(holdings_count=2, selection_interval=5,
                                    modules_json=canonical_json_bytes(modules), **common)
    columnar = _ColumnarFixture(
        sessions=data.sessions, instruments=data.instruments,
        universe_members=data.universe_members,
        industries=data.industries, execution_prices=data.execution_prices,
        trading_states=data.trading_states, price_limits=data.price_limits,
        matrices={field: np.asarray([
            [float(values.get((session, item), "nan")) for session in data.sessions]
            for item in data.instruments]) for field, values in data.fields.items()},
    )
    run_input = RunInput(
        research_data=columnar, alpha_expression=None, field_bindings={}, effective_lookback=0,
        universe="manual", neutralization=None, research_kind="strategy_backtest",
        strategy=strategy,
        research_start_session=SESSIONS[0], research_end_session=SESSIONS[-1],
    )
    binding = AlphaFactorExecutionBinding.from_run_input(
        run_input, data_generation_id="combined-ledger",
        numeric_execution_contract=NUMERIC_CONTRACT_ID,
        semantic_versions={"kernel": "combined-test"},
    )
    state = empty_research_continuation("strategy_backtest")
    observations = []
    start = 0
    for end in (2, 3, 4, 5, 6, 12):
        chunk = execute_research_chunk(
            run_input=run_input, binding=binding,
            research_data=columnar.slice_sessions(SESSIONS[:end]), forward_labels=None,
            research_sessions=SESSIONS[start:end], final_chunk=end == 12,
            continuation=state, cancellation_check=lambda: None,
        )
        state = validated_research_continuation(chunk.continuation,
                                                research_kind="strategy_backtest")
        observations.extend(chunk.strategy_daily_observations)
        start = end
    expected = build_result_payload(run(run_input.with_research_data(data)),
                                    research_kind="strategy_backtest")
    assert observations == expected.pop("strategy_daily_observations")
    assert chunk.final_values == expected
