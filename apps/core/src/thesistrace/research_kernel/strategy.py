import hashlib
import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from fractions import Fraction
from statistics import stdev

from thesistrace.research_kernel.builtin_framework import (
    BUILTIN_FRAMEWORK_MODULES,
    BuiltinFramework,
    BuiltinFrameworkState,
)
from thesistrace.research_kernel.common_inputs import CLOSE_FIELD_ID
from thesistrace.research_kernel.exposure import evaluate_exposure_series, require_exposure_value
from thesistrace.research_kernel.numeric import (
    ACCOUNTING_CONTEXT,
    MAX_INITIAL_CASH_CNY,
    canonical_decimal,
    require_finite_decimal,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.series_plan import CommonInputObserver
from thesistrace.research_kernel.terminal_state_schema import PendingTarget, TargetSelection
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    ExecutionPrice,
    InstrumentProfile,
    PriceLimit,
)


def strategy_event_id(kind: str, *identity: object) -> str:
    """Logical identity within a source Strategy execution, independent of chunking."""
    return f"{kind}_" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


class StrategyCalculationError(RuntimeError):
    pass


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


@dataclass(frozen=True)
class _StrategyExecution:
    payload: dict[str, object]
    prior_metric_state: dict[str, object] | None
    prior_daily_count: int
    turnover_events: tuple[dict[str, object], ...]
    cumulative_cost: Decimal


def transition_strategy(
    research_data: AlignedResearchData,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str,
    continuation: dict[str, object] | None = None,
    observe_common: CommonInputObserver | None = None,
    observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> StrategyTransition:
    """Execute every included Open and retain the completed account boundary."""
    return _transition_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        observe_common=observe_common,
        observe_holdings=observe_holdings,
    )


def transition_columnar_strategy(
    research_data: ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str,
    continuation: dict[str, object] | None = None,
    cancellation_check: Callable[[], None],
    observe_common: CommonInputObserver | None = None,
    observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> StrategyTransition:
    return _transition_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        observe_common=observe_common,
        observe_holdings=observe_holdings,
        cancellation_check=cancellation_check,
    )


def _transition_strategy(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str,
    continuation: dict[str, object] | None,
    cancellation_check: Callable[[], None] | None = None,
    observe_common: CommonInputObserver | None = None,
    observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> StrategyTransition:
    ledger: list[dict[str, object]] = []
    finalized = run_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        observe_common=observe_common,
        observe_holdings=observe_holdings,
        ledger=ledger,
        cancellation_check=cancellation_check,
    )
    return StrategyTransition(
        finalized=finalized,
        resumable=finalized,
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
    continuation: dict[str, object] | None = None,
    ledger: list[dict[str, object]] | None = None,
    cancellation_check: Callable[[], None] | None = None,
    observe_common: CommonInputObserver | None = None,
    observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    execution = _execute_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        observe_common=observe_common,
        observe_holdings=observe_holdings,
        ledger=ledger,
        cancellation_check=cancellation_check,
    )
    return (
        _strategy_continuation_result(execution)
        if continuation is not None
        and isinstance(continuation.get("metric_state"), Mapping)
        else _strategy_publication_result(execution)
    )


