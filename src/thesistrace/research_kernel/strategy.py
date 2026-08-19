import hashlib
import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from fractions import Fraction
from heapq import nsmallest
from statistics import stdev

import numpy as np

from thesistrace.research_kernel.numeric import (
    ACCOUNTING_CONTEXT,
    canonical_decimal,
    require_finite_decimal,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    ExecutionPrice,
    InstrumentProfile,
    PriceLimit,
    slice_research_sessions,
)

INITIAL_CASH = Decimal("10000000")


class StrategyCalculationError(RuntimeError):
    pass


def _alpha_rank_key(item: Mapping[str, object]) -> tuple[Decimal, str]:
    return -Decimal(str(item["value"])), str(item["instrument_id"])


@dataclass
class Position:
    execution_shares: int
    adjusted_units: Decimal
    last_adjusted_price: Decimal


@dataclass(frozen=True)
class StrategyTransition:
    finalized: dict[str, object]
    resumable: dict[str, object]
    ledger: tuple[dict[str, object], ...]


def transition_strategy(
    research_data: AlignedResearchData,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str,
    continuation: dict[str, object] | None = None,
) -> StrategyTransition:
    """Calculate a boundary and retain the state immediately before its terminal."""
    return _transition_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        slice_resumable=lambda sessions: slice_research_sessions(research_data, sessions),
    )


def transition_columnar_strategy(
    research_data: ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str,
    continuation: dict[str, object] | None = None,
    cancellation_check: Callable[[], None],
) -> StrategyTransition:
    return _transition_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        slice_resumable=lambda sessions: research_data.slice_sessions(sessions),
        cancellation_check=cancellation_check,
    )


def _transition_strategy(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str,
    continuation: dict[str, object] | None,
    slice_resumable: Callable[
        [tuple[str, ...]], AlignedResearchData | ColumnarResearchSeries
    ],
    cancellation_check: Callable[[], None] | None = None,
) -> StrategyTransition:
    ledger: list[dict[str, object]] = []
    finalized = run_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        ledger=ledger,
        cancellation_check=cancellation_check,
    )
    calendar = list(research_data.sessions)
    resumable_research_data = (
        research_data
        if calendar[-1] == origin_session
        else slice_resumable(tuple(calendar[:-1]))
    )
    resumable = run_strategy(
        resumable_research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        terminal_cutoff=False,
        continuation=continuation,
        cancellation_check=cancellation_check,
    )
    return StrategyTransition(
        finalized=finalized,
        resumable=resumable,
        ledger=tuple(ledger),
    )


def legal_order_quantity(
    board: str,
    side: str,
    target_quantity: int,
    *,
    complete_liquidation: bool,
) -> int:
    del side
    quantity = max(0, int(target_quantity))
    if complete_liquidation:
        return quantity
    if board in {"main", "chinext"}:
        return quantity // 100 * 100
    if board == "star":
        return quantity if quantity >= 200 else 0
    raise StrategyCalculationError(f"unsupported board: {board}")


def split_child_orders(
    board: str,
    quantity: int,
    *,
    complete_liquidation: bool = False,
) -> list[int]:
    caps = {"main": 1_000_000, "chinext": 300_000, "star": 100_000}
    minimums = {"main": 100, "chinext": 100, "star": 200}
    if board not in caps:
        raise StrategyCalculationError(f"unsupported board: {board}")
    if not complete_liquidation and board in {"main", "chinext"} and quantity % 100:
        raise StrategyCalculationError("non-liquidation child order is not a board lot")
    cap = caps[board]
    minimum = minimums[board]
    children: list[int] = []
    remaining = quantity
    while remaining > cap:
        children.append(cap)
        remaining -= cap
    if remaining:
        if complete_liquidation:
            children.append(remaining)
            return children
        if children and remaining < minimum:
            adjustment = minimum - remaining
            children[-1] -= adjustment
            remaining += adjustment
        children.append(remaining)
    return children


def transaction_cost(
    raw_notional: Decimal,
    side: str,
    costs: dict[str, Decimal],
) -> Decimal:
    with accounting_context():
        commission = max(
            raw_notional * costs["commission_rate_all_in"],
            costs["commission_min_cny"],
        )
        total = commission + raw_notional * costs["transfer_fee_rate"]
        if side == "sell":
            total += raw_notional * costs["stamp_duty_sell_rate"]
    return require_finite_decimal(total)


def market_rejection_reason(
    *,
    side: str,
    state: str | None,
    raw_open: Decimal | None,
    upper: Decimal,
    lower: Decimal,
) -> str | None:
    if state == "full_session_suspension":
        return "suspension"
    if state == "data_unavailable":
        return "data_unavailable"
    if raw_open is None:
        return None
    if side == "buy" and raw_open >= upper:
        return "upper_limit_buy"
    if side == "sell" and raw_open <= lower:
        return "lower_limit_sell"
    return None


