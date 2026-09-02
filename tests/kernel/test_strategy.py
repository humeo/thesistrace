import copy
from decimal import Decimal

import pytest
from series import aligned_market_data

from contracts import CLOSE_ADJUSTED, FIELD_BINDINGS
from thesistrace.fixture import build_fixture
from thesistrace.research_kernel.alpha import evaluate_alpha_matrix, validate_alpha
from thesistrace.research_kernel.strategy import (
    StrategyCalculationError,
    advance_strategy_metric_state,
    legal_order_quantity,
    market_rejection_reason,
    maximum_drawdown,
    run_strategy,
    split_child_orders,
    strategy_metrics_from_state,
    transaction_cost,
)


def test_a_share_quantity_child_order_and_cost_rules() -> None:
    assert legal_order_quantity("main", "buy", 1059, complete_liquidation=False) == 1000
    assert legal_order_quantity("chinext", "sell", 199, complete_liquidation=False) == 100
    assert legal_order_quantity("star", "buy", 199, complete_liquidation=False) == 0
    assert legal_order_quantity("star", "buy", 237, complete_liquidation=False) == 237
    assert legal_order_quantity("main", "sell", 37, complete_liquidation=True) == 37
    assert split_child_orders("main", 2_100_000) == [1_000_000, 1_000_000, 100_000]
    assert split_child_orders("chinext", 650_000) == [300_000, 300_000, 50_000]
    assert split_child_orders("star", 200_001) == [100_000, 99_801, 200]
    assert split_child_orders("main", 1_000_050, complete_liquidation=True) == [1_000_000, 50]
    with pytest.raises(StrategyCalculationError, match="board lot"):
        split_child_orders("main", 1_000_050)

    costs = {
        "commission_rate_all_in": Decimal("0.0003"),
        "commission_min_cny": Decimal("5"),
        "stamp_duty_sell_rate": Decimal("0.0005"),
        "transfer_fee_rate": Decimal("0.00001"),
    }
    assert transaction_cost(Decimal("1000"), "buy", costs) == Decimal("5.01000")
    assert transaction_cost(Decimal("1000"), "sell", costs) == Decimal("5.51000")


def test_market_rejections_are_three_explicit_categories() -> None:
    assert (
        market_rejection_reason(
            side="buy",
            state="full_session_suspension",
            raw_open=None,
            upper=Decimal("11"),
            lower=Decimal("9"),
        )
        == "suspension"
    )
    assert (
        market_rejection_reason(
            side="buy",
            state="normal",
            raw_open=Decimal("11"),
            upper=Decimal("11"),
            lower=Decimal("9"),
        )
        == "upper_limit_buy"
    )
    assert (
        market_rejection_reason(
            side="sell",
            state="normal",
            raw_open=Decimal("9"),
            upper=Decimal("11"),
            lower=Decimal("9"),
        )
        == "lower_limit_sell"
    )
    assert (
        market_rejection_reason(
            side="buy",
            state="normal",
            raw_open=Decimal("10"),
            upper=Decimal("11"),
            lower=Decimal("9"),
        )
        is None
    )


