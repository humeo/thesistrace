import copy
from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _canonical, _definition

from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_series import slice_research_sessions


def test_partial_exit_releases_acquisition_cost_proportionally_after_resume():
    data = aligned_market_data(_canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "11000"
    bought = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    position = bought.finalized["positions"][0]
    assert position["execution_shares"] == 1000
    assert Decimal(position["remaining_acquisition_cost_cny"]) == Decimal("10005.10")

    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["contract_checksum"], "reason": "partial_exit",
        "allocation": None, "position_limits": {A: 700},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    assert sold["fills"][-1]["quantity"] == 300
    assert sold["positions"][0]["execution_shares"] == 700
    assert Decimal(sold["positions"][0]["remaining_acquisition_cost_cny"]) == Decimal("7003.57")


def test_acquisition_cost_includes_slippage_and_additional_buy_fees():
    from test_strategy_cost_slippage import buy_at_constant_open

    data, matrix, definition, bought = buy_at_constant_open(
        initial_cash="100000", slippage="10", exposure=0.2,
    )
    position = bought.finalized["positions"][0]
    assert position["execution_shares"] == 100
    assert position["holding_age"] == 1
    assert position["holding_cycle_started_session"] == SESSIONS[1]
    assert Decimal(position["remaining_acquisition_cost_cny"]) == Decimal("10015.1001")
    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["contract_checksum"], "reason": "add_position",
        "position_limits": {},
        "allocation": {"mode": "rebalance", "exposure": 0.5,
                       "instrument_ids": [A], "relative_weights": {A: "1"}},
    }
    added = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    assert added["fills"][-1]["quantity"] == 300
    assert Decimal(added["positions"][0]["remaining_acquisition_cost_cny"]) == Decimal("40054.4094")

    assert added["positions"][0]["holding_age"] == 2
    assert added["positions"][0]["holding_cycle_started_session"] == SESSIONS[1]


def test_holding_age_is_identical_across_a_restored_session_boundary():
    from test_strategy_cost_slippage import buy_at_constant_open

    data, matrix, definition, bought = buy_at_constant_open()
    whole = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
    resumed = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=bought.resumable,
    )
    assert whole.finalized["positions"] == resumed.finalized["positions"]
    assert whole.finalized["positions"][0]["holding_age"] == 3
    assert whole.finalized["positions"][0]["holding_cycle_started_session"] == SESSIONS[1]


def test_complete_exit_then_new_buy_starts_a_new_holding_cycle():
    from test_strategy_cost_slippage import buy_at_constant_open

    data, matrix, definition, bought = buy_at_constant_open(initial_cash="30000")
    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["contract_checksum"], "reason": "exit",
        "allocation": None, "position_limits": {A: 0},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    )
    assert sold.finalized["positions"] == []
    state = copy.deepcopy(sold.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[2], "execution": "next_research_session_open",
        "contract_checksum": state["contract_checksum"], "reason": "new_selection",
        "position_limits": {},
        "allocation": {"mode": "rebalance", "exposure": 1.0,
                       "instrument_ids": [A], "relative_weights": {A: "1"}},
    }
    rebought = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=state,
    ).finalized
    position = rebought["positions"][0]
    assert position["holding_age"] == 1
    assert position["holding_cycle_started_session"] == SESSIONS[3]
    assert Decimal(position["remaining_acquisition_cost_cny"]) == Decimal("20026.2062")


def test_close_risk_nav_uses_research_units_without_overwriting_open_marks():
    from test_manual_strategy_ledger import _set_alpha_closes

    canonical = _canonical(
        opens={session: {A: ("10", "20"), B: "10"} for session in SESSIONS},
    )
    _set_alpha_closes(canonical, {session: {A: "18"} for session in SESSIONS})
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "11000"
    result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
    position = result["positions"][0]
    assert Decimal(position["adjusted_units"]) == Decimal("500")
    assert Decimal(position["last_adjusted_price"]) == Decimal("20")
    assert Decimal(position["last_close_adjusted_price"]) == Decimal("18")
    assert Decimal(result["daily"][-1]["net_nav"]) == Decimal("10994.9")
    assert Decimal(result["daily"][-1]["close_risk_nav_cny"]) == Decimal("9994.9")