def run_strategy(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str | None = None,
    terminal_cutoff: bool = True,
    continuation: dict[str, object] | None = None,
    skip_execution_sessions: set[str] | None = None,
    ledger: list[dict[str, object]] | None = None,
    cancellation_check: Callable[[], None] | None = None,
) -> dict[str, object]:
    calendar = list(research_data.sessions)
    if continuation is None:
        if origin_session is None:
            raise StrategyCalculationError("Strategy requires an explicit origin session")
        origin_index = calendar.index(origin_session)
        processing_start = origin_index
    else:
        prior_daily = continuation.get("daily")
        if not isinstance(prior_daily, list) or not prior_daily:
            raise StrategyCalculationError("continuation has no Strategy history")
        last_session = str(prior_daily[-1]["session"])
        processing_start = calendar.index(last_session) + 1
        report_session_count = int(continuation.get("report_session_count", len(prior_daily)))
        if report_session_count < len(prior_daily):
            raise StrategyCalculationError("continuation report session count is invalid")
        origin_index = processing_start - report_session_count
    report_calendar = calendar[processing_start:]
    strategy = definition["strategy"]
    holdings_count = int(strategy["holdings_count"])
    rebalance_interval = int(strategy["rebalance_interval"])
    if not 1 <= holdings_count <= 100 or not 1 <= rebalance_interval <= 20:
        raise StrategyCalculationError("invalid Strategy breadth or schedule")
    if Decimal(str(strategy["initial_cash_cny"])) != INITIAL_CASH:
        raise StrategyCalculationError("invalid Initial Cash")
    costs = {name: Decimal(str(value)) for name, value in definition["costs"].items()}
    skipped_sessions = skip_execution_sessions or set()

    instruments = research_data.instruments
    prices = research_data.execution_prices
    states = research_data.trading_states
    limits = research_data.price_limits
    value_store = alpha_matrix.get("value_store")
    alpha_by_session = (
        value_store
        if isinstance(value_store, Mapping)
        else {str(item["session"]): item["values"] for item in alpha_matrix["sessions"]}
    )
    universes = research_data.universe_members
    columnar_benchmark: tuple[
        dict[str, int],
        dict[str, int],
        np.ndarray,
        np.ndarray,
    ] | None = None
    if isinstance(research_data, ColumnarResearchSeries):
        benchmark_instruments = tuple(
            sorted(
                {
                    instrument_id
                    for session in calendar
                    for instrument_id in universes.get(session, ())
                }
            )
        )
        columnar_benchmark = (
            {
                instrument_id: index
                for index, instrument_id in enumerate(benchmark_instruments)
            },
            {session: index for index, session in enumerate(calendar)},
            research_data.adjusted_open_decimal_matrix(benchmark_instruments),
            research_data.adjusted_open_matrix(benchmark_instruments),
        )

    if continuation is None:
        positions: dict[str, Position] = {}
        gross_cash = INITIAL_CASH
        net_cash = INITIAL_CASH
        cumulative_cost = Decimal(0)
        benchmark_nav = Decimal(1)
        daily: list[dict[str, object]] = []
        fills: list[dict[str, object]] = []
        orders: list[dict[str, object]] = []
        child_orders: list[dict[str, object]] = []
        rejections: list[dict[str, object]] = []
        diagnostics: list[dict[str, object]] = []
        rebalance_events: list[dict[str, object]] = []
        turnover_events: list[dict[str, object]] = []
        prior_metric_state: dict[str, object] | None = None
        prior_daily_count = 0
    else:
        position_rows = continuation.get("positions")
        if not isinstance(position_rows, list):
            raise StrategyCalculationError("continuation positions are invalid")
        positions = {
            str(item["instrument_id"]): Position(
                execution_shares=int(item["execution_shares"]),
                adjusted_units=Decimal(str(item["adjusted_units"])),
                last_adjusted_price=Decimal(str(item["last_adjusted_price"])),
            )
            for item in position_rows
        }
        daily = [dict(item) for item in continuation["daily"]]
        prior_daily_count = len(daily)
        last_daily = daily[-1]
        gross_cash = Decimal(str(last_daily["gross_cash"]))
        net_cash = Decimal(str(last_daily["net_cash"]))
        cumulative_cost = Decimal(str(last_daily["cumulative_transaction_cost"]))
        benchmark_nav = Decimal(str(last_daily["benchmark_nav"]))
        fills = [dict(item) for item in continuation.get("fills", [])]
        orders = [dict(item) for item in continuation.get("orders", [])]
        child_orders = [dict(item) for item in continuation.get("child_orders", [])]
        rejections = [dict(item) for item in continuation.get("rejections", [])]
        diagnostics = [dict(item) for item in continuation.get("diagnostics", [])]
        rebalance_events = [dict(item) for item in continuation.get("rebalance_events", [])]
        metric_state = continuation.get("metric_state")
        prior_metric_state = dict(metric_state) if isinstance(metric_state, Mapping) else None
        if prior_metric_state is None:
            prior_turnover = continuation.get("metrics", {}).get("turnover", {}).get("events", [])
            turnover_events = [dict(item) for item in prior_turnover]
        else:
            turnover_events = []

    for session in report_calendar:
        if cancellation_check is not None:
            cancellation_check()
        global_index = calendar.index(session)
        report_index = global_index - origin_index
        marks, valuation_events = mark_positions(session, positions, prices, states, instruments)
        pre_gross_nav = money(gross_cash + sum_position_values(positions, marks))
        pre_net_nav = money(net_cash + sum_position_values(positions, marks))
        pre_weights = account_weights(net_cash, pre_net_nav, positions, marks)
        cycle_type = (
            "terminal_valuation"
            if terminal_cutoff and global_index == len(calendar) - 1
            else "open"
        )
        rebalance = False
        benchmark_return = Decimal(0)
        event_side_order: list[str] = []
        event_intended_orders: list[dict[str, object]] = []
        event_order_start = len(orders)
        event_fill_start = len(fills)
        event_rejection_start = len(rejections)
        event_diagnostic_start = len(diagnostics)
        event_cost_start = cumulative_cost
        execution_signal: dict[str, object] | None = None

        signal_index = global_index - 1
        if (
            report_index > 0
            and (not terminal_cutoff or global_index < len(calendar) - 1)
            and session not in skipped_sessions
            and (signal_index - origin_index) % rebalance_interval == 0
        ):
            rebalance = True
            signal_session = calendar[signal_index]
            alpha_values = alpha_by_session[signal_session]
            selected = nsmallest(holdings_count, alpha_values, key=_alpha_rank_key)
            candidates = [str(item["instrument_id"]) for item in selected]
            if ledger is not None:
                ranked = sorted(alpha_values, key=_alpha_rank_key)
                execution_signal = {
                    "session": signal_session,
                    "alpha_values": [dict(item) for item in ranked],
                    "selected_instrument_ids": candidates,
                }
            if not candidates:
                diagnostics.append(
                    {
                        "session": session,
                        "reason": "insufficient_candidates",
                        "available": 0,
                    }
                )
            target_value = money(pre_net_nav / max(1, len(candidates)))
            candidate_set = set(candidates)
            alpha_order = {instrument_id: index for index, instrument_id in enumerate(candidates)}

            for instrument_id in sorted(list(positions)):
                position = positions[instrument_id]
                current_value = money(position.adjusted_units * marks[instrument_id])
                desired_value = target_value if instrument_id in candidate_set else Decimal(0)
                if current_value <= desired_value:
                    continue
                complete = desired_value == 0
                if complete:
                    unrounded = position.execution_shares
                else:
                    reduction = current_value - desired_value
                    unrounded = int(
                        money(Decimal(position.execution_shares) * reduction / current_value)
                    )
                quantity = legal_order_quantity(
                    instruments[instrument_id].board,
                    "sell",
                    unrounded,
                    complete_liquidation=complete,
                )
                event_intended_orders.append(
                    {
                        "instrument_id": instrument_id,
                        "side": "sell",
                        "intended_value": canonical_decimal(current_value - desired_value),
                        "unrounded_quantity": unrounded,
                        "legal_quantity": quantity,
                    }
                )
                if quantity <= 0:
                    diagnostics.append(
                        {
                            "session": session,
                            "instrument_id": instrument_id,
                            "reason": "below_board_lot",
                            "side": "sell",
                            "unrounded_quantity": unrounded,
                        }
                    )
                    continue
                event_side_order.append("sell")
                gross_cash, net_cash, cost = execute_order(
                    session=session,
                    instrument_id=instrument_id,
                    side="sell",
                    quantity=quantity,
                    positions=positions,
                    prices=prices,
                    states=states,
                    limits=limits,
                    instruments=instruments,
                    costs=costs,
                    gross_cash=gross_cash,
                    net_cash=net_cash,
                    fills=fills,
                    orders=orders,
                    child_orders=child_orders,
                    rejections=rejections,
                    intended_value=current_value - desired_value,
                    unrounded_quantity=unrounded,
                )
                cumulative_cost = money(cumulative_cost + cost)

            marks, additional_events = mark_positions(
                session, positions, prices, states, instruments
            )
            valuation_events.extend(additional_events)
            for instrument_id in sorted(candidates, key=lambda value: alpha_order[value]):
                price = prices.get((session, instrument_id))
                current_value = (
                    money(positions[instrument_id].adjusted_units * marks[instrument_id])
                    if instrument_id in positions
                    else Decimal(0)
                )
                deficit = target_value - current_value
                if price is None:
                    if deficit <= 0:
                        continue
                    event_intended_orders.append(
                        {
                            "instrument_id": instrument_id,
                            "side": "buy",
                            "intended_value": canonical_decimal(deficit),
                            "unrounded_quantity": None,
                            "legal_quantity": None,
                        }
                    )
                    state = states.get((session, instrument_id))
                    listed_to = instruments[instrument_id].listed_to
                    if state in {"full_session_suspension", "data_unavailable"}:
                        rejection_reason = (
                            "suspension"
                            if state == "full_session_suspension"
                            else "data_unavailable"
                        )
                        order_id = len(orders)
                        orders.append(
                            {
                                "order_id": order_id,
                                "session": session,
                                "instrument_id": instrument_id,
                                "side": "buy",
                                "intended_value": canonical_decimal(deficit),
                                "unrounded_quantity": None,
                                "legal_quantity": None,
                            }
                        )
                        rejections.append(
                            {
                                "order_id": order_id,
                                "session": session,
                                "instrument_id": instrument_id,
                                "side": "buy",
                                "intended_value": canonical_decimal(deficit),
                                "reason": rejection_reason,
                            }
                        )
                        event_side_order.append("buy")
                        continue
                    if listed_to and listed_to <= session:
                        diagnostics.append(
                            {
                                "session": session,
                                "instrument_id": instrument_id,
                                "reason": "ineligible",
                                "side": "buy",
                            }
                        )
                        continue
                    raise StrategyCalculationError(
                        f"unexplained executable Open for {instrument_id} on {session}"
                    )
                else:
                    raw_open = Decimal(price.raw_open)
                    unrounded = int(deficit / raw_open) if deficit > 0 else 0
                    legal_quantity = (
                        legal_order_quantity(
                            instruments[instrument_id].board,
                            "buy",
                            unrounded,
                            complete_liquidation=False,
                        )
                        if raw_open > 0
                        else 0
                    )
                    quantity = affordable_quantity(
                        board=instruments[instrument_id].board,
                        quantity=legal_quantity,
                        raw_open=raw_open,
                        net_cash=net_cash,
                        costs=costs,
                    )
                    if deficit > 0:
                        event_intended_orders.append(
                            {
                                "instrument_id": instrument_id,
                                "side": "buy",
                                "intended_value": canonical_decimal(deficit),
                                "unrounded_quantity": unrounded,
                                "legal_quantity": legal_quantity,
                            }
                        )
                if quantity <= 0:
                    if legal_quantity <= 0 and unrounded > 0:
                        diagnostics.append(
                            {
                                "session": session,
                                "instrument_id": instrument_id,
                                "reason": "below_board_lot",
                                "side": "buy",
                                "unrounded_quantity": unrounded,
                            }
                        )
                    elif legal_quantity > 0:
                        diagnostics.append(
                            {
                                "session": session,
                                "instrument_id": instrument_id,
                                "reason": "insufficient_cash",
                                "side": "buy",
                                "legal_quantity": legal_quantity,
                            }
                        )
                    continue
                event_side_order.append("buy")
                gross_cash, net_cash, cost = execute_order(
                    session=session,
                    instrument_id=instrument_id,
                    side="buy",
                    quantity=quantity,
                    positions=positions,
                    prices=prices,
                    states=states,
                    limits=limits,
                    instruments=instruments,
                    costs=costs,
                    gross_cash=gross_cash,
                    net_cash=net_cash,
                    fills=fills,
                    orders=orders,
                    child_orders=child_orders,
                    rejections=rejections,
                    intended_value=deficit,
                    unrounded_quantity=unrounded,
                )
                cumulative_cost = money(cumulative_cost + cost)

            post_marks, post_events = mark_positions(
                session, positions, prices, states, instruments
            )
            valuation_events.extend(post_events)
            post_net_nav_for_turnover = money(net_cash + sum_position_values(positions, post_marks))
            post_weights = account_weights(
                net_cash, post_net_nav_for_turnover, positions, post_marks
            )
            turnover = weight_turnover(pre_weights, post_weights)
            turnover_events.append({"session": session, "value": turnover})
            rebalance_events.append(
                {
                    "session": session,
                    "signal_session": signal_session,
                    "side_order": event_side_order,
                    "fill_count": len(fills) - event_fill_start,
                    "turnover": turnover,
                    "target_weights": {
                        instrument_id: float(target_value / pre_net_nav)
                        for instrument_id in candidates
                    },
                    "actual_weights": {
                        key: value for key, value in post_weights.items() if key != "cash"
                    },
                }
            )
            marks = post_marks

        gross_nav = money(gross_cash + sum_position_values(positions, marks))
        net_nav = money(net_cash + sum_position_values(positions, marks))
        if net_cash < 0:
            raise StrategyCalculationError("Net Cash became negative")

        if report_index >= 2:
            signal_session = calendar[global_index - 2]
            entry_session = calendar[global_index - 1]
            benchmark_return = (
                columnar_equal_weight_benchmark_return(
                    signal_session,
                    entry_session,
                    session,
                    universes,
                    states,
                    instruments,
                    *columnar_benchmark,
                )
                if columnar_benchmark is not None
                else equal_weight_benchmark_return(
                    signal_session,
                    entry_session,
                    session,
                    universes,
                    prices,
                    states,
                    instruments,
                )
            )
            benchmark_nav = money(benchmark_nav * (Decimal(1) + benchmark_return))

        position_values = {
            instrument_id: money(position.adjusted_units * marks[instrument_id])
            for instrument_id, position in positions.items()
        }
        holdings = len(positions)
        max_weight = (
            max(float(value / net_nav) for value in position_values.values())
            if position_values and net_nav != 0
            else 0.0
        )
        cash_ratio = float(net_cash / net_nav) if net_nav != 0 else 0.0
        residual = money((gross_nav - net_nav) - cumulative_cost)
        previous_gross_nav = Decimal(str(daily[-1]["gross_nav"])) if daily else gross_nav
        previous_net_nav = Decimal(str(daily[-1]["net_nav"])) if daily else net_nav
        daily.append(
            {
                "session": session,
                "cycle_type": cycle_type,
                "rebalance": rebalance,
                "pre_trade_gross_nav": canonical_decimal(pre_gross_nav),
                "pre_trade_net_nav": canonical_decimal(pre_net_nav),
                "gross_nav": canonical_decimal(gross_nav),
                "net_nav": canonical_decimal(net_nav),
                "gross_return": float(gross_nav / previous_gross_nav - 1),
                "net_return": float(net_nav / previous_net_nav - 1),
                "gross_cash": canonical_decimal(gross_cash),
                "net_cash": canonical_decimal(net_cash),
                "benchmark_nav": canonical_decimal(benchmark_nav),
                "benchmark_return": float(benchmark_return),
                "cumulative_transaction_cost": canonical_decimal(cumulative_cost),
                "holdings_count": holdings,
                "maximum_single_name_weight": max_weight,
                "cash_ratio": cash_ratio,
                "execution_rounding_residual": canonical_decimal(residual),
                "valuation_events": unique_events(valuation_events),
            }
        )
        if ledger is not None:
            ledger.append(
                {
                    "session": session,
                    "cycle_type": cycle_type,
                    "signal": execution_signal,
                    "intended_orders": event_intended_orders,
                    "submitted_orders": [dict(item) for item in orders[event_order_start:]],
                    "fills": [dict(item) for item in fills[event_fill_start:]],
                    "rejections": [dict(item) for item in rejections[event_rejection_start:]],
                    "diagnostics": [dict(item) for item in diagnostics[event_diagnostic_start:]],
                    "gross_cash": canonical_decimal(gross_cash),
                    "net_cash": canonical_decimal(net_cash),
                    "positions": _position_payload(positions),
                    "transaction_cost_cny": canonical_decimal(cumulative_cost - event_cost_start),
                    "cumulative_transaction_cost": canonical_decimal(cumulative_cost),
                    "gross_nav": canonical_decimal(gross_nav),
                    "net_nav": canonical_decimal(net_nav),
                    "valuation_events": unique_events(valuation_events),
                }
            )
        if cancellation_check is not None:
            cancellation_check()

    if prior_metric_state is None:
        metrics = strategy_metrics(
            daily=daily,
            turnover_events=turnover_events,
            cumulative_cost=cumulative_cost,
            rejections=rejections,
        )
        metric_state = None
    else:
        metric_state = advance_strategy_metric_state(
            prior_metric_state,
            daily=daily[prior_daily_count:],
            turnover_events=turnover_events,
            cumulative_cost=cumulative_cost,
            rejections=rejections,
        )
        metrics = strategy_metrics_from_state(metric_state)
    positions_payload = _position_payload(positions)
    payload = {
        "alpha_checksum": alpha_matrix["checksum"],
        "initial_cash_cny": canonical_decimal(INITIAL_CASH),
        "daily": daily,
        "positions": positions_payload,
        "orders": orders,
        "child_orders": child_orders,
        "fills": fills,
        "rebalance_events": rebalance_events,
        "rejections": rejections,
        "diagnostics": diagnostics,
        "metrics": metrics,
    }
    if metric_state is not None:
        payload["metric_state"] = metric_state
    return {
        **payload,
        "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _position_payload(positions: Mapping[str, Position]) -> list[dict[str, object]]:
    return [
        {
            "instrument_id": instrument_id,
            "execution_shares": position.execution_shares,
            "adjusted_units": canonical_decimal(position.adjusted_units),
            "last_adjusted_price": canonical_decimal(position.last_adjusted_price),
        }
        for instrument_id, position in sorted(positions.items())
    ]


def mark_positions(
    session: str,
    positions: dict[str, Position],
    prices: dict[tuple[str, str], ExecutionPrice],
    states: dict[tuple[str, str], str],
    instruments: dict[str, InstrumentProfile],
) -> tuple[dict[str, Decimal], list[dict[str, object]]]:
    marks: dict[str, Decimal] = {}
    events: list[dict[str, object]] = []
    for instrument_id in list(positions):
        price = prices.get((session, instrument_id))
        if price is not None:
            mark = Decimal(price.adjusted_open)
            positions[instrument_id].last_adjusted_price = mark
            marks[instrument_id] = mark
            continue
        if states.get((session, instrument_id)) in {
            "full_session_suspension",
            "data_unavailable",
        }:
            marks[instrument_id] = positions[instrument_id].last_adjusted_price
            events.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "type": "valuation_carry",
                }
            )
            continue
        listed_to = instruments[instrument_id].listed_to
        if listed_to and listed_to <= session:
            positions.pop(instrument_id)
            events.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "type": "terminal_delisting_writeoff",
                }
            )
            continue
        raise StrategyCalculationError(
            f"unexplained missing Open for held instrument {instrument_id} on {session}"
        )
    return marks, events


