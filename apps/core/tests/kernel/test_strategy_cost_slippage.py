import copy
from decimal import Decimal

import pytest
from series import aligned_market_data
from test_manual_strategy_ledger import SESSIONS, A, B, _alpha_matrix, _canonical, _definition

from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_series import slice_research_sessions


def buy_at_constant_open(
    *, initial_cash="10020", adjusted_open="100", upper="110", slippage="10", exposure=1,
):
    data = aligned_market_data(_canonical(
        opens={session: {A: ("100", adjusted_open), B: "100"} for session in SESSIONS},
        limit_overrides={(session, A): (upper, "90") for session in SESSIONS},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = initial_cash
    definition["strategy"]["exposure_expression"] = {"kind": "number", "value": exposure}
    definition["costs"]["slippage_bps"] = slippage
    bought = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    )
    return data, matrix, definition, bought


@pytest.mark.parametrize("adjusted_open,units", [("100", "100"), ("200", "50")])
def test_slippage_round_trip_matches_manual_cash_and_dual_unit_ledger(adjusted_open, units):
    data, matrix, definition, bought = buy_at_constant_open(adjusted_open=adjusted_open)
    buy = bought.finalized["fills"][0]
    assert buy["quantity"] == 100
    assert Decimal(buy["net_cash_delta"]) == Decimal("-10015.1001")
    assert Decimal(buy["gross_cash_delta"]) == Decimal("-10010")
    assert Decimal(buy["cost"]) == Decimal("5.1001")
    assert {name: Decimal(buy[name]) for name in (
        "raw_open", "execution_price", "price_slippage", "commission_cny",
        "stamp_duty_cny", "transfer_fee_cny",
    )} == {
        "raw_open": Decimal("100"), "execution_price": Decimal("100.1"),
        "price_slippage": Decimal("0.1"), "commission_cny": Decimal("5"),
        "stamp_duty_cny": Decimal("0"), "transfer_fee_cny": Decimal("0.1001"),
    }
    assert Decimal(buy["adjusted_units_delta"]) == Decimal(units)
    assert Decimal(bought.finalized["daily"][-1]["gross_nav"]) == Decimal("10010")

    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1],
        "execution": "next_research_session_open",
        "contract_checksum": state["decision_state"]["selection"]["contract_checksum"],
        "reason": "close_position",
        "allocation": None,
        "position_limits": {A: 0},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    sale = sold["fills"][-1]
    assert sale["side"] == "sell"
    assert sale["quantity"] == 100
    assert Decimal(sale["research_settlement"]) == Decimal("9990")
    assert Decimal(sale["net_cash_delta"]) == Decimal("9979.9051")
    assert Decimal(sale["cost"]) == Decimal("10.0949")
    assert Decimal(sale["execution_price"]) == Decimal("99.9")
    assert Decimal(sale["price_slippage"]) == Decimal("-0.1")
    assert Decimal(sale["commission_cny"]) == Decimal("5")
    assert Decimal(sale["stamp_duty_cny"]) == Decimal("4.995")
    assert Decimal(sale["transfer_fee_cny"]) == Decimal("0.0999")
    assert sold["positions"] == []
    assert Decimal(sold["daily"][-1]["gross_nav"]) == Decimal("10000")
    assert Decimal(sold["daily"][-1]["net_nav"]) == Decimal("9984.805")


@pytest.mark.parametrize("cash,shares", [("10015.10", 0), ("10015.11", 100)])
def test_buy_affordability_includes_slippage_and_fees(cash, shares):
    _, _, _, result = buy_at_constant_open(initial_cash=cash)
    assert sum(fill["quantity"] for fill in result.finalized["fills"]) == shares
    assert Decimal(result.finalized["daily"][-1]["net_cash"]) >= 0


def test_synthetic_price_can_cross_limit_while_raw_open_still_controls_rejection():
    _, _, _, executable = buy_at_constant_open(upper="100.05")
    assert executable.finalized["rejections"] == []
    assert Decimal(executable.finalized["fills"][0]["gross_cash_delta"]) == Decimal("-10010")
    _, _, _, blocked = buy_at_constant_open(upper="100")
    assert blocked.finalized["fills"] == []
    assert [row["reason"] for row in blocked.finalized["rejections"]] == ["upper_limit_buy"]


def test_sell_price_stays_positive_for_slippage_arbitrarily_close_to_ceiling():
    data, matrix, definition, bought = buy_at_constant_open(
        initial_cash="30000", slippage="9999." + "9" * 100,
    )
    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["decision_state"]["selection"]["contract_checksum"],
        "reason": "close_position", "allocation": None, "position_limits": {A: 0},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    sale = sold["fills"][-1]
    assert sale["side"] == "sell"
    assert Decimal(sale["execution_price"]) == Decimal("1e-102")