def test_top_n_strategy_runs_one_deterministic_net_primary_account() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    definition = {
        "universe": "top300",
        "strategy": {
            "holdings_count": 10,
            "rebalance_interval": 5,
            "initial_cash_cny": "10000000",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
    }

    origin_session = str(canonical["research_calendar"][0])
    result = run_strategy(
        aligned_market_data(canonical),
        matrix,
        definition,
        origin_session=origin_session,
    )
    repeated = run_strategy(
        aligned_market_data(canonical),
        matrix,
        definition,
        origin_session=origin_session,
    )

    assert result["checksum"] == repeated["checksum"]
    assert len(result["daily"]) == len(canonical["research_calendar"])
    assert result["daily"][0]["net_nav"] == "1e+7"
    assert result["daily"][0]["holdings_count"] == 0
    assert result["daily"][1]["holdings_count"] > 0
    assert result["daily"][1]["gross_return"] == 0
    assert result["daily"][1]["net_return"] < 0
    assert result["daily"][-1]["cycle_type"] == "terminal_valuation"
    assert result["daily"][-1]["rebalance"] is False
    assert all(Decimal(day["net_cash"]) >= 0 for day in result["daily"])
    assert all(isinstance(position["execution_shares"], int) for position in result["positions"])
    assert all("adjusted_units" in position for position in result["positions"])

    metrics = result["metrics"]
    assert set(metrics) >= {
        "gross_cumulative_return",
        "net_cumulative_return",
        "gross_cagr",
        "net_cagr",
        "maximum_drawdown",
        "annualized_volatility",
        "sharpe",
        "calmar",
        "turnover",
        "transaction_costs",
        "holdings_count",
        "maximum_single_name_weight",
        "cash_ratio",
        "market_rejections",
    }
    assert metrics["turnover"]["events"]
    assert metrics["turnover"]["average_rebalance"] is not None
    assert metrics["turnover"]["annualized"] is not None
    assert metrics["transaction_costs"]["cumulative_amount"] > 0
    assert metrics["risk_free_rate"] == 0
    assert metrics["market_rejections"] == {
        "upper_limit_buy": 0,
        "lower_limit_sell": 0,
        "suspension": 0,
    }
    assert all(
        event["side_order"]
        == sorted(event["side_order"], key=lambda side: 0 if side == "sell" else 1)
        for event in result["rebalance_events"]
    )
    assert all(order["order_id"] == index for index, order in enumerate(result["orders"]))
    assert all(
        result["orders"][child["order_id"]]["instrument_id"] == child["instrument_id"]
        for child in result["child_orders"]
    )
    assert result["rebalance_events"][0]["target_weights"]
    assert result["rebalance_events"][0]["actual_weights"]

    metric_state = None
    midpoint = len(result["daily"]) // 2
    for chunk in (result["daily"][:midpoint], result["daily"][midpoint:]):
        sessions = {str(row["session"]) for row in chunk}
        metric_state = advance_strategy_metric_state(
            metric_state,
            daily=chunk,
            turnover_events=[
                event
                for event in metrics["turnover"]["events"]
                if str(event["session"]) in sessions
            ],
            cumulative_cost=Decimal(str(chunk[-1]["cumulative_transaction_cost"])),
            rejections=[
                rejection
                for rejection in result["rejections"]
                if str(rejection["session"]) in sessions
            ],
        )
    assert metric_state is not None
    compact_metrics = copy.deepcopy(metrics)
    compact_metrics["maximum_drawdown"].pop("series")
    compact_metrics["turnover"].pop("events")
    compact_metrics["holdings_count"].pop("daily")
    compact_metrics["maximum_single_name_weight"].pop("daily")
    compact_metrics["cash_ratio"].pop("daily")
    state_metrics = strategy_metrics_from_state(metric_state)
    state_metrics["maximum_drawdown"].pop("series")
    state_metrics["turnover"].pop("events")
    state_metrics["holdings_count"].pop("daily")
    state_metrics["maximum_single_name_weight"].pop("daily")
    state_metrics["cash_ratio"].pop("daily")
    assert state_metrics == compact_metrics


def test_unexplained_missing_held_open_fails_instead_of_becoming_suspension() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    definition = {
        "universe": "top300",
        "strategy": {
            "holdings_count": 10,
            "rebalance_interval": 1,
            "initial_cash_cny": "10000000",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
    }
    report_start = 0
    missing_session = canonical["research_calendar"][report_start + 2]
    held_candidate = matrix["sessions"][report_start]["values"][-1]["instrument_id"]
    canonical["prices"] = [
        row
        for row in canonical["prices"]
        if not (row["session"] == missing_session and row["instrument_id"] == held_candidate)
    ]
    canonical["trading_states"] = [
        row
        for row in canonical["trading_states"]
        if not (row["session"] == missing_session and row["instrument_id"] == held_candidate)
    ]

    with pytest.raises(StrategyCalculationError, match="unexplained missing Open"):
        run_strategy(
            aligned_market_data(canonical),
            matrix,
            definition,
            origin_session=str(canonical["research_calendar"][report_start]),
        )


def test_suspended_holding_carries_valuation() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    definition = strategy_definition(rebalance_interval=20)
    report_start = 0
    suspended_session = canonical["research_calendar"][report_start + 2]
    held_candidate = matrix["sessions"][report_start]["values"][-1]["instrument_id"]
    canonical["prices"] = [
        row
        for row in canonical["prices"]
        if not (row["session"] == suspended_session and row["instrument_id"] == held_candidate)
    ]
    for row in canonical["trading_states"]:
        if row["session"] == suspended_session and row["instrument_id"] == held_candidate:
            row["state"] = "full_session_suspension"

    result = run_strategy(
        aligned_market_data(canonical),
        matrix,
        definition,
        origin_session=str(canonical["research_calendar"][report_start]),
    )

    assert {
        "session": suspended_session,
        "instrument_id": held_candidate,
        "type": "valuation_carry",
    } in result["daily"][2]["valuation_events"]


def test_suspended_new_target_creates_one_logical_rejection_without_children() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    report_start = 0
    execution_session = canonical["research_calendar"][report_start + 1]
    target = matrix["sessions"][report_start]["values"][-1]["instrument_id"]
    canonical["prices"] = [
        row
        for row in canonical["prices"]
        if not (row["session"] == execution_session and row["instrument_id"] == target)
    ]
    for row in canonical["trading_states"]:
        if row["session"] == execution_session and row["instrument_id"] == target:
            row["state"] = "full_session_suspension"

    result = run_strategy(
        aligned_market_data(canonical),
        matrix,
        strategy_definition(rebalance_interval=20),
        origin_session=str(canonical["research_calendar"][report_start]),
    )

    rejection = next(
        item
        for item in result["rejections"]
        if item["session"] == execution_session and item["instrument_id"] == target
    )
    assert rejection["reason"] == "suspension"
    assert rejection["order_id"] == result["orders"][rejection["order_id"]]["order_id"]
    assert all(child["order_id"] != rejection["order_id"] for child in result["child_orders"])


def test_data_unavailable_new_target_is_rejected_without_execution() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    execution_session = canonical["research_calendar"][1]
    target = matrix["sessions"][0]["values"][-1]["instrument_id"]
    for table in ("prices", "price_limits"):
        canonical[table] = [
            row
            for row in canonical[table]
            if not (
                row["session"] == execution_session
                and row["instrument_id"] == target
            )
        ]
    for row in canonical["trading_states"]:
        if row["session"] == execution_session and row["instrument_id"] == target:
            row["state"] = "data_unavailable"

    result = run_strategy(
        aligned_market_data(canonical),
        matrix,
        strategy_definition(rebalance_interval=20),
        origin_session=str(canonical["research_calendar"][0]),
    )

    rejection = next(
        item
        for item in result["rejections"]
        if item["session"] == execution_session and item["instrument_id"] == target
    )
    assert rejection["reason"] == "data_unavailable"
    assert all(child["order_id"] != rejection["order_id"] for child in result["child_orders"])


def test_terminal_delisting_writes_off_without_an_order_or_cost() -> None:
    _, canonical = build_fixture()
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(CLOSE_ADJUSTED, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    definition = strategy_definition(rebalance_interval=20)
    report_start = 0
    delist_session = canonical["research_calendar"][report_start + 2]
    held_candidate = matrix["sessions"][report_start]["values"][-1]["instrument_id"]
    canonical["prices"] = [
        row
        for row in canonical["prices"]
        if not (row["session"] == delist_session and row["instrument_id"] == held_candidate)
    ]
    for instrument in canonical["instruments"]:
        if instrument["instrument_id"] == held_candidate:
            instrument["listed_to"] = delist_session
    for universe in canonical["liquidity_universes"].values():
        for snapshot in universe:
            if snapshot["session"] >= delist_session:
                snapshot["instrument_ids"] = [
                    instrument_id
                    for instrument_id in snapshot["instrument_ids"]
                    if instrument_id != held_candidate
                ]

    result = run_strategy(
        aligned_market_data(canonical),
        matrix,
        definition,
        origin_session=str(canonical["research_calendar"][report_start]),
    )

    event = {
        "session": delist_session,
        "instrument_id": held_candidate,
        "type": "terminal_delisting_writeoff",
    }
    assert event in result["daily"][2]["valuation_events"]
    assert all(
        not (order["session"] == delist_session and order["instrument_id"] == held_candidate)
        for order in result["orders"]
    )


def test_drawdown_is_a_non_negative_loss_with_recovery() -> None:
    daily = [{"session": value} for value in ("d1", "d2", "d3", "d4")]
    drawdown = maximum_drawdown(
        daily,
        [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("121")],
    )

    assert drawdown["value"] == 0.25
    assert drawdown["peak_session"] == "d2"
    assert drawdown["trough_session"] == "d3"
    assert drawdown["recovery_session"] == "d4"
    assert drawdown["unrecovered"] is False
    assert all(point["drawdown"] >= 0 for point in drawdown["series"])


def strategy_definition(*, rebalance_interval: int) -> dict[str, object]:
    return {
        "universe": "top300",
        "strategy": {
            "holdings_count": 10,
            "rebalance_interval": rebalance_interval,
            "initial_cash_cny": "10000000",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
    }