def execute_order(
    *,
    session: str,
    instrument_id: str,
    side: str,
    quantity: int,
    positions: dict[str, Position],
    prices: dict[tuple[str, str], ExecutionPrice],
    states: dict[tuple[str, str], str],
    limits: dict[tuple[str, str], PriceLimit],
    instruments: dict[str, InstrumentProfile],
    costs: dict[str, Decimal],
    gross_cash: Decimal,
    net_cash: Decimal,
    fills: list[dict[str, object]],
    orders: list[dict[str, object]],
    child_orders: list[dict[str, object]],
    rejections: list[dict[str, object]],
    intended_value: Decimal,
    unrounded_quantity: int,
) -> tuple[Decimal, Decimal, Decimal]:
    price = prices.get((session, instrument_id))
    limit = limits.get((session, instrument_id))
    state = states.get((session, instrument_id))
    raw_open = Decimal(price.raw_open) if price is not None else None
    if limit is None and state not in {"full_session_suspension", "data_unavailable"}:
        raise StrategyCalculationError(f"missing price limit for {instrument_id} on {session}")
    upper = Decimal(limit.upper) if limit is not None else Decimal(0)
    lower = Decimal(limit.lower) if limit is not None else Decimal(0)
    rejection = market_rejection_reason(
        side=side,
        state=state,
        raw_open=raw_open,
        upper=upper,
        lower=lower,
    )
    order_id = len(orders)
    orders.append(
        {
            "order_id": order_id,
            "session": session,
            "instrument_id": instrument_id,
            "side": side,
            "intended_value": canonical_decimal(intended_value),
            "unrounded_quantity": unrounded_quantity,
            "legal_quantity": quantity,
        }
    )
    if rejection is not None:
        rejections.append(
            {
                "order_id": order_id,
                "session": session,
                "instrument_id": instrument_id,
                "side": side,
                "quantity": quantity,
                "intended_value": canonical_decimal(intended_value),
                "reason": rejection,
            }
        )
        return gross_cash, net_cash, Decimal(0)
    if price is None or raw_open is None:
        raise StrategyCalculationError(f"unexplained executable Open for {instrument_id}")
    adjusted_open = Decimal(price.adjusted_open)
    board = instruments[instrument_id].board
    total_cost = Decimal(0)
    total_quantity = 0
    position = positions.get(instrument_id)
    complete_liquidation = (
        side == "sell" and position is not None and position.execution_shares == quantity
    )
    for child_quantity in split_child_orders(
        board,
        quantity,
        complete_liquidation=complete_liquidation,
    ):
        child_order_id = len(child_orders)
        raw_notional = money(Decimal(child_quantity) * raw_open)
        child_cost = transaction_cost(raw_notional, side, costs)
        total_cost = money(total_cost + child_cost)
        total_quantity += child_quantity
        child_orders.append(
            {
                "child_order_id": child_order_id,
                "order_id": order_id,
                "session": session,
                "instrument_id": instrument_id,
                "side": side,
                "quantity": child_quantity,
            }
        )
        fills.append(
            {
                "child_order_id": child_order_id,
                "order_id": order_id,
                "session": session,
                "instrument_id": instrument_id,
                "side": side,
                "quantity": child_quantity,
                "raw_open": canonical_decimal(raw_open),
                "raw_notional": canonical_decimal(raw_notional),
                "cost": canonical_decimal(child_cost),
            }
        )
    if side == "buy":
        raw_notional = money(Decimal(total_quantity) * raw_open)
        with accounting_context():
            added_units = Decimal(total_quantity) / (adjusted_open / raw_open)
        position = positions.get(instrument_id)
        if position is None:
            positions[instrument_id] = Position(total_quantity, added_units, adjusted_open)
        else:
            position.execution_shares += total_quantity
            position.adjusted_units = money(position.adjusted_units + added_units)
            position.last_adjusted_price = adjusted_open
        gross_cash = money(gross_cash - raw_notional)
        net_cash = money(net_cash - raw_notional - total_cost)
    else:
        position = positions[instrument_id]
        before_shares = position.execution_shares
        with accounting_context():
            if total_quantity == before_shares:
                removed_units = position.adjusted_units
            else:
                removed_units = (
                    position.adjusted_units * Decimal(total_quantity) / Decimal(before_shares)
                )
            settlement = removed_units * adjusted_open
        gross_cash = money(gross_cash + settlement)
        net_cash = money(net_cash + settlement - total_cost)
        if total_quantity == before_shares:
            positions.pop(instrument_id)
        else:
            position.execution_shares -= total_quantity
            position.adjusted_units = money(position.adjusted_units - removed_units)
            position.last_adjusted_price = adjusted_open
    return gross_cash, net_cash, total_cost


