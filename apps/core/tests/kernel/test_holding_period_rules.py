from decimal import Decimal

import pytest
from pydantic import ValidationError
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _canonical, _definition

from thesistrace.research_kernel.builtin_risk import BuiltinRiskModule
from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_series import slice_research_sessions


def test_maximum_holding_period_decides_at_nth_close_and_exits_next_open():
    data = aligned_market_data(_canonical(
        opens={session: {A: "12" if session == SESSIONS[3] else "10", B: "10"}
               for session in SESSIONS},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "maximum_holding_sessions": 2,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    assert [(fill["side"], fill["session"]) for fill in prefix.finalized["fills"]] == [
        ("buy", SESSIONS[1]),
    ]
    assert prefix.finalized["positions"][0]["holding_age"] == 2
    assert prefix.resumable["pending_target"]["decision_session"] == SESSIONS[2]
    assert prefix.resumable["pending_target"]["position_limits"] == {A: 0}
    result = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=prefix.resumable,
    ).finalized
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", SESSIONS[1]), ("sell", SESSIONS[3]),
    ]
    assert result["positions"] == []
    assert Decimal(result["daily"][-1]["net_cash"]) == 12000


def test_expiry_and_stop_loss_preserve_both_causes_and_execute_one_exit():
    from test_manual_strategy_ledger import _set_alpha_closes

    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[2]: {A: "8"}})
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "maximum_holding_sessions": 2, "stop_loss_threshold": 0.1,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    adjustment = result["framework_events"][2]["risk_adjustment"]
    assert adjustment["position_limits"] == {A: 0}
    assert [(row["reason"], row["holding_age"]) for row in adjustment["observations"]] == [
        ("stop_loss", 2), ("maximum_holding_period", 2),
    ]
    assert adjustment["observations"][1]["maximum_holding_sessions"] == 2
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", SESSIONS[1]), ("sell", SESSIONS[3]),
    ]


@pytest.mark.parametrize("value", [0, -1, 1.5, "2", True, float("inf")])
def test_maximum_holding_period_requires_a_positive_integer(value):
    with pytest.raises(ValidationError) as error:
        BuiltinRiskModule.model_validate({
            "kind": "builtin_risk/v1", "maximum_holding_sessions": value,
        })
    assert error.value.errors()[0]["loc"] == ("maximum_holding_sessions",)


def test_minimum_holding_reserves_young_holding_before_selecting_better_stock():
    data = aligned_market_data(_canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
    ), universe="manual")
    matrix = _alpha_matrix({
        SESSIONS[0]: ((A, 2), (B, 1)),
        **{session: ((B, 2), (A, 1)) for session in SESSIONS[1:]},
    })
    definition = _definition(selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["portfolio_construction"] = {
        "kind": "periodic_top_n/v1", "minimum_holding_sessions": 2,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["instrument_id"], fill["session"]) for fill in result["fills"]] == [
        ("buy", A, SESSIONS[1]), ("sell", A, SESSIONS[3]), ("buy", B, SESSIONS[3]),
    ]
    proposal = result["framework_events"][1]["proposal"]
    assert proposal["allocation"]["retained_instrument_ids"] == [A]
    assert proposal["allocation"]["instrument_ids"] == []
    assert result["framework_events"][1]["portfolio_retentions"] == [{
        "reason": "minimum_holding_period", "instrument_id": A, "execution_shares": 1000,
        "holding_age": 1, "minimum_holding_sessions": 2,
    }]
    assert result["positions"][0]["holding_age"] == 1


def test_stop_loss_overrides_minimum_reservation_without_same_open_buyback():
    from test_manual_strategy_ledger import _set_alpha_closes

    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "8"}})
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"].update({
        "portfolio_construction": {"kind": "periodic_top_n/v1", "minimum_holding_sessions": 3},
        "risk_management": {"kind": "builtin_risk/v1", "stop_loss_threshold": 0.1},
    })
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", SESSIONS[1]), ("sell", SESSIONS[2]), ("buy", SESSIONS[3]),
    ]
    assert result["positions"][0]["holding_age"] == 1


def test_framework_rejects_minimum_above_maximum_at_maximum_field():
    from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
    from thesistrace.research_kernel.framework_strategy import FrameworkModules

    modules = dict(BUILTIN_FRAMEWORK_MODULES)
    modules.update({
        "portfolio_construction": {"kind": "periodic_top_n/v1", "minimum_holding_sessions": 3},
        "risk_management": {"kind": "builtin_risk/v1", "maximum_holding_sessions": 2},
    })
    with pytest.raises(ValidationError) as error:
        FrameworkModules.model_validate(modules)
    assert error.value.errors()[0]["loc"] == ("risk_management", "maximum_holding_sessions")


