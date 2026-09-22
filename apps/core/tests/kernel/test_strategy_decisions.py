import copy
from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _canonical, _definition

from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_series import slice_research_sessions


def test_frozen_target_can_change_selection_outside_the_builtin_schedule():
    data = aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=3)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = {name: "0" for name in definition["costs"]}
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    state = copy.deepcopy(prefix.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1],
        "execution": "next_research_session_open",
        "contract_checksum": state["target_selection"]["contract_checksum"],
        "reason": "better_candidate",
        "allocation": {
            "mode": "rebalance",
            "instrument_ids": [B],
            "relative_weights": {B: "1"},
            "exposure": 1.0,
        },
        "position_limits": {},
    }
    result = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized

    assert [
        (fill["instrument_id"], fill["side"], fill["quantity"])
        for fill in result["fills"] if fill["session"] == SESSIONS[2]
    ] == [(A, "sell", 10000), (B, "buy", 10000)]
    assert result["target_selection"]["selected_instrument_ids"] == [A]
    assert result["pending_target"] is None
    assert [(item["instrument_id"], item["execution_shares"])
            for item in result["positions"]] == [(B, 10000)]


def test_local_reduction_keeps_other_holdings_and_freezes_quantity_before_open():
    data = aligned_market_data(
        _canonical(opens={session: {A: "20" if session == SESSIONS[2] else "10", B: "10"}
                          for session in SESSIONS}),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(holdings_count=2, selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = {name: "0" for name in definition["costs"]}
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    state = copy.deepcopy(prefix.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1],
        "execution": "next_research_session_open",
        "contract_checksum": state["target_selection"]["contract_checksum"],
        "reason": "local_reduction",
        "allocation": None,
        "position_limits": {A: 4000},
    }
    result = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized

    assert [(fill["instrument_id"], fill["side"], fill["quantity"])
            for fill in result["fills"] if fill["session"] == SESSIONS[2]] == [(A, "sell", 1000)]
    assert [(item["instrument_id"], item["execution_shares"])
            for item in result["positions"]] == [(A, 4000), (B, 5000)]
    assert Decimal(result["daily"][-1]["net_cash"]) == Decimal("20000")
    assert result["pending_target"] is None
    continued = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=result,
    ).finalized
    assert continued["fills"] == result["fills"]
    assert [(item["instrument_id"], item["execution_shares"])
            for item in continued["positions"]] == [(A, 4000), (B, 5000)]
    assert Decimal(continued["daily"][-1]["net_cash"]) == Decimal("20000")


def test_final_allocation_and_share_ceiling_produce_one_difference_without_buyback():
    data = aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(holdings_count=2, selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = {name: "0" for name in definition["costs"]}
    prefix = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    state = copy.deepcopy(prefix.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["target_selection"]["contract_checksum"],
        "reason": "new_portfolio_with_reduction",
        "allocation": {
            "mode": "rebalance", "instrument_ids": [A],
            "relative_weights": {A: "1"}, "exposure": 1.0,
        },
        "position_limits": {A: 4000},
    }
    result = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=state,
    ).finalized
    assert [(fill["instrument_id"], fill["side"], fill["quantity"])
            for fill in result["fills"] if fill["session"] > SESSIONS[1]] == [
        (A, "sell", 1000), (B, "sell", 5000),
    ]
    assert Decimal(result["daily"][-1]["net_cash"]) == Decimal("60000")


def test_explicit_increase_can_use_cash_released_by_same_decision_local_exit():
    data = aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(holdings_count=2, selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "100000"
    definition["costs"] = {name: "0" for name in definition["costs"]}
    state = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    ).resumable
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["target_selection"]["contract_checksum"],
        "reason": "better_candidate_with_local_exit",
        "allocation": {
            "mode": "increase", "instrument_ids": [B],
            "relative_weights": {B: "1"}, "exposure": 1.0,
        },
        "position_limits": {A: 0},
    }
    result = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=state,
    ).finalized
    assert [(fill["instrument_id"], fill["side"], fill["quantity"])
            for fill in result["fills"] if fill["session"] > SESSIONS[1]] == [
        (A, "sell", 5000), (B, "buy", 5000),
    ]
    assert [(item["instrument_id"], item["execution_shares"])
            for item in result["positions"]] == [(B, 10000)]
    assert Decimal(result["daily"][-1]["net_cash"]) == 0


@pytest.mark.parametrize("change", [
    {"allocation": None, "position_limits": {}},
    {"position_limits": {A: -1}},
    {"position_limits": {A: 1.5}},
    {"position_limits": {A: True}},
    {"position_limits": {B: 1}},
    {"decision_session": SESSIONS[1]},
    {"unexpected_instruction": "buy"},
    {"allocation": {"mode": "rebalance", "instrument_ids": [A],
                    "relative_weights": {A: "1"}, "exposure": float("nan")}},
    {"allocation": {"mode": "rebalance", "instrument_ids": [A],
                    "relative_weights": {A: "1"}, "exposure": 1.01}},
    {"allocation": {"mode": "rebalance", "instrument_ids": ["unknown"],
                    "relative_weights": {"unknown": "1"}, "exposure": 1.0}},
])
def test_invalid_final_decisions_fail_before_any_execution(change):
    data = aligned_market_data(
        _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS}),
        universe="manual",
    )
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition()
    state = transition_strategy(
        slice_research_sessions(data, SESSIONS[:1]), matrix, definition,
        origin_session=SESSIONS[0],
    ).resumable
    state["pending_target"].update(change)
    original = copy.deepcopy(state)
    with pytest.raises((ValueError, RuntimeError)):
        transition_strategy(
            data, matrix, definition, origin_session=SESSIONS[0], continuation=state,
        )
    assert state == original