def test_split_fills_charge_each_minimum_and_reconcile_custom_slippage_cash():
    data = aligned_market_data(_canonical(
        opens={session: {A: "1", B: "1"} for session in SESSIONS},
        limit_overrides={(session, A): ("2", "0.5") for session in SESSIONS},
    ), universe="manual")
    matrix = _alpha_matrix({session: ((A, 2), (B, 1)) for session in SESSIONS})
    definition = _definition(selection_interval=4)
    definition["strategy"]["initial_cash_cny"] = "1001120.12"
    definition["costs"].update(commission_rate_all_in="0", slippage_bps="10")
    result = transition_strategy(
        slice_research_sessions(data, SESSIONS[:2]), matrix, definition,
        origin_session=SESSIONS[0],
    ).finalized
    fills = result["fills"]
    assert [fill["quantity"] for fill in fills] == [1000000, 100]
    assert [Decimal(fill["commission_cny"]) for fill in fills] == [Decimal("5"), Decimal("5")]
    assert [Decimal(fill["transfer_fee_cny"]) for fill in fills] == [
        Decimal("10.01"), Decimal("0.001001"),
    ]
    assert sum(Decimal(fill["net_cash_delta"]) for fill in fills) == Decimal("-1001120.111001")
    assert Decimal(result["daily"][-1]["net_cash"]) == Decimal("0.008999")


def test_monetary_buy_target_uses_execution_price_even_with_spare_cash():
    _, _, _, result = buy_at_constant_open(
        initial_cash="100000", slippage="1000", exposure=0.5,
    )
    fill = result.finalized["fills"][0]
    # 50,000 / 110 = 454 shares before the 100-share lot rule.
    assert fill["quantity"] == 400
    assert Decimal(fill["net_cash_delta"]) == Decimal("-44013.64")


@pytest.mark.parametrize("adjusted_open", ["100", "200"])
def test_monetary_sell_target_uses_directional_price_and_research_units(adjusted_open):
    data, matrix, definition, bought = buy_at_constant_open(
        initial_cash="100000", slippage="1000", exposure=0.8, adjusted_open=adjusted_open,
    )
    assert bought.finalized["fills"][0]["quantity"] == 700
    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["decision_state"]["selection"]["contract_checksum"],
        "reason": "reduce_target", "position_limits": {},
        "allocation": {"mode": "rebalance", "exposure": 0.35,
                       "instrument_ids": [A], "relative_weights": {A: "1"}},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    # Net NAV 92,976.13; desired 32,541.6455; sell budget 37,458.3545.
    # Divide by 90 research CNY per execution share: 416, rounded to 400 shares.
    sale = sold["fills"][-1]
    assert sale["side"] == "sell"
    assert sale["quantity"] == 400
    assert Decimal(sale["research_settlement"]) == Decimal("36000")
    assert Decimal(sale["net_cash_delta"]) == Decimal("35970.84")


def test_explicit_local_share_limit_is_not_resized_by_slippage():
    data, matrix, definition, bought = buy_at_constant_open(
        initial_cash="100000", slippage="5000",
    )
    assert bought.finalized["fills"][0]["quantity"] == 600
    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["decision_state"]["selection"]["contract_checksum"],
        "reason": "local_limit", "allocation": None, "position_limits": {A: 300},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    assert sold["fills"][-1]["quantity"] == 300
    assert sold["positions"][0]["execution_shares"] == 300


def test_one_reduction_target_cannot_repurchase_after_its_slipped_sale():
    data, matrix, definition, bought = buy_at_constant_open(
        initial_cash="100000", slippage="5000", exposure=0.8,
    )
    assert bought.finalized["fills"][0]["quantity"] == 500
    state = copy.deepcopy(bought.resumable)
    state["pending_target"] = {
        "decision_session": SESSIONS[1], "execution": "next_research_session_open",
        "contract_checksum": state["decision_state"]["selection"]["contract_checksum"],
        "reason": "reduce_target", "position_limits": {},
        "allocation": {"mode": "rebalance", "exposure": 0.35,
                       "instrument_ids": [A], "relative_weights": {A: "1"}},
    }
    sold = transition_strategy(
        slice_research_sessions(data, SESSIONS[:3]), matrix, definition,
        origin_session=SESSIONS[0], continuation=state,
    ).finalized
    fills = [fill for fill in sold["fills"] if fill["session"] == SESSIONS[2]]
    assert [(fill["side"], fill["quantity"]) for fill in fills] == [("sell", 400)]
    assert sold["positions"][0]["execution_shares"] == 100