def test_exposure_change_reserves_young_holdings_without_duplicate_weighted_targets():
    from thesistrace.research_kernel.builtin_framework import BuiltinFramework

    policy = BuiltinFramework(holdings_count=1, selection_interval=5, weighting="equal_weight",
                              volatility_window=20, contract_checksum="a" * 64,
                              minimum_holding_sessions=3)
    baseline = policy.decide(session=SESSIONS[0], report_index=0, alpha_values=[
        {"instrument_id": A, "value": 1},
    ], close_windows={}, exposure_value=1, previous=None)
    changed = policy.decide(session=SESSIONS[1], report_index=1, alpha_values=[
        {"instrument_id": B, "value": 2},
    ], close_windows={}, exposure_value=0.5, previous=baseline.state,
        account={"positions": [{"instrument_id": A, "holding_age": 1}]})
    assert changed.target.allocation.retained_instrument_ids == [A]
    assert changed.target.allocation.instrument_ids == []
    assert changed.target.allocation.relative_weights == {}


def test_retained_holding_uses_capital_before_remaining_candidate_weights():
    data = aligned_market_data(_canonical(opens={
        session: {A: "10" if index < 2 else "20", B: "10"}
        for index, session in enumerate(SESSIONS)
    }), universe="manual")
    matrix = _alpha_matrix({SESSIONS[0]: ((A, 1),), **{
        session: ((B, 2), (A, 1)) for session in SESSIONS[1:]
    }})
    definition = _definition(holdings_count=2, selection_interval=1)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["portfolio_construction"] = {
        "kind": "periodic_top_n/v1", "minimum_holding_sessions": 4,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    assert [(fill["side"], fill["instrument_id"], fill["quantity"])
            for fill in result["fills"]] == [
        ("buy", A, 1000),
    ]
    assert result["positions"][0]["execution_shares"] == 1000
    assert result["framework_events"][1]["proposal"]["allocation"]["instrument_ids"] == [B]


def test_blocked_expiry_preserves_holding_and_queues_a_fresh_close_decision():
    data = aligned_market_data(_canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
        limit_overrides={(SESSIONS[2], A): ("12", "10")},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "maximum_holding_sessions": 1,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    blocked = transition_strategy(slice_research_sessions(data, SESSIONS[:3]), matrix,
                                  definition, origin_session=SESSIONS[0])
    assert blocked.finalized["rejections"][-1]["reason"] == "lower_limit_sell"
    position = blocked.finalized["positions"][0]
    assert position["execution_shares"] == 1000
    assert Decimal(position["remaining_acquisition_cost_cny"]) == 10000
    assert position["holding_age"] == 2
    assert blocked.resumable["pending_target"]["decision_session"] == SESSIONS[2]
    decisions = blocked.finalized["framework_events"]
    assert decisions[1]["target_id"] != decisions[2]["target_id"]
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0],
                                 continuation=blocked.resumable).finalized
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", SESSIONS[1]), ("sell", SESSIONS[3]),
    ]


def test_expiry_counts_research_sessions_across_weekend_and_holiday():
    sessions = ("2026-04-02", "2026-04-03", "2026-04-07", "2026-04-08")
    data = aligned_market_data(_canonical(sessions=sessions,
        opens={session: {A: "10", B: "10"} for session in sessions},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in sessions})
    definition = _definition(selection_interval=4)
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "maximum_holding_sessions": 2,
    }
    result = transition_strategy(data, matrix, definition, origin_session=sessions[0]).finalized
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", "2026-04-03"), ("sell", "2026-04-08"),
    ]
    evidence = result["framework_events"][2]["risk_adjustment"]["observations"][0]
    assert evidence["holding_age"] == 2