def run_strategy_with_metric_state(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str | None = None,
    continuation: dict[str, object] | None = None,
    ledger: list[dict[str, object]] | None = None,
    cancellation_check: Callable[[], None] | None = None,
    observe_common: CommonInputObserver | None = None,
    observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    execution = _execute_strategy(
        research_data,
        alpha_matrix,
        definition,
        origin_session=origin_session,
        continuation=continuation,
        observe_common=observe_common,
        observe_holdings=observe_holdings,
        ledger=ledger,
        cancellation_check=cancellation_check,
    )
    return _strategy_continuation_result(execution)


def _execute_strategy(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    alpha_matrix: dict[str, object],
    definition: dict[str, object],
    *,
    origin_session: str | None = None,
    continuation: dict[str, object] | None = None,
    ledger: list[dict[str, object]] | None = None,
    cancellation_check: Callable[[], None] | None = None,
    observe_common: CommonInputObserver | None = None,
    observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> _StrategyExecution:
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
    if strategy["mode"] != "framework" or strategy["modules"] != BUILTIN_FRAMEWORK_MODULES:
        raise StrategyCalculationError("Unsupported Strategy implementation")
    close_histories = None
    if strategy["weighting"] == "inverse_volatility":
        instruments = tuple(sorted(research_data.instruments))
        if isinstance(research_data, ColumnarResearchSeries):
            matrix = research_data.numeric_field_matrices(
                (CLOSE_FIELD_ID,), instruments,
            )[CLOSE_FIELD_ID]
            close_histories = dict(zip(instruments, matrix, strict=True))
        else:
            close_field = research_data.fields[CLOSE_FIELD_ID]
            close_histories = {
                item: [close_field.get((session, item)) for session in calendar]
                for item in instruments
            }
    exposure_values = evaluate_exposure_series(
        research_data, strategy["exposure_expression"], observe_common=observe_common,
    )
    exposure = None if continuation is None else require_exposure_value(
        continuation["target_exposure"], str(continuation["daily"][-1]["session"]),
    )
    initial_cash = Decimal(str(strategy["initial_cash_cny"]))
    if (
        not initial_cash.is_finite() or initial_cash <= 0
        or initial_cash > MAX_INITIAL_CASH_CNY or initial_cash.as_tuple().exponent < -2
    ):
        raise StrategyCalculationError("invalid Initial Cash")
    if continuation is not None:
        metric_state = continuation.get("metric_state")
        prior_initial_cash = (
            metric_state["initial_cash_cny"]
            if isinstance(metric_state, Mapping)
            else continuation["initial_cash_cny"]
        )
        if Decimal(str(prior_initial_cash)) != initial_cash:
            raise StrategyCalculationError(
                "continuation Initial Cash differs from account baseline"
            )
    costs = {name: Decimal(str(value)) for name, value in definition["costs"].items()}

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
    contract_checksum = hashlib.sha256(canonical_json_bytes(definition)).hexdigest()
    framework = BuiltinFramework(
        holdings_count=int(strategy["holdings_count"]),
        selection_interval=int(strategy["selection_interval"]),
        weighting=strategy["weighting"],
        volatility_window=int(strategy["volatility_window"]),
        contract_checksum=contract_checksum,
    )
    target_selection = None if continuation is None else continuation["target_selection"]
    if target_selection is not None:
        target_selection = TargetSelection.model_validate(target_selection).model_dump(mode="json")
        if target_selection["contract_checksum"] != contract_checksum:
            raise StrategyCalculationError("Retained Selection differs from Strategy contract")
    framework_state = (
        BuiltinFrameworkState(TargetSelection.model_validate(target_selection), exposure)
        if target_selection is not None else None
    )
    pending_target = None if continuation is None else continuation["pending_target"]
    if pending_target is not None:
        pending_target = PendingTarget.model_validate(pending_target).model_dump(mode="json")
        if pending_target["contract_checksum"] != contract_checksum:
            raise StrategyCalculationError("Pending decision differs from Strategy contract")
    if continuation is None:
        positions: dict[str, Position] = {}
        gross_cash = initial_cash
        net_cash = initial_cash
        cumulative_cost = Decimal(0)
        daily: list[dict[str, object]] = []
        fills: list[dict[str, object]] = []
        orders: list[dict[str, object]] = []
        child_orders: list[dict[str, object]] = []
        rejections: list[dict[str, object]] = []
        diagnostics: list[dict[str, object]] = []
        rebalance_events: list[dict[str, object]] = []
        turnover_events: list[dict[str, object]] = []
        prior_turnover_events: list[dict[str, object]] = []
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
        fills = [dict(item) for item in continuation.get("fills", [])]
        orders = [dict(item) for item in continuation.get("orders", [])]
        child_orders = [dict(item) for item in continuation.get("child_orders", [])]
        rejections = [dict(item) for item in continuation.get("rejections", [])]
        diagnostics = [dict(item) for item in continuation.get("diagnostics", [])]
        rebalance_events = [dict(item) for item in continuation.get("rebalance_events", [])]
        prior_metrics = continuation.get("metrics", {})
        prior_turnover = (
            prior_metrics.get("turnover", {})
            if isinstance(prior_metrics, Mapping)
            else {}
        )
        prior_turnover_values = (
            prior_turnover.get("events", [])
            if isinstance(prior_turnover, Mapping)
            else []
        )
        if not isinstance(prior_turnover_values, list) or any(
            not isinstance(item, Mapping) for item in prior_turnover_values
        ):
            raise StrategyCalculationError("continuation turnover history is invalid")
        prior_turnover_events = [dict(item) for item in prior_turnover_values]
        metric_state = continuation.get("metric_state")
        if metric_state is None:
            prior_metric_state = None
            turnover_events = list(prior_turnover_events)
        elif isinstance(metric_state, Mapping):
            prior_metric_state = dict(metric_state)
            turnover_events = []
        else:
            raise StrategyCalculationError("continuation metric state is invalid")

    execution_constraints = ([] if continuation is None else [
        dict(item) for item in continuation.get("execution_constraints", [])
    ])
    target_events = ([] if continuation is None else [
        dict(item) for item in continuation.get("target_events", [])
    ])
    for session in report_calendar:
        if cancellation_check is not None:
            cancellation_check()
        if pending_target is not None:
            decision = PendingTarget.model_validate(pending_target)
            if not decision.instrument_ids <= instruments.keys():
                raise StrategyCalculationError("Pending decision contains unknown instruments")
            if any(
                item not in positions or maximum > positions[item].execution_shares
                for item, maximum in decision.position_limits.items()
            ):
                raise StrategyCalculationError("Local target must reduce an actual holding")
        global_index = calendar.index(session)
        report_index = global_index - origin_index
        marks, valuation_events = mark_positions(session, positions, prices, states, instruments)
        pre_gross_nav = money(gross_cash + sum_position_values(positions, marks))
        pre_net_nav = money(net_cash + sum_position_values(positions, marks))
        pre_weights = account_weights(net_cash, pre_net_nav, positions, marks)
        cycle_type = "open"
        rebalance = False
        event_side_order: list[str] = []
        event_intended_orders: list[dict[str, object]] = []
        event_order_start = len(orders)
        event_fill_start = len(fills)
        event_rejection_start = len(rejections)
        event_diagnostic_start = len(diagnostics)
        event_cost_start = cumulative_cost
        execution_signal: dict[str, object] | None = None

        signal_index = global_index - 1
        if pending_target is not None:
            if report_index <= 0:
                raise StrategyCalculationError("Initial baseline cannot execute a prior target")
            rebalance = True
            signal_session = calendar[signal_index]
            if pending_target["decision_session"] != signal_session:
                raise StrategyCalculationError("Open target is not from the preceding Close")
            allocation = pending_target["allocation"]
            mode = allocation["mode"] if allocation is not None else "local"
            reason = pending_target["reason"]
            target_id = strategy_event_id("target", contract_checksum, signal_session)
            candidates = list(allocation["instrument_ids"]) if allocation is not None else []
            if ledger is not None:
                execution_signal = {
                    "session": signal_session,
                    "selected_instrument_ids": candidates,
                }
            if allocation is not None and not candidates:
                diagnostics.append(
                    {
                        "session": session,
                        "reason": "insufficient_candidates",
                        "available": 0,
                    }
                )
            target_capital = (
                money(pre_net_nav * Decimal(str(allocation["exposure"])))
                if allocation is not None else Decimal(0)
            )
            target_values = {}
            for instrument_id in candidates:
                ratio = Fraction(allocation["relative_weights"][instrument_id])
                target_values[instrument_id] = money(
                    target_capital * ratio.numerator / ratio.denominator
                )
            actual_stock_value = sum_position_values(positions, marks)
            if mode == "reduce":
                ratio = (min(Decimal(1), target_capital / actual_stock_value)
                         if actual_stock_value else Decimal(0))
                target_values = {
                    item: money(position.adjusted_units * marks[item] * ratio)
                    for item, position in positions.items()
                }
            if mode in {"local", "increase"}:
                for item, position in positions.items():
                    target_values.setdefault(item, money(position.adjusted_units * marks[item]))
            position_limits = pending_target["position_limits"]
            for item, maximum in position_limits.items():
                # Delisting can remove a holding during the Open mark above.
                if item in positions:
                    position = positions[item]
                    capped_value = money(
                        position.adjusted_units * marks[item] * maximum / position.execution_shares
                    )
                    target_values[item] = min(target_values.get(item, Decimal(0)), capped_value)
            candidate_set = set(target_values)
            alpha_order = {instrument_id: index for index, instrument_id in enumerate(candidates)}

            for instrument_id in sorted(positions):
                if mode == "increase" and instrument_id not in position_limits:
                    continue
                position = positions[instrument_id]
                current_value = money(position.adjusted_units * marks[instrument_id])
                desired_value = (
                    target_values[instrument_id] if instrument_id in candidate_set else Decimal(0)
                )
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
                if instrument_id in position_limits:
                    unrounded = max(
                        unrounded, position.execution_shares - position_limits[instrument_id],
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
                    execution_constraints.append(_execution_constraint(
                        target_id=target_id, decision_session=signal_session,
                        session=session, instrument_id=instrument_id, side="sell", mode=mode,
                        decision_reason=reason,
                        reason="below_board_lot", intended_value=current_value - desired_value,
                        unrounded_quantity=unrounded, legal_quantity=0, submitted_quantity=0,
                        available_cash=net_cash,
                    ))
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
                    target_id=target_id,
                    decision_session=signal_session,
                    reason=reason,
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
            buy_budget = max(
                Decimal(0), target_capital - sum_position_values(positions, marks),
            )
            for instrument_id in ([] if mode == "reduce" else sorted(
                candidates, key=lambda value: alpha_order[value],
            )):
                price = prices.get((session, instrument_id))
                current_value = (
                    money(positions[instrument_id].adjusted_units * marks[instrument_id])
                    if instrument_id in positions
                    else Decimal(0)
                )
                deficit = target_values[instrument_id] - current_value
                if mode == "increase":
                    deficit = min(deficit, buy_budget)
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
                        order_id = strategy_event_id(
                            "order", target_id, session, instrument_id, "buy",
                        )
                        orders.append(
                            {
                                "target_id": target_id,
                                "decision_session": signal_session,
                                "reason": reason,
                                "rejection_reason": rejection_reason,
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
                if deficit > 0 and (legal_quantity == 0 or quantity < legal_quantity):
                    execution_constraints.append(_execution_constraint(
                        target_id=target_id, decision_session=signal_session,
                        session=session, instrument_id=instrument_id, side="buy", mode=mode,
                        decision_reason=reason,
                        reason="below_board_lot" if legal_quantity == 0 else "insufficient_cash",
                        intended_value=deficit, unrounded_quantity=unrounded,
                        legal_quantity=legal_quantity, submitted_quantity=quantity,
                        available_cash=net_cash,
                    ))
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
                cash_before_buy = net_cash
                gross_cash, net_cash, cost = execute_order(
                    session=session,
                    target_id=target_id,
                    decision_session=signal_session,
                    reason=reason,
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
                if mode == "increase":
                    buy_budget = max(Decimal(0), buy_budget - (cash_before_buy - net_cash - cost))

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
                        instrument_id: float(target_values[instrument_id] / pre_net_nav)
                        for instrument_id in target_values
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
                "cumulative_transaction_cost": canonical_decimal(cumulative_cost),
                "holdings_count": holdings,
                "maximum_single_name_weight": max_weight,
                "cash_ratio": cash_ratio,
                "execution_rounding_residual": canonical_decimal(residual),
                "valuation_events": unique_events(valuation_events),
            }
        )
        if observe_holdings is not None:
            observe_holdings({
                "session": session,
                "positions": [
                    {
                        "instrument_id": instrument_id,
                        "execution_shares": position.execution_shares,
                        "adjusted_units": canonical_decimal(position.adjusted_units),
                        "adjusted_mark": canonical_decimal(marks[instrument_id]),
                        "market_value_cny": canonical_decimal(position_values[instrument_id]),
                        "weight": float(position_values[instrument_id] / net_nav)
                        if net_nav != 0 else 0.0,
                    }
                    for instrument_id, position in sorted(positions.items())
                ],
            })
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
        end_index = global_index + 1
        close_windows = {} if close_histories is None else {
            str(item["instrument_id"]): close_histories[str(item["instrument_id"])][
                max(0, end_index - framework.volatility_window - 1):end_index
            ] for item in alpha_by_session[session]
        }
        try:
            decision = framework.decide(
                session=session, report_index=report_index,
                alpha_values=alpha_by_session[session], close_windows=close_windows,
                exposure_value=exposure_values[session], previous=framework_state,
            )
        except ValueError as error:
            raise StrategyCalculationError(str(error)) from error
        framework_state = decision.state
        target_selection = framework_state.selection.model_dump(mode="json")
        exposure = framework_state.exposure
        pending_target = decision.target.model_dump(mode="json") if decision.target else None
        diagnostics.extend(decision.diagnostics)
        if pending_target is not None:
            target_events.append({
                "target_id": strategy_event_id("target", contract_checksum, session),
                **pending_target,
            })
        if cancellation_check is not None:
            cancellation_check()

    positions_payload = _position_payload(positions)
    payload = {
        "alpha_checksum": alpha_matrix["checksum"],
        "target_selection": target_selection,
        "target_exposure": exposure,
        "pending_target": pending_target,
        "initial_cash_cny": canonical_decimal(initial_cash),
        "daily": daily,
        "positions": positions_payload,
        "target_events": target_events,
        "orders": orders,
        "child_orders": child_orders,
        "fills": fills,
        "rebalance_events": rebalance_events,
        "rejections": rejections,
        "diagnostics": diagnostics,
        "execution_constraints": execution_constraints,
    }
    return _StrategyExecution(
        payload=payload,
        prior_metric_state=prior_metric_state,
        prior_daily_count=prior_daily_count,
        turnover_events=tuple(turnover_events),
        cumulative_cost=cumulative_cost,
    )


def _execution_constraint(
    *, target_id: str, decision_session: str, session: str, instrument_id: str,
    side: str, mode: str, decision_reason: str, reason: str,
    intended_value: Decimal, unrounded_quantity: int,
    legal_quantity: int, submitted_quantity: int, available_cash: Decimal,
) -> dict[str, object]:
    return {
        "constraint_id": strategy_event_id(
            "constraint", target_id, session, instrument_id, side, reason,
        ),
        "target_id": target_id, "decision_session": decision_session, "session": session,
        "instrument_id": instrument_id, "side": side, "mode": mode, "reason": reason,
        "decision_reason": decision_reason,
        "intended_value": canonical_decimal(intended_value),
        "unrounded_quantity": unrounded_quantity, "legal_quantity": legal_quantity,
        "submitted_quantity": submitted_quantity,
        "available_cash_cny": canonical_decimal(available_cash),
        "order_id": strategy_event_id("order", target_id, session, instrument_id, side)
        if submitted_quantity else None,
    }


def _strategy_publication_result(execution: _StrategyExecution) -> dict[str, object]:
    if execution.prior_metric_state is None:
        daily = execution.payload["daily"]
        rejections = execution.payload["rejections"]
        assert isinstance(daily, list)
        assert isinstance(rejections, list)
        metrics = strategy_metrics(
            initial_cash=Decimal(str(execution.payload["initial_cash_cny"])),
            daily=daily,
            turnover_events=list(execution.turnover_events),
            cumulative_cost=execution.cumulative_cost,
            rejections=rejections,
        )
    else:
        metrics = strategy_metrics_from_state(_strategy_metric_state(execution))
    payload = {**execution.payload, "metrics": metrics}
    return {
        **payload,
        "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _strategy_continuation_result(execution: _StrategyExecution) -> dict[str, object]:
    metric_state = _strategy_metric_state(execution)
    payload = {
        **execution.payload,
        "metrics": strategy_metrics_from_state(metric_state),
        "metric_state": metric_state,
    }
    return {
        **payload,
        "checksum": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _strategy_metric_state(execution: _StrategyExecution) -> dict[str, object]:
    daily = execution.payload["daily"]
    rejections = execution.payload["rejections"]
    assert isinstance(daily, list)
    assert isinstance(rejections, list)
    return advance_strategy_metric_state(
        execution.prior_metric_state,
        initial_cash=Decimal(str(execution.payload["initial_cash_cny"])),
        daily=daily[execution.prior_daily_count :],
        turnover_events=list(execution.turnover_events),
        cumulative_cost=execution.cumulative_cost,
        rejections=rejections,
    )


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
                    "adjustment_id": strategy_event_id(
                        "adjustment", session, instrument_id, "valuation_carry",
                    ),
                    "execution_shares_delta": 0,
                    "adjusted_units_delta": "0",
                    "net_cash_delta": "0",
                    "gross_cash_delta": "0",
                    "valuation_delta": "0",
                    "last_adjusted_price": canonical_decimal(
                        positions[instrument_id].last_adjusted_price,
                    ),
                }
            )
            continue
        listed_to = instruments[instrument_id].listed_to
        if listed_to and listed_to <= session:
            removed_position = positions.pop(instrument_id)
            events.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "type": "terminal_delisting_writeoff",
                    "adjustment_id": strategy_event_id(
                        "adjustment", session, instrument_id, "terminal_delisting_writeoff",
                    ),
                    "execution_shares_delta": -removed_position.execution_shares,
                    "adjusted_units_delta": canonical_decimal(
                        removed_position.adjusted_units.copy_negate(),
                    ),
                    "net_cash_delta": "0",
                    "gross_cash_delta": "0",
                    "valuation_delta": canonical_decimal(
                        -removed_position.adjusted_units * removed_position.last_adjusted_price,
                    ),
                    "last_adjusted_price": canonical_decimal(removed_position.last_adjusted_price),
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
    target_id: str,
    decision_session: str,
    reason: str,
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
    order_id = strategy_event_id("order", target_id, session, instrument_id, side)
    event_context = {
        "target_id": target_id, "decision_session": decision_session, "reason": reason,
    }
    orders.append(
        {
            **event_context,
            "rejection_reason": rejection,
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
    fill_start = len(fills)
    cash_before = gross_cash, net_cash
    position = positions.get(instrument_id)
    units_before = Decimal(0) if position is None else position.adjusted_units
    complete_liquidation = (
        side == "sell" and position is not None and position.execution_shares == quantity
    )
    for child_quantity in split_child_orders(
        board,
        quantity,
        complete_liquidation=complete_liquidation,
    ):
        child_order_id = strategy_event_id(
            "child", order_id, total_quantity, total_quantity + child_quantity,
        )
        raw_notional = money(Decimal(child_quantity) * raw_open)
        child_cost = transaction_cost(raw_notional, side, costs)
        total_cost = money(total_cost + child_cost)
        total_quantity += child_quantity
        child_orders.append(
            {
                **event_context,
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
                "fill_id": strategy_event_id("fill", child_order_id),
                **event_context,
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
    position_after = positions.get(instrument_id)
    units_after = Decimal(0) if position_after is None else position_after.adjusted_units
    # Allocate the actual order-level mutations, retaining any accounting-rounding
    # residual explicitly. Child raw notionals are not the synthetic settlement.
    with accounting_context():
        deltas = (gross_cash - cash_before[0], net_cash - cash_before[1],
                  units_after - units_before)
        prior = (Decimal(0), Decimal(0), Decimal(0))
        cumulative_net = Decimal(0)
        cumulative_quantity = 0
        for fill in fills[fill_start:]:
            cumulative_quantity += fill["quantity"]
            cumulative = (deltas if cumulative_quantity == total_quantity else tuple(
                value * cumulative_quantity / total_quantity for value in deltas
            ))
            gross_delta, _, units_delta = (
                value - before for value, before in zip(cumulative, prior, strict=True)
            )
            prior = cumulative
            net_delta = (deltas[1] - cumulative_net if cumulative_quantity == total_quantity
                         else gross_delta - Decimal(fill["cost"]))
            cumulative_net += net_delta
            fill.update({
                "adjusted_open": canonical_decimal(adjusted_open),
                "research_settlement": canonical_decimal(abs(gross_delta)),
                "gross_cash_delta": canonical_decimal(gross_delta),
                "net_cash_delta": canonical_decimal(net_delta),
                "cash_rounding_delta": canonical_decimal(
                    net_delta - gross_delta + Decimal(fill["cost"]),
                ),
                "execution_shares_delta": fill["quantity"] * (1 if side == "buy" else -1),
                "adjusted_units_delta": canonical_decimal(units_delta),
            })
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


def strategy_metrics(
    *,
    initial_cash: Decimal,
    daily: list[dict[str, object]],
    turnover_events: list[dict[str, object]],
    cumulative_cost: Decimal,
    rejections: list[dict[str, object]],
) -> dict[str, object]:
    gross_nav = [Decimal(str(item["gross_nav"])) for item in daily]
    net_nav = [Decimal(str(item["net_nav"])) for item in daily]
    entry_index = next(
        (index for index, item in enumerate(daily) if item["rebalance"] is True),
        len(daily) - 1,
    )
    investment_intervals = len(daily) - entry_index - 1
    report_intervals = len(daily) - 1
    gross_cumulative = float(gross_nav[-1] / initial_cash - 1)
    net_cumulative = float(net_nav[-1] / initial_cash - 1)
    gross_cagr = cagr(gross_nav[-1] / initial_cash, investment_intervals)
    net_cagr = cagr(net_nav[-1] / initial_cash, investment_intervals)
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
    calmar = (
        None
        if net_cagr is None or drawdown["value"] in {None, 0.0}
        else net_cagr / abs(float(drawdown["value"]))
    )
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
        "gross_cagr": gross_cagr,
        "net_cagr": net_cagr,
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
            "annualized": (
                math.fsum(turnover_values) * 252 / report_intervals
                if report_intervals
                else None
            ),
        },
        "transaction_costs": {
            "cumulative_amount": float(cumulative_cost),
            "ratio": float(cumulative_cost / initial_cash),
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
    initial_cash: Decimal,
    daily: list[dict[str, object]],
    turnover_events: list[dict[str, object]],
    cumulative_cost: Decimal,
    rejections: list[dict[str, object]],
) -> dict[str, object]:
    state = dict(prior_state or {})
    if prior_state is not None and Decimal(str(state["initial_cash_cny"])) != initial_cash:
        raise StrategyCalculationError(
                "continuation Initial Cash differs from account baseline"
            )
    state["initial_cash_cny"] = canonical_decimal(initial_cash)
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
        holdings = int(row["holdings_count"])
        weight = float(row["maximum_single_name_weight"])
        cash = float(row["cash_ratio"])
        session_count = int(state.get("session_count", 0))
        if session_count == 0:
            state.update(
                {
                    "contract": "strategy-metric-state-v2",
                    "entry_session": None,
                    "entry_session_ordinal": None,
                    "first_gross_nav": str(gross_nav),
                    "first_net_nav": str(net_nav),
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

        if row["rebalance"] is True and state.get("entry_session") is None:
            state["entry_session"] = session
            state["entry_session_ordinal"] = session_count + 1
        state["session_count"] = session_count + 1
        state["last_gross_nav"] = str(gross_nav)
        state["last_net_nav"] = str(net_nav)
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
    initial_cash = Decimal(str(state["initial_cash_cny"]))
    if not initial_cash.is_finite() or initial_cash <= 0:
        raise StrategyCalculationError("invalid Initial Cash in metric state")
    report_intervals = int(state["session_count"]) - 1
    entry_ordinal = state.get("entry_session_ordinal")
    investment_intervals = (
        report_intervals
        if entry_ordinal is None
        else int(state["session_count"]) - int(entry_ordinal)
    )
    last_gross_nav = Decimal(str(state["last_gross_nav"]))
    last_net_nav = Decimal(str(state["last_net_nav"]))
    gross_cumulative = float(last_gross_nav / initial_cash - 1)
    net_cumulative = float(last_net_nav / initial_cash - 1)
    gross_cagr = cagr(last_gross_nav / initial_cash, investment_intervals)
    net_cagr = cagr(last_net_nav / initial_cash, investment_intervals)
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
        "gross_cagr": gross_cagr,
        "net_cagr": net_cagr,
        "maximum_drawdown": drawdown,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "risk_free_rate": 0,
        "calmar": calmar,
        "turnover": {
            "events": [],
            "average_rebalance": (turnover_sum / turnover_count if turnover_count else None),
            "annualized": (
                turnover_sum * 252 / report_intervals if report_intervals else None
            ),
        },
        "transaction_costs": {
            "cumulative_amount": float(cumulative_cost),
            "ratio": float(cumulative_cost / initial_cash),
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
            if worst_value > 0 and net_nav[index] >= net_nav[worst_peak]
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
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            value = sum(
                (
                    position.adjusted_units * marks[instrument_id]
                    for instrument_id, position in sorted(positions.items())
                ),
                Decimal(0),
            )
    except DecimalException as error:
        raise StrategyCalculationError("invalid accounting result") from error
    return money(value)


def money(value: Decimal) -> Decimal:
    try:
        with localcontext(ACCOUNTING_CONTEXT):
            result = +value
    except DecimalException as error:
        raise StrategyCalculationError("invalid accounting result") from error
    return require_finite_decimal(result)


def accounting_context():
    return localcontext(ACCOUNTING_CONTEXT)