def affordable_quantity(
    *,
    board: str,
    quantity: int,
    raw_open: Decimal,
    net_cash: Decimal,
    costs: dict[str, Decimal],
) -> int:
    step = 1 if board == "star" else 100
    minimum = 200 if board == "star" else 100

    def is_affordable(candidate: int) -> bool:
        children = split_child_orders(board, candidate)
        notional = money(Decimal(candidate) * raw_open)
        total_cost = sum(
            (
                transaction_cost(money(Decimal(child) * raw_open), "buy", costs)
                for child in children
            ),
            Decimal(0),
        )
        return notional + total_cost <= net_cash

    if quantity < minimum:
        return 0
    low_units = 0
    high_units = (quantity - minimum) // step + 1
    while low_units < high_units:
        middle = (low_units + high_units + 1) // 2
        candidate = minimum + (middle - 1) * step
        if is_affordable(candidate):
            low_units = middle
        else:
            high_units = middle - 1
    return minimum + (low_units - 1) * step if low_units else 0


def equal_weight_benchmark_return(
    signal_session: str,
    entry_session: str,
    exit_session: str,
    universes: dict[str, tuple[str, ...]],
    prices: dict[tuple[str, str], ExecutionPrice],
    states: dict[tuple[str, str], str],
    instruments: dict[str, InstrumentProfile],
) -> Decimal:
    returns: list[Decimal] = []
    for instrument_id in universes.get(signal_session, []):
        entry = prices.get((entry_session, instrument_id))
        exit_price = prices.get((exit_session, instrument_id))
        if entry is not None:
            entry_open = Decimal(entry.adjusted_open)
        elif states.get((entry_session, instrument_id)) == "full_session_suspension":
            prior = latest_adjusted_open_before(
                entry_session,
                instrument_id,
                prices,
            )
            if prior is None:
                raise StrategyCalculationError(
                    f"missing prior Benchmark mark for {instrument_id} on {entry_session}"
                )
            entry_open = prior
        elif states.get((entry_session, instrument_id)) == "data_unavailable":
            continue
        else:
            listed_to = instruments[instrument_id].listed_to
            if listed_to and listed_to <= entry_session:
                returns.append(Decimal(0))
                continue
            raise StrategyCalculationError(
                f"unexplained Benchmark Open for {instrument_id} on {entry_session}"
            )
        if exit_price is not None:
            returns.append(money(Decimal(exit_price.adjusted_open) / entry_open - 1))
            continue
        if states.get((exit_session, instrument_id)) == "full_session_suspension":
            returns.append(Decimal(0))
            continue
        if states.get((exit_session, instrument_id)) == "data_unavailable":
            continue
        listed_to = instruments[instrument_id].listed_to
        if listed_to and listed_to <= exit_session:
            returns.append(Decimal(-1))
            continue
        raise StrategyCalculationError(
            f"unexplained Benchmark Open for {instrument_id} on {exit_session}"
        )
    return money(sum(returns, Decimal(0)) / len(returns)) if returns else Decimal(0)