def test_add_and_partial_sale_keep_expiry_clock_in_same_holding_cycle():
    from copy import deepcopy

    sessions = (*SESSIONS, "2026-01-09")
    data = aligned_market_data(_canonical(sessions=sessions,
        opens={session: {A: "10", B: "10"} for session in sessions},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in sessions})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["exposure_expression"] = {"kind": "number", "value": 0.2}
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "maximum_holding_sessions": 3,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    current = transition_strategy(slice_research_sessions(data, sessions[:2]), matrix,
                                  definition, origin_session=sessions[0])
    for boundary, exposure, expected_shares in ((3, 0.5, 500), (4, 0.3, 300)):
        state = deepcopy(current.resumable)
        state["pending_target"] = {
            "decision_session": sessions[boundary - 2], "execution": "next_research_session_open",
            "contract_checksum": state["contract_checksum"], "reason": "explicit_resize",
            "position_limits": {},
            "allocation": {"mode": "rebalance", "exposure": exposure,
                           "instrument_ids": [A], "relative_weights": {A: "1"}},
        }
        current = transition_strategy(slice_research_sessions(data, sessions[:boundary]), matrix,
                                      definition, origin_session=sessions[0], continuation=state)
        position = current.finalized["positions"][0]
        assert position["execution_shares"] == expected_shares
        assert position["holding_age"] == boundary - 1
        assert position["holding_cycle_started_session"] == sessions[1]
    assert current.resumable["pending_target"]["position_limits"] == {A: 0}
    expired = transition_strategy(data, matrix, definition, origin_session=sessions[0],
                                 continuation=current.resumable).finalized
    assert expired["positions"] == []
    assert [(row["side"], row["quantity"], row["session"]) for row in expired["fills"]] == [
        ("buy", 200, sessions[1]), ("buy", 300, sessions[2]),
        ("sell", 200, sessions[3]), ("sell", 300, sessions[4]),
    ]


def test_increase_budget_counts_retained_capital_once_with_mixed_holding_ages():
    from copy import deepcopy

    from thesistrace.research_kernel.builtin_framework import BuiltinFramework
    from thesistrace.research_kernel.terminal_state_schema import BuiltinPortfolioState

    data = aligned_market_data(_canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
        limit_overrides={(SESSIONS[1], B): ("10", "8")},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(holdings_count=2, selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["exposure_expression"] = {"kind": "number", "value": 0.5}
    definition["strategy"]["modules"]["portfolio_construction"] = {
        "kind": "periodic_top_n/v1", "minimum_holding_sessions": 2,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    current = transition_strategy(slice_research_sessions(data, SESSIONS[:2]), matrix,
                                  definition, origin_session=SESSIONS[0])
    assert [(row["instrument_id"], row["execution_shares"])
            for row in current.finalized["positions"]] == [(A, 200)]
    # Supply two public portfolio decisions between periodic selections. The first
    # retains young A and acquires B; the second retains young B and increases A.
    for end, exposure in ((3, 0.7), (4, 0.8)):
        state = deepcopy(current.resumable)
        portfolio = BuiltinFramework(holdings_count=2, selection_interval=4,
            weighting="equal_weight", volatility_window=20,
            contract_checksum=state["contract_checksum"], minimum_holding_sessions=2)
        decision = portfolio.decide(session=SESSIONS[end - 2], report_index=end - 2,
            alpha_values=[], close_windows={}, exposure_value=exposure,
            previous=BuiltinPortfolioState.model_validate(
                state["decision_state"]["module_states"]["portfolio_construction"]),
            account={"positions": current.finalized["positions"]})
        assert decision.target.allocation.mode == "increase"
        state["pending_target"] = decision.target.model_dump(mode="json")
        current = transition_strategy(slice_research_sessions(data, SESSIONS[:end]), matrix,
                                      definition, origin_session=SESSIONS[0], continuation=state)
    assert {row["instrument_id"]: row["execution_shares"]
            for row in current.finalized["positions"]} == {A: 300, B: 500}
    assert Decimal(current.finalized["daily"][-1]["net_cash"]) == 2000


def test_expiry_exits_only_the_older_holding_and_leaves_freed_cash_unallocated():
    from copy import deepcopy

    data = aligned_market_data(_canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["exposure_expression"] = {"kind": "number", "value": 0.3}
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "maximum_holding_sessions": 2,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    bought = transition_strategy(slice_research_sessions(data, SESSIONS[:2]), matrix,
                                 definition, origin_session=SESSIONS[0])
    state = deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["contract_checksum"], "reason": "new_candidate",
        "position_limits": {}, "allocation": {"mode": "increase", "exposure": 0.5,
            "instrument_ids": [B], "relative_weights": {B: "1"}},
    }
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0],
                                 continuation=state).finalized
    assert [(row["instrument_id"], row["side"], row["quantity"]) for row in result["fills"]] == [
        (A, "buy", 300), (B, "buy", 200), (A, "sell", 300),
    ]
    assert result["framework_events"][2]["risk_adjustment"]["position_limits"] == {A: 0}
    assert [(row["instrument_id"], row["execution_shares"])
            for row in result["positions"]] == [(B, 200)]
    assert Decimal(result["daily"][-1]["net_cash"]) == 8000
