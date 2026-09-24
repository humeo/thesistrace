from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import (
    SESSIONS,
    A,
    B,
    _alpha_matrix,
    _canonical,
    _definition,
    _set_alpha_closes,
)

from thesistrace.research_kernel.strategy import transition_strategy


def test_take_profit_uses_first_trigger_baseline_for_cumulative_reductions():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}, SESSIONS[2]: {A: "12"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
            {"profit_threshold": 0.2, "cumulative_reduction": 0.6},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    assert [(fill["side"], fill["quantity"]) for fill in result.finalized["fills"]] == [
        ("buy", 1000), ("sell", 300), ("sell", 300),
    ]
    position = result.finalized["positions"][0]
    assert position["execution_shares"] == 400
    assert Decimal(position["remaining_acquisition_cost_cny"]) == 4000
    assert Decimal(result.finalized["daily"][-1]["net_cash"]) == 6000


def test_take_profit_rejects_non_increasing_tiers_at_the_offending_field():
    import pytest
    from pydantic import ValidationError

    from thesistrace.research_kernel.builtin_risk import BuiltinRiskModule

    for field in ("profit_threshold", "cumulative_reduction"):
        tiers = [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
            {"profit_threshold": 0.2, "cumulative_reduction": 0.6},
        ]
        tiers[1][field] = tiers[0][field]
        with pytest.raises(ValidationError) as error:
            BuiltinRiskModule.model_validate({
                "kind": "builtin_risk/v1", "take_profit_tiers": tiers,
            })
        assert error.value.errors()[0]["loc"] == ("take_profit_tiers", 1, field)


def test_blocked_take_profit_preserves_progress_and_new_close_retries_the_difference():
    from thesistrace.research_series import slice_research_sessions

    canonical = _canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
        limit_overrides={(SESSIONS[2], A): ("12", "10")},
    )
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    prefix = transition_strategy(slice_research_sessions(data, SESSIONS[:3]), matrix,
                                 definition, origin_session=SESSIONS[0])
    assert prefix.finalized["rejections"][-1]["reason"] == "lower_limit_sell"
    observation = prefix.finalized["framework_events"][-1]["risk_adjustment"]["observations"][0]
    assert Decimal(observation["executed_reduction_units"]) == 0
    assert Decimal(observation["remaining_reduction_units"]) == 300
    assert prefix.resumable["pending_target"]["decision_session"] == SESSIONS[2]
    continued = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0],
                                    continuation=prefix.resumable)
    full = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    assert continued.finalized == full.finalized
    assert continued.resumable == full.resumable
    assert [(fill["side"], fill["quantity"]) for fill in full.finalized["fills"]] == [
        ("buy", 1000), ("sell", 300),
    ]
    observation = full.finalized["framework_events"][-1]["risk_adjustment"]["observations"][0]
    assert Decimal(observation["executed_reduction_units"]) == 300
    assert Decimal(observation["remaining_reduction_units"]) == 0


def test_crossing_both_tiers_sells_once_and_daily_selection_cannot_buy_back():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "12"}})
    definition = _definition(selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
            {"profit_threshold": 0.2, "cumulative_reduction": 0.6},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [
        ("buy", 1000), ("sell", 600),
    ]
    assert result["positions"][0]["execution_shares"] == 400
    assert Decimal(result["daily"][-1]["net_cash"]) == 6000


def test_full_take_profit_records_actual_completion_and_allows_fresh_cycle():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 1.0},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["session"], fill["quantity"]) for fill in result["fills"]] == [
        ("buy", SESSIONS[1], 1000), ("sell", SESSIONS[2], 1000),
        ("buy", SESSIONS[3], 1000),
    ]
    observation = result["framework_events"][2]["risk_adjustment"]["observations"][0]
    assert observation["cycle_ended"] is True
    assert Decimal(observation["executed_reduction_units"]) == 1000
    assert Decimal(observation["remaining_reduction_units"]) == 0
    assert result["positions"][0]["holding_age"] == 1


@pytest.mark.parametrize("new_sessions", [False, True])
@pytest.mark.parametrize("baseline", ["0", "NaN", "Infinity", "bogus", "-1"])
def test_restored_take_profit_rejects_impossible_baseline_instead_of_trading(
    new_sessions, baseline,
):
    import pytest

    from thesistrace.research_kernel.strategy import StrategyCalculationError
    from thesistrace.research_series import slice_research_sessions

    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    prefix = transition_strategy(slice_research_sessions(data, SESSIONS[:2]), matrix,
                                 definition, origin_session=SESSIONS[0])
    prefix.resumable["decision_state"]["module_states"]["risk_management"][
        "take_profit_cycles"
    ][A]["baseline_adjusted_units"] = baseline
    restored_data = data if new_sessions else slice_research_sessions(data, SESSIONS[:2])
    with pytest.raises(StrategyCalculationError, match="baseline"):
        transition_strategy(restored_data, matrix, definition, origin_session=SESSIONS[0],
                            continuation=prefix.resumable)


