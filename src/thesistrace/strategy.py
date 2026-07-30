import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from statistics import stdev

from thesistrace.numeric import (
    ACCOUNTING_CONTEXT,
    canonical_decimal,
    require_finite_decimal,
)
from thesistrace.objects import canonical_json_bytes

INITIAL_CASH = Decimal("10000000")


class StrategyCalculationError(RuntimeError):
    pass


@dataclass
class Position:
    execution_shares: int
    adjusted_units: Decimal
    last_adjusted_price: Decimal


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


def split_child_orders(board: str, quantity: int) -> list[int]:
    caps = {"main": 1_000_000, "chinext": 300_000, "star": 100_000}
    minimums = {"main": 100, "chinext": 100, "star": 200}
    if board not in caps:
        raise StrategyCalculationError(f"unsupported board: {board}")
    cap = caps[board]
    minimum = minimums[board]
    children: list[int] = []
    remaining = quantity
    while remaining > cap:
        children.append(cap)
        remaining -= cap
    if remaining:
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
    if raw_open is None:
        return None
    if side == "buy" and raw_open >= upper:
        return "upper_limit_buy"
    if side == "sell" and raw_open <= lower:
        return "lower_limit_sell"
    return None


def run_strategy(
    canonical: dict[str, object],
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
) -> dict[str, object]:
    calendar = [str(value) for value in canonical["research_calendar"]]
    report_start = len(calendar) - 504
    report_calendar = calendar[report_start:]
    if len(report_calendar) != 504:
        raise StrategyCalculationError("Strategy requires 504 report sessions")
    strategy = definition["strategy"]
    holdings_count = int(strategy["holdings_count"])
    rebalance_interval = int(strategy["rebalance_interval"])
    if not 1 <= holdings_count <= 100 or not 1 <= rebalance_interval <= 20:
        raise StrategyCalculationError("invalid Strategy breadth or schedule")
    if Decimal(str(strategy["initial_cash_cny"])) != INITIAL_CASH:
        raise StrategyCalculationError("invalid Initial Cash")
    costs = {name: Decimal(str(value)) for name, value in definition["costs"].items()}

    instruments = {str(item["instrument_id"]): item for item in canonical["instruments"]}
    prices = {
        (str(item["session"]), str(item["instrument_id"])): item for item in canonical["prices"]
    }
    states = {
        (str(item["session"]), str(item["instrument_id"])): str(item["state"])
        for item in canonical["trading_states"]
    }
    limits = {
        (str(item["session"]), str(item["instrument_id"])): item
        for item in canonical["price_limits"]
    }
    alpha_by_session = {str(item["session"]): item["values"] for item in alpha_matrix["sessions"]}
    universes = {
        str(item["session"]): [str(value) for value in item["instrument_ids"]]
        for item in canonical["liquidity_universes"][str(definition["universe"])]
    }

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

    for report_index, session in enumerate(report_calendar):
        global_index = report_start + report_index
        marks, valuation_events = mark_positions(session, positions, prices, states, instruments)
        pre_gross_nav = money(gross_cash + sum_position_values(positions, marks))
        pre_net_nav = money(net_cash + sum_position_values(positions, marks))
        pre_weights = account_weights(net_cash, pre_net_nav, positions, marks)
        cycle_type = "terminal_valuation" if report_index == len(report_calendar) - 1 else "open"
        rebalance = False
        benchmark_return = Decimal(0)
        event_side_order: list[str] = []
        event_fill_start = len(fills)

        signal_index = global_index - 1
        if (
            report_index > 0
            and global_index < len(calendar) - 1
            and (signal_index - report_start) % rebalance_interval == 0
        ):
            rebalance = True
            signal_session = calendar[signal_index]
            ranked = sorted(
                alpha_by_session[signal_session],
                key=lambda item: (-Decimal(str(item["value"])), str(item["instrument_id"])),
            )
            candidates = [str(item["instrument_id"]) for item in ranked[:holdings_count]]
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
                    str(instruments[instrument_id]["board"]),
                    "sell",
                    unrounded,
                    complete_liquidation=complete,
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
                    state = states.get((session, instrument_id))
                    listed_to = str(instruments[instrument_id].get("listed_to", ""))
                    if state == "full_session_suspension":
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
                                "reason": "suspension",
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
                    raw_open = Decimal(str(price["open_raw"]))
                    unrounded = int(deficit / raw_open) if deficit > 0 else 0
                    legal_quantity = (
                        legal_order_quantity(
                            str(instruments[instrument_id]["board"]),
                            "buy",
                            unrounded,
                            complete_liquidation=False,
                        )
                        if raw_open > 0
                        else 0
                    )
                    quantity = affordable_quantity(
                        board=str(instruments[instrument_id]["board"]),
                        quantity=legal_quantity,
                        raw_open=raw_open,
                        net_cash=net_cash,
                        costs=costs,
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
            signal_session = report_calendar[report_index - 2]
            entry_session = report_calendar[report_index - 1]
            benchmark_return = equal_weight_benchmark_return(
                signal_session,
                entry_session,
                session,
                universes,
                prices,
                states,
                instruments,
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

    metrics = strategy_metrics(
        daily=daily,
        turnover_events=turnover_events,
        cumulative_cost=cumulative_cost,
        rejections=rejections,
    )
    positions_payload = [
        {
            "instrument_id": instrument_id,
            "execution_shares": position.execution_shares,
            "adjusted_units": canonical_decimal(position.adjusted_units),
        }
        for instrument_id, position in sorted(positions.items())
    ]
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
    return {
        **payload,
        "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def mark_positions(
    session: str,
    positions: dict[str, Position],
    prices: dict[tuple[str, str], dict[str, object]],
    states: dict[tuple[str, str], str],
    instruments: dict[str, dict[str, object]],
) -> tuple[dict[str, Decimal], list[dict[str, object]]]:
    marks: dict[str, Decimal] = {}
    events: list[dict[str, object]] = []
    for instrument_id in list(positions):
        price = prices.get((session, instrument_id))
        if price is not None:
            mark = Decimal(str(price["open_adj"]))
            positions[instrument_id].last_adjusted_price = mark
            marks[instrument_id] = mark
            continue
        if states.get((session, instrument_id)) == "full_session_suspension":
            marks[instrument_id] = positions[instrument_id].last_adjusted_price
            events.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "type": "valuation_carry",
                }
            )
            continue
        listed_to = str(instruments[instrument_id].get("listed_to", ""))
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
    prices: dict[tuple[str, str], dict[str, object]],
    states: dict[tuple[str, str], str],
    limits: dict[tuple[str, str], dict[str, object]],
    instruments: dict[str, dict[str, object]],
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
    raw_open = Decimal(str(price["open_raw"])) if price is not None else None
    if limit is None and state != "full_session_suspension":
        raise StrategyCalculationError(f"missing price limit for {instrument_id} on {session}")
    upper = Decimal(str(limit["upper"])) if limit is not None else Decimal(0)
    lower = Decimal(str(limit["lower"])) if limit is not None else Decimal(0)
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
    adjusted_open = Decimal(str(price["open_adj"]))
    board = str(instruments[instrument_id]["board"])
    total_cost = Decimal(0)
    total_quantity = 0
    for child_quantity in split_child_orders(board, quantity):
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
    universes: dict[str, list[str]],
    prices: dict[tuple[str, str], dict[str, object]],
    states: dict[tuple[str, str], str],
    instruments: dict[str, dict[str, object]],
) -> Decimal:
    returns: list[Decimal] = []
    for instrument_id in universes.get(signal_session, []):
        entry = prices.get((entry_session, instrument_id))
        exit_price = prices.get((exit_session, instrument_id))
        if entry is not None:
            entry_open = Decimal(str(entry["open_adj"]))
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
        else:
            listed_to = str(instruments[instrument_id].get("listed_to", ""))
            if listed_to and listed_to <= entry_session:
                returns.append(Decimal(0))
                continue
            raise StrategyCalculationError(
                f"unexplained Benchmark Open for {instrument_id} on {entry_session}"
            )
        if exit_price is not None:
            returns.append(money(Decimal(str(exit_price["open_adj"])) / entry_open - 1))
            continue
        if states.get((exit_session, instrument_id)) == "full_session_suspension":
            returns.append(Decimal(0))
            continue
        listed_to = str(instruments[instrument_id].get("listed_to", ""))
        if listed_to and listed_to <= exit_session:
            returns.append(Decimal(-1))
            continue
        raise StrategyCalculationError(
            f"unexplained Benchmark Open for {instrument_id} on {exit_session}"
        )
    return money(sum(returns, Decimal(0)) / len(returns)) if returns else Decimal(0)


def latest_adjusted_open_before(
    session: str,
    instrument_id: str,
    prices: dict[tuple[str, str], dict[str, object]],
) -> Decimal | None:
    candidates = [
        (price_session, Decimal(str(row["open_adj"])))
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
    benchmark_cagr = cagr(benchmark_nav[-1] / benchmark_nav[0], intervals)
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