def test_suspended_close_carries_its_own_mark_and_unknown_missing_close_fails():
    import pytest
    from test_manual_strategy_ledger import _set_alpha_closes

    from thesistrace.research_kernel.strategy import StrategyCalculationError

    for state in ("full_session_suspension", "data_unavailable"):
        canonical = _canonical(
            opens={session: {A: None if session == SESSIONS[2] else ("10", "20"), B: "10"}
                   for session in SESSIONS[:3]},
            sessions=SESSIONS[:3], states={(SESSIONS[2], A): state},
        )
        _set_alpha_closes(canonical, {session: {A: "18"} for session in SESSIONS[:2]})
        data = aligned_market_data(canonical, universe="manual")
        matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS[:3]})
        definition = _definition(selection_interval=4)
        definition["strategy"]["initial_cash_cny"] = "11000"
        if state == "data_unavailable":
            with pytest.raises(StrategyCalculationError, match="missing Close"):
                transition_strategy(data, matrix, definition, origin_session=SESSIONS[0])
        else:
            result = transition_strategy(
                data, matrix, definition, origin_session=SESSIONS[0],
            ).finalized
            position = result["positions"][0]
            assert position["holding_age"] == 2
            assert Decimal(position["last_adjusted_price"]) == Decimal("20")
            assert Decimal(position["last_close_adjusted_price"]) == Decimal("18")
            assert Decimal(result["daily"][-1]["close_risk_nav_cny"]) == Decimal("9994.9")


@pytest.mark.parametrize("invalid_close", ("0", "-1", "Infinity"))
def test_suspension_does_not_hide_an_invalid_present_close(invalid_close):
    from test_manual_strategy_ledger import _set_alpha_closes

    from thesistrace.research_kernel.strategy import StrategyCalculationError

    canonical = _canonical(
        opens={session: {A: "10", B: "10"} for session in SESSIONS},
        states={(SESSIONS[2], A): "full_session_suspension"},
    )
    _set_alpha_closes(canonical, {SESSIONS[2]: {A: invalid_close}})
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    with pytest.raises(StrategyCalculationError, match="invalid Close"):
        transition_strategy(data, matrix, _definition(selection_interval=4),
                            origin_session=SESSIONS[0])


@pytest.mark.parametrize("next_open", ("8.6", "12"))
def test_builtin_stop_loss_freezes_close_exit_and_executes_at_next_open(next_open):
    from test_manual_strategy_ledger import _set_alpha_closes

    canonical = _canonical(opens={
        SESSIONS[0]: {A: "10", B: "10"},
        SESSIONS[1]: {A: "10", B: "10"},
        SESSIONS[2]: {A: next_open, B: "10"},
        SESSIONS[3]: {A: "9", B: "10"},
    })
    _set_alpha_closes(canonical, {SESSIONS[1]: {A: "8.9"}})
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    triggered = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    evidence = triggered.finalized["framework_events"][-1]["risk_adjustment"]
    assert evidence["mode"] == "holding_risk"
    assert evidence["observations"] == [{
        "reason": "stop_loss", "instrument_id": A, "remaining_acquisition_cost_cny": "1e+4",
        "close_market_value_cny": "89e+2", "holding_return": "-11e-2",
        "stop_loss_threshold": "1e-1", "execution_shares": 1000, "holding_age": 1,
    }]
    assert triggered.resumable["pending_target"]["position_limits"] == {A: 0}
    assert triggered.resumable["pending_target"]["allocation"] is None
    assert triggered.resumable["pending_target"]["decision_session"] == SESSIONS[1]
    result = transition_strategy(
        data, matrix, definition, origin_session=SESSIONS[0], continuation=triggered.resumable,
    ).finalized
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", SESSIONS[1]), ("sell", SESSIONS[2]),
    ]
    assert Decimal(result["fills"][-1]["execution_price"]) == Decimal(next_open)
    assert Decimal(result["daily"][-1]["net_cash"]) == Decimal(next_open) * 1000
    assert result["positions"] == []


def test_intraday_low_does_not_trigger_close_stop_loss_and_holidays_do_not_age_holdings():
    sessions = ("2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12")
    canonical = _canonical(
        sessions=sessions,
        opens={session: {A: "10", B: "10"} for session in sessions},
    )
    for row in canonical["prices"]:
        row["low_adj"] = "8"
    data = aligned_market_data(canonical, universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in sessions})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "10000"
    definition["strategy"]["modules"]["risk_management"] = {
        "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
    }
    definition["costs"] = dict.fromkeys(definition["costs"], "0")
    result = transition_strategy(data, matrix, definition, origin_session=sessions[0]).finalized
    assert [(fill["side"], fill["session"]) for fill in result["fills"]] == [
        ("buy", "2026-10-08"),
    ]
    assert result["positions"][0]["holding_age"] == 3
    assert result["positions"][0]["holding_cycle_started_session"] == "2026-10-08"
    assert all(event["risk_adjustment"] is None for event in result["framework_events"])