def test_take_profit_uses_adjusted_units_with_distinct_execution_shares():
    canonical = _canonical(opens={
        session: {A: ("10", "20"), B: "10"} for session in SESSIONS
    })
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "22"}, SESSIONS[2]: {A: "24"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
            {"profit_threshold": 0.2, "cumulative_reduction": 0.6},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [
        ("buy", 1000), ("sell", 300), ("sell", 300),
    ]
    assert Decimal(result["positions"][0]["adjusted_units"]) == 200
    observation = result["framework_events"][-1]["risk_adjustment"]["observations"][0]
    assert observation["baseline_execution_shares"] == 1000
    assert Decimal(observation["baseline_adjusted_units"]) == 500
    assert Decimal(observation["executed_reduction_units"]) == 300


def test_sub_lot_take_profit_retains_unexecuted_difference():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.025},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [("buy", 1000)]
    observation = result["framework_events"][-1]["risk_adjustment"]["observations"][0]
    assert Decimal(observation["remaining_reduction_units"]) == 25
    assert Decimal(observation["executed_reduction_units"]) == 0
    assert result["positions"][0]["execution_shares"] == 1000


@pytest.mark.parametrize("selection_interval", [1, 4])
def test_take_profit_writeoff_does_not_fabricate_a_completed_sale(selection_interval):
    canonical = _canonical(
        opens={session: {A: "10" if index < 2 else None, B: "10"}
               for index, session in enumerate(SESSIONS)},
        universes={session: (A, B) if index < 2 else (B,)
                   for index, session in enumerate(SESSIONS)},
    )
    canonical["instruments"][0]["listed_to"] = SESSIONS[2]
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(selection_interval=selection_interval)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    from thesistrace.research_series import slice_research_sessions

    full = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    prefix = transition_strategy(slice_research_sessions(data, SESSIONS[:3]), matrix,
                                 definition, origin_session=SESSIONS[0])
    resumed = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0],
                                  continuation=prefix.resumable)
    assert resumed.finalized == full.finalized
    assert resumed.resumable == full.resumable
    result = full.finalized
    observation = result["framework_events"][2]["risk_adjustment"]["observations"][0]
    assert observation["cycle_ended"] is True
    assert Decimal(observation["executed_reduction_units"]) == 0
    assert Decimal(observation["remaining_reduction_units"]) == 300
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [("buy", 1000)]
    assert result["positions"] == []
    assert Decimal(result["daily"][-1]["net_cash"]) == 0
    assert [row["net_return"] for row in result["daily"]][-2:] == [-1.0, 0.0]



def test_take_profit_is_local_and_leaves_released_cash_idle_without_new_proposal():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(holdings_count=2, selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "20000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["instrument_id"], fill["side"], fill["quantity"])
            for fill in result["fills"]] == [(A, "buy", 1000), (B, "buy", 1000), (A, "sell", 300)]
    assert [(row["instrument_id"], row["execution_shares"])
            for row in result["positions"]] == [(A, 700), (B, 1000)]
    assert Decimal(result["daily"][-1]["net_cash"]) == 3000