def columnar_equal_weight_benchmark_return(
    signal_session: str,
    entry_session: str,
    exit_session: str,
    universes: Mapping[str, tuple[str, ...]],
    states: Mapping[tuple[str, str], str],
    instruments: Mapping[str, InstrumentProfile],
    instrument_positions: Mapping[str, int],
    session_positions: Mapping[str, int],
    adjusted_opens: np.ndarray,
    numeric_adjusted_opens: np.ndarray,
) -> Decimal:
    entry_index = session_positions[entry_session]
    exit_index = session_positions[exit_session]
    universe = universes.get(signal_session, ())
    positions = np.fromiter(
        (instrument_positions[instrument_id] for instrument_id in universe),
        dtype=np.intp,
        count=len(universe),
    )
    entry_values = adjusted_opens[positions, entry_index]
    exit_values = adjusted_opens[positions, exit_index]
    entry_present = np.isfinite(numeric_adjusted_opens[positions, entry_index])
    exit_present = np.isfinite(numeric_adjusted_opens[positions, exit_index])
    if np.all(entry_present) and np.all(exit_present):
        returns = np.subtract(np.divide(exit_values, entry_values), Decimal(1))
        total_return = np.sum(returns, initial=Decimal(0))
        return money(total_return / len(returns)) if len(returns) else Decimal(0)
    total_return = Decimal(0)
    return_count = 0
    for instrument_id in universe:
        position = instrument_positions[instrument_id]
        entry_open = adjusted_opens[position, entry_index]
        exit_open = adjusted_opens[position, exit_index]
        if isinstance(entry_open, Decimal):
            pass
        elif states.get((entry_session, instrument_id)) == "full_session_suspension":
            prior_values = adjusted_opens[position, :entry_index]
            entry_open = next(
                (value for value in reversed(prior_values) if isinstance(value, Decimal)),
                None,
            )
            if entry_open is None:
                raise StrategyCalculationError(
                    f"missing prior Benchmark mark for {instrument_id} on {entry_session}"
                )
        elif states.get((entry_session, instrument_id)) == "data_unavailable":
            continue
        else:
            listed_to = instruments[instrument_id].listed_to
            if listed_to and listed_to <= entry_session:
                return_count += 1
                continue
            raise StrategyCalculationError(
                f"unexplained Benchmark Open for {instrument_id} on {entry_session}"
            )
        if isinstance(exit_open, Decimal):
            total_return += require_finite_decimal(exit_open / entry_open - 1)
            return_count += 1
            continue
        if states.get((exit_session, instrument_id)) == "full_session_suspension":
            return_count += 1
            continue
        if states.get((exit_session, instrument_id)) == "data_unavailable":
            continue
        listed_to = instruments[instrument_id].listed_to
        if listed_to and listed_to <= exit_session:
            total_return += Decimal(-1)
            return_count += 1
            continue
        raise StrategyCalculationError(
            f"unexplained Benchmark Open for {instrument_id} on {exit_session}"
        )
    return money(total_return / return_count) if return_count else Decimal(0)