def test_stop_loss_is_local_and_composes_once_with_a_new_portfolio():
    from test_manual_strategy_ledger import _set_alpha_closes

    for interval in (1, 4):
        canonical = _canonical(
            opens={session: {A: "8.6" if session == SESSIONS[2] else "10", B: "10"}
                   for session in SESSIONS[:3]}, sessions=SESSIONS[:3],
        )
        _set_alpha_closes(canonical, {SESSIONS[1]: {A: "8.9"}})
        data = aligned_market_data(canonical, universe="manual")
        matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS[:3]})
        definition = _definition(holdings_count=2, selection_interval=interval)
        definition["strategy"]["initial_cash_cny"] = "20000"
        definition["strategy"]["modules"]["risk_management"] = {
            "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
        }
        definition["costs"] = dict.fromkeys(definition["costs"], "0")
        result = transition_strategy(data, matrix, definition, origin_session=SESSIONS[0]).finalized
        assert [(row["instrument_id"], row["side"], row["quantity"])
                for row in result["fills"] if row["session"] == SESSIONS[2]] == [(A, "sell", 1000)]
        assert [(row["instrument_id"], row["execution_shares"])
                for row in result["positions"]] == [(B, 1000)]
        assert Decimal(result["daily"][-1]["net_cash"]) == Decimal("8600")


def test_blocked_stop_loss_keeps_cost_and_needs_a_new_close_decision():
    from test_manual_strategy_ledger import _set_alpha_closes

    for next_close, expected_sales in (("10", []), ("8.9", [SESSIONS[3]])):
        canonical = _canonical(
            opens={session: {A: "8.6" if session == SESSIONS[2] else "10", B: "10"}
                   for session in SESSIONS},
            limit_overrides={(SESSIONS[2], A): ("12", "8.6")},
        )
        _set_alpha_closes(canonical, {SESSIONS[1]: {A: "8.9"}, SESSIONS[2]: {A: next_close}})
        data = aligned_market_data(canonical, universe="manual")
        matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
        definition = _definition(selection_interval=4)
        definition["strategy"]["initial_cash_cny"] = "10000"
        definition["strategy"]["modules"]["risk_management"] = {
            "kind": "builtin_risk/v1", "stop_loss_threshold": 0.1,
        }
        definition["costs"] = dict.fromkeys(definition["costs"], "0")
        blocked = transition_strategy(
            slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
            origin_session=SESSIONS[0],
        )
        assert blocked.finalized["rejections"][-1]["reason"] == "lower_limit_sell"
        assert blocked.finalized["positions"][0]["execution_shares"] == 1000
        assert Decimal(blocked.finalized["positions"][0]["remaining_acquisition_cost_cny"]) == 10000
        if next_close == "10":
            assert blocked.resumable["pending_target"] is None
        else:
            assert blocked.resumable["pending_target"]["decision_session"] == SESSIONS[2]
        result = transition_strategy(
            data, matrix, definition, origin_session=SESSIONS[0], continuation=blocked.resumable,
        ).finalized
        assert [row["session"] for row in result["fills"]
                if row["side"] == "sell"] == expected_sales


def test_published_result_retains_close_risk_nav_and_position_account_facts():
    from test_manual_strategy_ledger import _kernel_run, _set_alpha_closes
    from test_result_bundle_contract import _verified_bundle

    from thesistrace.research_run.result import (
        build_result_payload,
        read_result_bundle,
        result_publication_payloads,
    )

    canonical = _canonical(opens={session: {A: "10", B: "10"} for session in SESSIONS})
    _set_alpha_closes(canonical, {session: {A: "9", B: "9"} for session in SESSIONS})
    output = _kernel_run(canonical, selection_interval=4)
    result = build_result_payload(output, research_kind="strategy_backtest")
    expected = output.artifacts_snapshot()["strategy_backtest"]["daily"][-1]
    assert result["strategy_daily_observations"][-1]["close_risk_nav_cny"] == (
        expected["close_risk_nav_cny"]
    )
    assert expected["close_risk_nav_cny"] != expected["net_nav"]
    payloads = result_publication_payloads(result, research_kind="strategy_backtest")
    reopened = read_result_bundle(_verified_bundle(payloads), research_kind="strategy_backtest")
    assert reopened == result
    assert (reopened["terminal_strategy_state"]["close_risk_nav_cny"]
            == expected["close_risk_nav_cny"])
    position = reopened["terminal_strategy_state"]["positions"][0]
    assert position["holding_age"] == 3
    assert position["holding_cycle_started_session"] == SESSIONS[1]
    assert Decimal(position["last_close_adjusted_price"]) == 9
    assert Decimal(position["last_adjusted_price"]) == 10