@pytest.mark.bounded_process
def test_additions_before_first_trigger_use_updated_cost_and_freeze_the_larger_baseline():
    from test_framework_strategy_programs import python_module

    from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime

    canonical = _canonical(opens={session: {A: "10" if index < 2 else "20", B: "10"}
                                  for index, session in enumerate(SESSIONS)})
    _set_alpha_closes(canonical, {SESSIONS[2]: {A: "15"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "12000"
    definition["strategy"]["environment"] = get_strategy_runtime().identity()
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["portfolio_construction"] = python_module('''
def decide(context, state, parameters):
    index = context['completed_sessions']
    output = None
    if index <= 2:
        output = {'reason': 'ordinary_addition', 'position_limits': {}, 'allocation': {
            'mode': 'rebalance', 'instrument_ids': ['equity:600001.SH'],
            'relative_weights': {'equity:600001.SH': '1'},
            'exposure': 0.5 if index == 1 else 1.0}}
    return {'output': output, 'state': {}}
''')
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 1.0},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [
        ("buy", 600), ("buy", 300), ("sell", 900),
    ]
    observation = result["framework_events"][2]["risk_adjustment"]["observations"][0]
    assert observation["baseline_execution_shares"] == 900
    assert Decimal(observation["holding_return"]) == Decimal("0.125")
    assert result["positions"] == []
    assert Decimal(result["daily"][-1]["net_cash"]) == 18000


@pytest.mark.bounded_process
@pytest.mark.parametrize("scenario", [
    "first_trigger", "cross_tier", "completed", "rejected", "rounding", "full_exit",
])
def test_take_profit_boundary_restores_in_a_fresh_process(tmp_path, scenario):
    import os
    import pickle
    import subprocess
    import sys

    from thesistrace.research_series import slice_research_sessions

    canonical = _canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
        limit_overrides={(SESSIONS[2], A): ("12", "10")} if scenario == "rejected" else None,
    )
    _set_alpha_closes(canonical, {
        SESSIONS[1]: {A: "11"}, SESSIONS[2]: {A: "12" if scenario == "cross_tier" else "10"},
    })
    reduction = 1.0 if scenario == "full_exit" else (0.025 if scenario == "rounding" else 0.3)
    tiers = [{"profit_threshold": 0.1, "cumulative_reduction": reduction}]
    if scenario == "cross_tier":
        tiers.append({"profit_threshold": 0.2, "cumulative_reduction": 0.6})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": tiers,
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    cut = 2 if scenario == "first_trigger" else 3
    prefix = transition_strategy(slice_research_sessions(data, SESSIONS[:cut]), matrix,
                                 definition, origin_session=SESSIONS[0])
    expected = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    sale_quantities = [fill["quantity"] for fill in expected.finalized["fills"]
                       if fill["side"] == "sell"]
    assert sale_quantities == {
        "first_trigger": [300], "cross_tier": [300, 300], "completed": [300],
        "rejected": [300], "rounding": [], "full_exit": [1000],
    }[scenario]
    payload = tmp_path / "trusted-test-checkpoint.pkl"
    payload.write_bytes(pickle.dumps((data, matrix, definition, prefix.resumable)))
    output = tmp_path / "restored.pkl"
    code = '''
import pickle, sys
from pathlib import Path
from thesistrace.research_kernel.strategy import transition_strategy
data, matrix, definition, prior = pickle.loads(Path(sys.argv[1]).read_bytes())
result = transition_strategy(data, matrix, definition, origin_session=None, continuation=prior)
Path(sys.argv[2]).write_bytes(pickle.dumps((result.finalized, result.resumable)))
'''
    subprocess.run([sys.executable, "-c", code, str(payload), str(output)], check=True,
                   capture_output=True, timeout=30,
                   env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    actual = pickle.loads(output.read_bytes())
    assert actual == (expected.finalized, expected.resumable)


def test_take_profit_keeps_frozen_units_across_a_changed_adjustment_ratio():
    canonical = _canonical(opens={
        session: {A: ("10", "20") if index < 2 else ("5", "20"), B: "10"}
        for index, session in enumerate(SESSIONS)
    })
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "22"}, SESSIONS[2]: {A: "24"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
            {"profit_threshold": 0.2, "cumulative_reduction": 0.6},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"], Decimal(fill["execution_price"]))
            for fill in result["fills"]] == [("buy", 1000, 10), ("sell", 300, 5), ("sell", 300, 5)]
    position = result["positions"][0]
    assert position["execution_shares"] == 400
    assert Decimal(position["adjusted_units"]) == 200
    assert Decimal(position["remaining_acquisition_cost_cny"]) == 4000
    # Research settlement is 300 removed adjusted units at20, while raw
    # execution notionals remain separately recorded at5 per execution share.
    assert Decimal(result["daily"][-1]["net_cash"]) == 6000


def test_take_profit_final_tier_liquidates_a_single_star_tail_share():
    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    canonical["instruments"][0]["board"] = "star"
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}, SESSIONS[2]: {A: "12"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "2010"
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.995},
            {"profit_threshold": 0.2, "cumulative_reduction": 1.0},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [
        ("buy", 201), ("sell", 200), ("sell", 1),
    ]
    assert result["positions"] == []
    assert Decimal(result["daily"][-1]["net_cash"]) == 2010


@pytest.mark.bounded_process
def test_stricter_portfolio_reduction_satisfies_take_profit_without_an_extra_sale():
    from test_framework_strategy_programs import python_module

    from thesistrace.research_kernel.strategy_program_runtime import get_strategy_runtime

    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "11"}})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["environment"] = get_strategy_runtime().identity()
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    definition["strategy"]["modules"]["portfolio_construction"] = python_module('''
def decide(context, state, parameters):
    index = context['completed_sessions']
    output = None
    if index == 1:
        output = {'reason': 'initial', 'position_limits': {}, 'allocation': {
            'mode': 'rebalance', 'instrument_ids': ['equity:600001.SH'],
            'relative_weights': {'equity:600001.SH': '1'}, 'exposure': 1.0}}
    elif index == 2:
        output = {'reason': 'ordinary_reduction', 'allocation': None,
                  'position_limits': {'equity:600001.SH': 200}}
    return {'output': output, 'state': {}}
''')
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "take_profit_tiers": [
            {"profit_threshold": 0.1, "cumulative_reduction": 0.3},
        ],
    }
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["quantity"]) for fill in result["fills"]] == [
        ("buy", 1000), ("sell", 800),
    ]
    assert result["positions"][0]["execution_shares"] == 200
    observation = result["framework_events"][-1]["risk_adjustment"]["observations"][0]
    assert Decimal(observation["executed_reduction_units"]) == 800
    assert Decimal(observation["remaining_reduction_units"]) == 0
    assert Decimal(result["daily"][-1]["net_cash"]) == 8000