def latest_adjusted_open_before(
    session: str,
    instrument_id: str,
    prices: dict[tuple[str, str], ExecutionPrice],
) -> Decimal | None:
    optimized = getattr(prices, "latest_adjusted_open_before", None)
    if callable(optimized):
        value = optimized(session, instrument_id)
        return None if value is None else Decimal(str(value))
    candidates = [
        (price_session, Decimal(row.adjusted_open))
        for (price_session, price_instrument), row in prices.items()
        if price_instrument == instrument_id and price_session < session
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def strategy_metrics(
    *,
    daily: list[dict[str, object]],
    turnover_events: list[dict[str, object]],
    cumulative_cost: Decimal,
    rejections: list[dict[str, object]],
) -> dict[str, object]:
    gross_nav = [Decimal(str(item["gross_nav"])) for item in daily]
    net_nav = [Decimal(str(item["net_nav"])) for item in daily]
    benchmark_nav = [Decimal(str(item["benchmark_nav"])) for item in daily]
    intervals = len(daily) - 1
    gross_cumulative = float(gross_nav[-1] / gross_nav[0] - 1)
    net_cumulative = float(net_nav[-1] / net_nav[0] - 1)
    benchmark_cumulative = float(benchmark_nav[-1] / benchmark_nav[0] - 1)
    gross_cagr = cagr(gross_nav[-1] / gross_nav[0], intervals)
    net_cagr = cagr(net_nav[-1] / net_nav[0], intervals)
    benchmark_cagr = cagr(
        benchmark_nav[-1] / benchmark_nav[0],
        intervals,
    )
    annualized_excess = cagr(
        (net_nav[-1] / net_nav[0]) / (benchmark_nav[-1] / benchmark_nav[0]),
        intervals,
    )
    net_returns = [
        float(net_nav[index] / net_nav[index - 1] - 1) for index in range(1, len(net_nav))
    ]
    volatility = stdev(net_returns) * math.sqrt(252) if len(net_returns) >= 2 else None
    return_mean = math.fsum(net_returns) / len(net_returns) if net_returns else None
    sharpe = (
        None
        if volatility in {None, 0.0} or return_mean is None
        else return_mean / (volatility / math.sqrt(252)) * math.sqrt(252)
    )
    drawdown = maximum_drawdown(daily, net_nav)
    calmar = None if drawdown["value"] in {None, 0.0} else net_cagr / abs(float(drawdown["value"]))
    turnover_values = [float(item["value"]) for item in turnover_events]
    holdings = [int(item["holdings_count"]) for item in daily]
    weights = [float(item["maximum_single_name_weight"]) for item in daily]
    cash = [float(item["cash_ratio"]) for item in daily]
    max_weight_index = max(range(len(weights)), key=weights.__getitem__)
    max_cash_index = max(range(len(cash)), key=cash.__getitem__)
    rejection_counts = Counter(str(item["reason"]) for item in rejections)
    return {
        "gross_cumulative_return": gross_cumulative,
        "net_cumulative_return": net_cumulative,
        "benchmark_cumulative_return": benchmark_cumulative,
        "gross_cagr": gross_cagr,
        "net_cagr": net_cagr,
        "benchmark_cagr": benchmark_cagr,
        "annualized_excess_return": annualized_excess,
        "maximum_drawdown": drawdown,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "risk_free_rate": 0,
        "calmar": calmar,
        "turnover": {
            "events": turnover_events,
            "average_rebalance": (
                math.fsum(turnover_values) / len(turnover_values) if turnover_values else None
            ),
            "annualized": (math.fsum(turnover_values) * 252 / intervals if intervals else None),
        },
        "transaction_costs": {
            "cumulative_amount": float(cumulative_cost),
            "ratio": float(cumulative_cost / INITIAL_CASH),
            "return_drag": gross_cumulative - net_cumulative,
        },
        "holdings_count": {
            "daily": holdings,
            "mean": math.fsum(holdings) / len(holdings),
            "minimum": min(holdings),
            "maximum": max(holdings),
            "ending": holdings[-1],
        },
        "maximum_single_name_weight": {
            "daily": weights,
            "period_maximum": {
                "value": weights[max_weight_index],
                "session": daily[max_weight_index]["session"],
            },
            "ending": weights[-1],
        },
        "cash_ratio": {
            "daily": cash,
            "mean": math.fsum(cash) / len(cash),
            "maximum": {
                "value": cash[max_cash_index],
                "session": daily[max_cash_index]["session"],
            },
            "ending": cash[-1],
        },
        "market_rejections": {
            "upper_limit_buy": rejection_counts["upper_limit_buy"],
            "lower_limit_sell": rejection_counts["lower_limit_sell"],
            "suspension": rejection_counts["suspension"],
        },
    }


def _fraction_from_state(
    state: dict[str, object],
    name: str,
) -> Fraction:
    return Fraction(
        int(state.get(f"{name}_numerator", 0)),
        int(state.get(f"{name}_denominator", 1)),
    )


def _store_fraction(
    state: dict[str, object],
    name: str,
    value: Fraction,
) -> None:
    state[f"{name}_numerator"] = value.numerator
    state[f"{name}_denominator"] = value.denominator


def _add_binary64(
    state: dict[str, object],
    name: str,
    value: float,
) -> None:
    _store_fraction(
        state,
        name,
        _fraction_from_state(state, name) + Fraction.from_float(value),
    )


def _sample_stdev_from_exact_moments(
    count: int,
    total: Fraction,
    squared_total: Fraction,
) -> float:
    if count < 2:
        raise StrategyCalculationError("sample standard deviation requires two observations")
    squared_deviations = (count * squared_total - total * total) / count
    variance = squared_deviations / (count - 1)
    numerator = variance.numerator
    denominator = variance.denominator
    bit_shift = (numerator.bit_length() - denominator.bit_length() - 109) // 2
    if bit_shift >= 0:
        root = (
            _integer_sqrt_fraction_round_to_odd(
                numerator,
                denominator << 2 * bit_shift,
            )
            << bit_shift
        )
        divisor = 1
    else:
        root = _integer_sqrt_fraction_round_to_odd(
            numerator << -2 * bit_shift,
            denominator,
        )
        divisor = 1 << -bit_shift
    return root / divisor


def _integer_sqrt_fraction_round_to_odd(
    numerator: int,
    denominator: int,
) -> int:
    root = math.isqrt(numerator // denominator)
    return root | (root * root * denominator != numerator)


def advance_strategy_metric_state(
    prior_state: dict[str, object] | None,
    *,
    daily: list[dict[str, object]],
    turnover_events: list[dict[str, object]],
    cumulative_cost: Decimal,
    rejections: list[dict[str, object]],
) -> dict[str, object]:
    state = dict(prior_state or {})
    rejection_counts = {
        "upper_limit_buy": int(state.get("upper_limit_buy_rejections", 0)),
        "lower_limit_sell": int(state.get("lower_limit_sell_rejections", 0)),
        "suspension": int(state.get("suspension_rejections", 0)),
    }
    for rejection in rejections:
        reason = str(rejection["reason"])
        if reason in rejection_counts:
            rejection_counts[reason] += 1

    for row in daily:
        session = str(row["session"])
        gross_nav = Decimal(str(row["gross_nav"]))
        net_nav = Decimal(str(row["net_nav"]))
        benchmark_nav = Decimal(str(row["benchmark_nav"]))
        holdings = int(row["holdings_count"])
        weight = float(row["maximum_single_name_weight"])
        cash = float(row["cash_ratio"])
        session_count = int(state.get("session_count", 0))
        if session_count == 0:
            state.update(
                {
                    "contract": "strategy-metric-state-v1",
                    "first_gross_nav": str(gross_nav),
                    "first_net_nav": str(net_nav),
                    "first_benchmark_nav": str(benchmark_nav),
                    "return_count": 0,
                    "peak_net_nav": str(net_nav),
                    "peak_session": session,
                    "worst_drawdown": "0",
                    "worst_peak_nav": str(net_nav),
                    "worst_peak_session": session,
                    "worst_trough_session": session,
                    "worst_recovery_session": None,
                    "holdings_sum": 0,
                    "holdings_minimum": holdings,
                    "holdings_maximum": holdings,
                    "weight_maximum": weight,
                    "weight_maximum_session": session,
                    "cash_maximum": cash,
                    "cash_maximum_session": session,
                    "turnover_count": int(state.get("turnover_count", 0)),
                }
            )
        else:
            prior_net_nav = Decimal(str(state["last_net_nav"]))
            net_return = float(net_nav / prior_net_nav - 1)
            return_count = int(state["return_count"]) + 1
            state["return_count"] = return_count
            _add_binary64(state, "return_sum", net_return)
            _store_fraction(
                state,
                "return_square_sum",
                _fraction_from_state(
                    state,
                    "return_square_sum",
                )
                + Fraction.from_float(net_return) ** 2,
            )

            worst_drawdown = Decimal(str(state["worst_drawdown"]))
            if (
                worst_drawdown > 0
                and state.get("worst_recovery_session") is None
                and net_nav >= Decimal(str(state["worst_peak_nav"]))
            ):
                state["worst_recovery_session"] = session
            peak_nav = Decimal(str(state["peak_net_nav"]))
            if net_nav > peak_nav:
                peak_nav = net_nav
                state["peak_net_nav"] = str(net_nav)
                state["peak_session"] = session
            drawdown = Decimal(1) - net_nav / peak_nav
            if drawdown > worst_drawdown:
                state["worst_drawdown"] = str(drawdown)
                state["worst_peak_nav"] = str(peak_nav)
                state["worst_peak_session"] = state["peak_session"]
                state["worst_trough_session"] = session
                state["worst_recovery_session"] = None
            state["holdings_minimum"] = min(
                int(state["holdings_minimum"]),
                holdings,
            )
            state["holdings_maximum"] = max(
                int(state["holdings_maximum"]),
                holdings,
            )
            if weight > float(state["weight_maximum"]):
                state["weight_maximum"] = weight
                state["weight_maximum_session"] = session
            if cash > float(state["cash_maximum"]):
                state["cash_maximum"] = cash
                state["cash_maximum_session"] = session

        state["session_count"] = session_count + 1
        state["last_gross_nav"] = str(gross_nav)
        state["last_net_nav"] = str(net_nav)
        state["last_benchmark_nav"] = str(benchmark_nav)
        state["last_session"] = session
        state["holdings_sum"] = int(state["holdings_sum"]) + holdings
        state["holdings_ending"] = holdings
        state["weight_ending"] = weight
        _add_binary64(state, "cash_sum", cash)
        state["cash_ending"] = cash

    for item in turnover_events:
        _add_binary64(
            state,
            "turnover_sum",
            float(item["value"]),
        )
    state["turnover_count"] = int(state.get("turnover_count", 0)) + len(turnover_events)
    state["cumulative_cost"] = str(cumulative_cost)
    state["upper_limit_buy_rejections"] = rejection_counts["upper_limit_buy"]
    state["lower_limit_sell_rejections"] = rejection_counts["lower_limit_sell"]
    state["suspension_rejections"] = rejection_counts["suspension"]
    if int(state.get("session_count", 0)) == 0:
        raise StrategyCalculationError("Strategy metric state has no observations")
    return state


def strategy_metrics_from_state(
    state: dict[str, object],
) -> dict[str, object]:
    intervals = int(state["session_count"]) - 1
    first_gross_nav = Decimal(str(state["first_gross_nav"]))
    first_net_nav = Decimal(str(state["first_net_nav"]))
    first_benchmark_nav = Decimal(str(state["first_benchmark_nav"]))
    last_gross_nav = Decimal(str(state["last_gross_nav"]))
    last_net_nav = Decimal(str(state["last_net_nav"]))
    last_benchmark_nav = Decimal(str(state["last_benchmark_nav"]))
    gross_cumulative = float(last_gross_nav / first_gross_nav - 1)
    net_cumulative = float(last_net_nav / first_net_nav - 1)
    benchmark_cumulative = float(last_benchmark_nav / first_benchmark_nav - 1)
    gross_cagr = cagr(last_gross_nav / first_gross_nav, intervals)
    net_cagr = cagr(last_net_nav / first_net_nav, intervals)
    benchmark_cagr = cagr(
        last_benchmark_nav / first_benchmark_nav,
        intervals,
    )
    annualized_excess = cagr(
        (last_net_nav / first_net_nav) / (last_benchmark_nav / first_benchmark_nav),
        intervals,
    )
    return_count = int(state["return_count"])
    return_sum = _fraction_from_state(state, "return_sum")
    return_square_sum = _fraction_from_state(
        state,
        "return_square_sum",
    )
    volatility = (
        _sample_stdev_from_exact_moments(
            return_count,
            return_sum,
            return_square_sum,
        )
        * math.sqrt(252)
        if return_count >= 2
        else None
    )
    return_mean = float(return_sum) / return_count if return_count else None
    sharpe = (
        None
        if volatility in {None, 0.0} or return_mean is None
        else return_mean / (volatility / math.sqrt(252)) * math.sqrt(252)
    )
    drawdown_value = float(state["worst_drawdown"])
    drawdown = {
        "value": drawdown_value,
        "peak_session": state["worst_peak_session"],
        "trough_session": state["worst_trough_session"],
        "recovery_session": state["worst_recovery_session"],
        "unrecovered": (state["worst_recovery_session"] is None and drawdown_value > 0),
        "series": [],
    }
    calmar = None if drawdown_value == 0.0 or net_cagr is None else net_cagr / abs(drawdown_value)
    turnover_sum = float(_fraction_from_state(state, "turnover_sum"))
    turnover_count = int(state["turnover_count"])
    cumulative_cost = Decimal(str(state["cumulative_cost"]))
    session_count = int(state["session_count"])
    return {
        "gross_cumulative_return": gross_cumulative,
        "net_cumulative_return": net_cumulative,
        "benchmark_cumulative_return": benchmark_cumulative,
        "gross_cagr": gross_cagr,
        "net_cagr": net_cagr,
        "benchmark_cagr": benchmark_cagr,
        "annualized_excess_return": annualized_excess,
        "maximum_drawdown": drawdown,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "risk_free_rate": 0,
        "calmar": calmar,
        "turnover": {
            "events": [],
            "average_rebalance": (turnover_sum / turnover_count if turnover_count else None),
            "annualized": (turnover_sum * 252 / intervals if intervals else None),
        },
        "transaction_costs": {
            "cumulative_amount": float(cumulative_cost),
            "ratio": float(cumulative_cost / INITIAL_CASH),
            "return_drag": gross_cumulative - net_cumulative,
        },
        "holdings_count": {
            "daily": [],
            "mean": int(state["holdings_sum"]) / session_count,
            "minimum": int(state["holdings_minimum"]),
            "maximum": int(state["holdings_maximum"]),
            "ending": int(state["holdings_ending"]),
        },
        "maximum_single_name_weight": {
            "daily": [],
            "period_maximum": {
                "value": float(state["weight_maximum"]),
                "session": state["weight_maximum_session"],
            },
            "ending": float(state["weight_ending"]),
        },
        "cash_ratio": {
            "daily": [],
            "mean": (float(_fraction_from_state(state, "cash_sum")) / session_count),
            "maximum": {
                "value": float(state["cash_maximum"]),
                "session": state["cash_maximum_session"],
            },
            "ending": float(state["cash_ending"]),
        },
        "market_rejections": {
            "upper_limit_buy": int(state["upper_limit_buy_rejections"]),
            "lower_limit_sell": int(state["lower_limit_sell_rejections"]),
            "suspension": int(state["suspension_rejections"]),
        },
    }


def maximum_drawdown(daily: list[dict[str, object]], net_nav: list[Decimal]) -> dict[str, object]:
    peak_index = 0
    worst_value = Decimal(0)
    worst_peak = 0
    worst_trough = 0
    for index, value in enumerate(net_nav):
        if value > net_nav[peak_index]:
            peak_index = index
        drawdown = Decimal(1) - value / net_nav[peak_index]
        if drawdown > worst_value:
            worst_value = drawdown
            worst_peak = peak_index
            worst_trough = index
    recovery = next(
        (
            index
            for index in range(worst_trough + 1, len(net_nav))
            if net_nav[index] >= net_nav[worst_peak]
        ),
        None,
    )
    return {
        "value": float(worst_value),
        "peak_session": daily[worst_peak]["session"],
        "trough_session": daily[worst_trough]["session"],
        "recovery_session": daily[recovery]["session"] if recovery is not None else None,
        "unrecovered": recovery is None and worst_value > 0,
        "series": [
            {
                "session": item["session"],
                "drawdown": float(Decimal(1) - value / max(net_nav[: index + 1])),
            }
            for index, (item, value) in enumerate(zip(daily, net_nav, strict=True))
        ],
    }


def cagr(wealth: Decimal, intervals: int) -> float | None:
    if intervals <= 0 or wealth <= 0:
        return None
    return float(wealth) ** (252 / intervals) - 1


def account_weights(
    cash: Decimal,
    nav: Decimal,
    positions: dict[str, Position],
    marks: dict[str, Decimal],
) -> dict[str, float]:
    if nav == 0:
        return {}
    weights = {"cash": float(cash / nav)}
    weights.update(
        {
            instrument_id: float(position.adjusted_units * marks[instrument_id] / nav)
            for instrument_id, position in positions.items()
        }
    )
    return weights


def weight_turnover(before: dict[str, float], after: dict[str, float]) -> float:
    assets = set(before) | set(after)
    return 0.5 * math.fsum(abs(after.get(asset, 0.0) - before.get(asset, 0.0)) for asset in assets)


def unique_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    result: list[dict[str, object]] = []
    for event in events:
        identity = (
            event.get("session"),
            event.get("instrument_id"),
            event.get("type"),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(event)
    return result


def sum_position_values(positions: dict[str, Position], marks: dict[str, Decimal]) -> Decimal:
    return money(
        sum(
            (
                position.adjusted_units * marks[instrument_id]
                for instrument_id, position in positions.items()
            ),
            Decimal(0),
        )
    )


def money(value: Decimal) -> Decimal:
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            result = +value
    except DecimalException as error:
        raise StrategyCalculationError("invalid accounting result") from error
    return require_finite_decimal(result)


def accounting_context():
    return localcontext(ACCOUNTING_CONTEXT)
