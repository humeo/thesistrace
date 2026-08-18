from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from time import monotonic

from thesistrace.research_kernel.alpha import (
    advance_alpha_checksum,
    evaluate_columnar_alpha_sessions,
)
from thesistrace.research_kernel.factor import (
    HORIZONS,
    columnar_forward_factor_days_by_horizon,
    factor_day,
)
from thesistrace.research_kernel.kernel_run import RunInput, calculation_definition
from thesistrace.research_kernel.numeric import canonical_decimal
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import (
    advance_strategy_metric_state,
    run_strategy,
    strategy_metrics_from_state,
)
from thesistrace.research_series import ColumnarResearchSeries

_STATISTIC_NAMES = (
    "ic",
    "rank_ic",
    "q1",
    "q2",
    "q3",
    "q4",
    "q5",
    "top_bottom_return",
)
_MAX_PENDING_ALPHA_SESSIONS = 21


@dataclass(frozen=True)
class ResearchChunkCalculation:
    continuation: dict[str, object]
    strategy_daily_observations: tuple[dict[str, object], ...]
    final_values: dict[str, object] | None
    phase_seconds: dict[str, float]


def empty_research_continuation() -> dict[str, object]:
    return {
        "schema_version": "research-chunk-continuation-v2",
        "completed_research_session_count": 0,
        "rolling_tail_sessions": [],
        "pending_alpha": [],
        "alpha_checksum": None,
        "factor_state": empty_factor_state(),
        "strategy_state": None,
        "strategy_checksum": None,
    }


def execute_research_chunk(
    *,
    run_input: RunInput,
    research_data: ColumnarResearchSeries,
    research_sessions: tuple[str, ...],
    final_chunk: bool,
    continuation: Mapping[str, object],
    cancellation_check: Callable[[], None],
) -> ResearchChunkCalculation:
    alpha_started = monotonic()
    state = _copy_research_continuation(continuation)
    if not research_sessions:
        return ResearchChunkCalculation(
            continuation=state,
            strategy_daily_observations=(),
            final_values=None,
            phase_seconds={
                "alpha_and_pending": monotonic() - alpha_started,
                "factor": 0.0,
                "strategy": 0.0,
                "finalize": 0.0,
            },
        )
    calendar = tuple(research_data.sessions)
    if any(session not in calendar for session in research_sessions):
        raise ValueError("Research Chunk sessions are outside its data slice")
    cancellation_check()
    evaluated = evaluate_columnar_alpha_sessions(
        research_data,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
        cancellation_check=cancellation_check,
    )
    selected = set(research_sessions)
    new_alpha = [dict(row) for row in evaluated["sessions"] if str(row["session"]) in selected]
    if [str(row["session"]) for row in new_alpha] != list(research_sessions):
        raise ValueError("Research Chunk Alpha output is incomplete")
    for row in new_alpha:
        state["alpha_checksum"] = advance_alpha_checksum(
            None if state["alpha_checksum"] is None else str(state["alpha_checksum"]),
            row,
        )
    pending = state["pending_alpha"]
    if not isinstance(pending, list):
        raise ValueError("Pending Alpha continuation is invalid")
    pending.extend(
        _compact_pending_alpha(row, research_data)
        for row in new_alpha
    )
    if len(pending) > _MAX_PENDING_ALPHA_SESSIONS + len(research_sessions):
        raise ValueError("Pending Alpha continuation exceeded its bound")

    matrix_rows: list[dict[str, object]] = []
    for value in pending:
        item = _mapping(value, "Pending Alpha")
        matrix_rows.append(_expand_pending_alpha(item, research_data))
    matrix_rows.sort(key=lambda row: calendar.index(str(row["session"])))
    matrix = {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": run_input.alpha_execution_plan().effective_lookback,
        "neutralization": run_input.neutralization,
        "sessions": matrix_rows,
        "checksum": state["alpha_checksum"],
    }
    last_new_index = calendar.index(research_sessions[-1])
    signal_sessions_by_horizon: dict[int, list[str]] = {}
    for horizon in HORIZONS:
        resolvable: list[str] = []
        for value in pending:
            item = _mapping(value, "Pending Alpha")
            remaining = item.get("remaining_horizons")
            if not isinstance(remaining, list) or horizon not in remaining:
                continue
            signal_session = str(item.get("session"))
            signal_index = calendar.index(signal_session)
            if final_chunk or signal_index + 1 + horizon <= last_new_index:
                resolvable.append(signal_session)
                remaining.remove(horizon)
        signal_sessions_by_horizon[horizon] = resolvable
    alpha_and_pending_seconds = monotonic() - alpha_started
    factor_started = monotonic()
    daily_by_horizon = columnar_forward_factor_days_by_horizon(
        research_data,
        matrix,
        signal_sessions_by_horizon=signal_sessions_by_horizon,
        cancellation_check=cancellation_check,
    )
    state["factor_state"] = advance_factor_state_from_daily(
        _mapping(state["factor_state"], "Factor state"),
        daily_by_horizon,
    )
    state["pending_alpha"] = [
        value for value in pending if _mapping(value, "Pending Alpha")["remaining_horizons"]
    ]
    if len(state["pending_alpha"]) > _MAX_PENDING_ALPHA_SESSIONS:
        raise ValueError("Pending Alpha continuation exceeded its bound")

    factor_seconds = monotonic() - factor_started
    strategy_started = monotonic()
    prior_strategy = state.get("strategy_state")
    prior_cost = Decimal(0)
    prior_daily_count = 0
    if prior_strategy is not None:
        strategy_continuation = _mapping(prior_strategy, "Strategy continuation")
        prior_daily = strategy_continuation.get("daily")
        if not isinstance(prior_daily, list) or len(prior_daily) != 1:
            raise ValueError("Strategy continuation is not bounded")
        prior_cost = Decimal(str(prior_daily[0]["cumulative_transaction_cost"]))
        prior_daily_count = 1
    else:
        strategy_continuation = None
    strategy = run_strategy(
        research_data,
        matrix,
        calculation_definition(run_input),
        origin_session=str(run_input.research_start_session),
        terminal_cutoff=final_chunk,
        continuation=strategy_continuation,
        cancellation_check=cancellation_check,
    )
    new_daily = [dict(value) for value in strategy["daily"][prior_daily_count:]]
    new_rejections = [dict(value) for value in strategy["rejections"]]
    observations = _strategy_observations(
        new_daily,
        new_rejections,
        prior_cumulative_cost=prior_cost,
    )
    for observation in observations:
        state["strategy_checksum"] = _advance_checksum(state.get("strategy_checksum"), observation)
    metric_state = strategy.get("metric_state")
    if not isinstance(metric_state, Mapping):
        turnover = _mapping(
            _mapping(strategy["metrics"], "Strategy metrics")["turnover"],
            "Strategy turnover",
        )
        metric_state = advance_strategy_metric_state(
            None,
            daily=new_daily,
            turnover_events=[dict(value) for value in turnover["events"]],
            cumulative_cost=Decimal(str(strategy["daily"][-1]["cumulative_transaction_cost"])),
            rejections=new_rejections,
        )
    metric_state = dict(metric_state)
    metric_state["cumulative_cost"] = str(Decimal(str(metric_state["cumulative_cost"])).normalize())
    strategy_seconds = monotonic() - strategy_started
    finalize_started = monotonic()
    completed_count = int(state["completed_research_session_count"]) + len(research_sessions)
    state["completed_research_session_count"] = completed_count
    state["strategy_state"] = {
        "daily": [dict(strategy["daily"][-1])],
        "positions": [dict(value) for value in strategy["positions"]],
        "orders": [],
        "child_orders": [],
        "fills": [],
        "rebalance_events": [],
        "rejections": [],
        "diagnostics": [],
        "report_session_count": completed_count,
        "metric_state": metric_state,
    }
    lookback = max(run_input.alpha_execution_plan().effective_lookback, 2)
    state["rolling_tail_sessions"] = list(calendar[-lookback:])

    final_values: dict[str, object] | None = None
    if final_chunk:
        if state["pending_alpha"]:
            raise ValueError("Final Research Chunk has unresolved Alpha Labels")
        metrics = strategy_metrics_from_state(dict(metric_state))
        for metric_name, history_name in (
            ("maximum_drawdown", "series"),
            ("turnover", "events"),
            ("holdings_count", "daily"),
            ("maximum_single_name_weight", "daily"),
            ("cash_ratio", "daily"),
        ):
            metric = metrics.get(metric_name)
            if isinstance(metric, dict):
                metric.pop(history_name, None)
        terminal = dict(strategy["daily"][-1])
        final_values = {
            "factor_summary": finalize_factor_state(
                _mapping(state["factor_state"], "Factor state"),
                alpha_checksum=str(state["alpha_checksum"]),
            ),
            "strategy_summary": {
                "alpha_checksum": str(state["alpha_checksum"]),
                "initial_cash_cny": str(strategy["initial_cash_cny"]),
                "source_checksum": str(state["strategy_checksum"]),
                "benchmark": {
                    "universe": run_input.universe,
                    "methodology": "selected_universe_equal_weight",
                },
                "metrics": metrics,
            },
            "terminal_strategy_state": {
                "session": str(terminal["session"]),
                "gross_cash": str(terminal["gross_cash"]),
                "net_cash": str(terminal["net_cash"]),
                "gross_nav": str(terminal["gross_nav"]),
                "net_nav": str(terminal["net_nav"]),
                "benchmark_nav": str(terminal["benchmark_nav"]),
                "cumulative_transaction_cost": str(terminal["cumulative_transaction_cost"]),
                "positions": [dict(value) for value in strategy["positions"]],
                "rebalance_phase": {
                    "origin_session": str(run_input.research_start_session),
                    "report_session_count": completed_count,
                    "rebalance_interval": run_input.rebalance_interval,
                    "completed_intervals": completed_count - 1,
                },
                "pending_signal": (
                    {
                        "signal_session": str(terminal["session"]),
                        "execution": "next_research_session_open",
                    }
                    if (completed_count - 1) % run_input.rebalance_interval == 0
                    else None
                ),
                "last_daily_observation": terminal,
                "metric_state": metric_state,
            },
        }
    return ResearchChunkCalculation(
        continuation=state,
        strategy_daily_observations=tuple(observations),
        final_values=final_values,
        phase_seconds={
            "alpha_and_pending": alpha_and_pending_seconds,
            "factor": factor_seconds,
            "strategy": strategy_seconds,
            "finalize": monotonic() - finalize_started,
        },
    )


def _compact_pending_alpha(
    row: Mapping[str, object],
    research_data: ColumnarResearchSeries,
) -> dict[str, object]:
    session = str(row["session"])
    members = tuple(sorted(research_data.universe_members.get(session, ())))
    raw_values = row.get("values")
    coverage_loss = row.get("coverage_loss")
    if not isinstance(raw_values, list) or not isinstance(coverage_loss, Mapping):
        raise ValueError("Alpha Matrix session is invalid")
    items = [_mapping(value, "Alpha Matrix value") for value in raw_values]
    instrument_ids = tuple(str(item.get("instrument_id")) for item in items)
    if len(items) == len(members):
        if instrument_ids != members:
            raise ValueError("Alpha Matrix session is invalid")
        compact_values = [item.get("value") for item in items]
    else:
        compact_values: list[object] = [None] * len(members)
        member_index = 0
        prior_instrument_id: str | None = None
        for instrument_id, item in zip(instrument_ids, items, strict=True):
            if prior_instrument_id is not None and instrument_id <= prior_instrument_id:
                raise ValueError("Alpha Matrix session is invalid")
            while member_index < len(members) and members[member_index] < instrument_id:
                member_index += 1
            if member_index == len(members) or members[member_index] != instrument_id:
                raise ValueError("Alpha Matrix session is invalid")
            compact_values[member_index] = item.get("value")
            prior_instrument_id = instrument_id
    return {
        "session": session,
        "values": compact_values,
        "coverage_loss": dict(coverage_loss),
        "remaining_horizons": list(HORIZONS),
    }


def _expand_pending_alpha(
    item: Mapping[str, object],
    research_data: ColumnarResearchSeries,
) -> dict[str, object]:
    session = str(item.get("session"))
    members = tuple(sorted(research_data.universe_members.get(session, ())))
    values = item.get("values")
    coverage_loss = item.get("coverage_loss")
    if (
        not isinstance(values, list)
        or len(values) != len(members)
        or not isinstance(coverage_loss, Mapping)
    ):
        raise ValueError("Pending Alpha continuation is invalid")
    return {
        "session": session,
        "values": [
            {"instrument_id": instrument_id, "value": value}
            for instrument_id, value in zip(members, values, strict=True)
            if value is not None
        ],
        "coverage_loss": dict(coverage_loss),
    }


def empty_factor_state() -> dict[str, object]:
    return {
        "schema_version": "research-factor-aggregate-v1",
        "horizons": {
            str(horizon): {
                "signal_session_count": 0,
                "quantile_valid_session_count": 0,
                "statistics": {name: _empty_statistic() for name in _STATISTIC_NAMES},
                "label_checksum": None,
                "source_checksum": None,
            }
            for horizon in HORIZONS
        },
    }


def advance_factor_state(
    prior: Mapping[str, object],
    labels: Mapping[str, object],
) -> dict[str, object]:
    label_horizons = _mapping(labels.get("horizons"), "Label horizons")
    daily_by_horizon: dict[str, list[dict[str, object]]] = {}
    for horizon in HORIZONS:
        label_horizon = _mapping(
            label_horizons.get(str(horizon)),
            f"Label horizon {horizon}",
        )
        sessions = label_horizon.get("sessions")
        if not isinstance(sessions, list) or any(
            not isinstance(value, Mapping) for value in sessions
        ):
            raise ValueError("Label sessions are invalid")
        daily_by_horizon[str(horizon)] = []
        for session in sessions:
            samples = session.get("samples")
            if not isinstance(samples, list):
                raise ValueError("Label samples are invalid")
            daily_by_horizon[str(horizon)].append(
                {
                    "session": str(session["session"]),
                    "sample_count": len(samples),
                    **factor_day([dict(value) for value in samples]),
                }
            )
    return advance_factor_state_from_daily(prior, daily_by_horizon)


def advance_factor_state_from_daily(
    prior: Mapping[str, object],
    daily_by_horizon: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    state = _copy_factor_state(prior)
    for horizon in HORIZONS:
        horizon_state = _mapping(
            _mapping(state["horizons"], "Factor horizons")[str(horizon)],
            f"Factor horizon {horizon}",
        )
        statistics = _mapping(horizon_state["statistics"], "Factor statistics")
        daily_values = daily_by_horizon.get(str(horizon))
        if not isinstance(daily_values, list):
            raise ValueError("Factor daily continuation is invalid")
        for daily in daily_values:
            horizon_state["signal_session_count"] = int(horizon_state["signal_session_count"]) + 1
            if daily["quantile_reason"] is None:
                horizon_state["quantile_valid_session_count"] = (
                    int(horizon_state["quantile_valid_session_count"]) + 1
                )
            _advance_statistic(statistics["ic"], daily["ic"])
            _advance_statistic(statistics["rank_ic"], daily["rank_ic"])
            quantiles = _mapping(daily["quantile_returns"], "Factor quantiles")
            for name in ("q1", "q2", "q3", "q4", "q5"):
                _advance_statistic(statistics[name], quantiles[name])
            _advance_statistic(
                statistics["top_bottom_return"],
                daily["top_bottom_return"],
            )
            horizon_state["label_checksum"] = _advance_checksum(
                horizon_state.get("label_checksum"),
                {
                    "session": daily["session"],
                    "sample_count": daily["sample_count"],
                },
            )
            horizon_state["source_checksum"] = _advance_checksum(
                horizon_state.get("source_checksum"),
                daily,
            )
    return state


def finalize_factor_state(
    state: Mapping[str, object],
    *,
    alpha_checksum: str,
) -> dict[str, object]:
    copied = _copy_factor_state(state)
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        value = _mapping(
            _mapping(copied["horizons"], "Factor horizons")[str(horizon)],
            f"Factor horizon {horizon}",
        )
        statistics = _mapping(value["statistics"], "Factor statistics")
        ic = _correlation_summary(statistics["ic"])
        rank_ic = _correlation_summary(statistics["rank_ic"])
        horizons[str(horizon)] = {
            "horizon": horizon,
            "alpha_checksum": alpha_checksum,
            "label_checksum": value.get("label_checksum") or hashlib.sha256(b"").hexdigest(),
            "source_checksum": value.get("source_checksum") or hashlib.sha256(b"").hexdigest(),
            "summary": {
                "ic": ic,
                "rank_ic": rank_ic,
                "quantile_returns": {
                    name: _mean(statistics[name]) for name in ("q1", "q2", "q3", "q4", "q5")
                },
                "top_bottom_return": _mean(statistics["top_bottom_return"]),
            },
            "coverage": {
                "signal_session_count": int(value["signal_session_count"]),
                "ic_valid_session_count": int(ic["valid_session_count"]),
                "rank_ic_valid_session_count": int(rank_ic["valid_session_count"]),
                "quantile_valid_session_count": int(value["quantile_valid_session_count"]),
            },
        }
    return {"horizons": horizons}


def _empty_statistic() -> dict[str, object]:
    return {
        "count": 0,
        "positive_count": 0,
        "sum_numerator": 0,
        "sum_denominator": 1,
        "square_sum_numerator": 0,
        "square_sum_denominator": 1,
        "fsum_partials": [],
    }


def _advance_statistic(value: object, observation: object) -> None:
    statistic = _mapping(value, "Factor statistic")
    if observation is None:
        return
    number = float(observation)
    if not math.isfinite(number):
        raise ValueError("Factor statistic is not finite")
    total = Fraction(
        int(statistic["sum_numerator"]),
        int(statistic["sum_denominator"]),
    ) + Fraction.from_float(number)
    square_total = (
        Fraction(
            int(statistic["square_sum_numerator"]),
            int(statistic["square_sum_denominator"]),
        )
        + Fraction.from_float(number) ** 2
    )
    statistic["count"] = int(statistic["count"]) + 1
    statistic["positive_count"] = int(statistic["positive_count"]) + int(number > 0)
    statistic["sum_numerator"] = total.numerator
    statistic["sum_denominator"] = total.denominator
    statistic["square_sum_numerator"] = square_total.numerator
    statistic["square_sum_denominator"] = square_total.denominator
    partials = statistic["fsum_partials"]
    if not isinstance(partials, list):
        raise ValueError("Factor fsum continuation is invalid")
    updated: list[float] = []
    for partial in partials:
        partial_number = float(partial)
        if abs(number) < abs(partial_number):
            number, partial_number = partial_number, number
        high = number + partial_number
        low = partial_number - (high - number)
        if low:
            updated.append(low)
        number = high
    updated.append(number)
    statistic["fsum_partials"] = updated


def _mean(value: object) -> float | None:
    statistic = _mapping(value, "Factor statistic")
    count = int(statistic["count"])
    if count == 0:
        return None
    partials = statistic["fsum_partials"]
    if not isinstance(partials, list):
        raise ValueError("Factor fsum continuation is invalid")
    return math.fsum(float(value) for value in partials) / count


def _correlation_summary(value: object) -> dict[str, object]:
    statistic = _mapping(value, "Factor statistic")
    count = int(statistic["count"])
    mean = _mean(statistic)
    deviation: float | None = None
    if count >= 2:
        total = Fraction(
            int(statistic["sum_numerator"]),
            int(statistic["sum_denominator"]),
        )
        square_total = Fraction(
            int(statistic["square_sum_numerator"]),
            int(statistic["square_sum_denominator"]),
        )
        variance = (square_total - total * total / count) / (count - 1)
        deviation = math.sqrt(float(variance))
    return {
        "mean": mean,
        "sample_deviation": deviation,
        "icir": (None if mean is None or deviation in {None, 0.0} else mean / deviation),
        "positive_fraction": (None if count == 0 else int(statistic["positive_count"]) / count),
        "valid_session_count": count,
    }


def _advance_checksum(prior: object, value: object) -> str:
    checksum = hashlib.sha256()
    if prior is not None:
        checksum.update(bytes.fromhex(str(prior)))
    checksum.update(canonical_json_bytes(value))
    return checksum.hexdigest()


def _strategy_observations(
    daily: list[dict[str, object]],
    rejections: list[dict[str, object]],
    *,
    prior_cumulative_cost: Decimal,
) -> list[dict[str, object]]:
    rejection_counts: dict[str, dict[str, int]] = {}
    for rejection in rejections:
        session = str(rejection["session"])
        reason = str(rejection["reason"])
        counts = rejection_counts.setdefault(session, {})
        counts[reason] = counts.get(reason, 0) + 1
    observations: list[dict[str, object]] = []
    prior_cost = prior_cumulative_cost
    for row in daily:
        cumulative_cost = Decimal(str(row["cumulative_transaction_cost"]))
        counts = rejection_counts.get(str(row["session"]), {})
        observations.append(
            {
                "session": str(row["session"]),
                "gross_nav": str(row["gross_nav"]),
                "net_nav": str(row["net_nav"]),
                "benchmark_nav": str(row["benchmark_nav"]),
                "net_cash": str(row["net_cash"]),
                "transaction_cost_cny": canonical_decimal(cumulative_cost - prior_cost),
                "holdings_count": int(row["holdings_count"]),
                "maximum_single_name_weight": float(row["maximum_single_name_weight"]),
                "upper_limit_buy_rejections": counts.get("upper_limit_buy", 0),
                "lower_limit_sell_rejections": counts.get("lower_limit_sell", 0),
                "suspension_rejections": counts.get("suspension", 0),
            }
        )
        prior_cost = cumulative_cost
    return observations


def _copy_research_continuation(value: Mapping[str, object]) -> dict[str, object]:
    import json

    copied = json.loads(canonical_json_bytes(value))
    if (
        not isinstance(copied, dict)
        or copied.get("schema_version") != "research-chunk-continuation-v2"
    ):
        raise ValueError("Research Chunk continuation is invalid")
    return copied


def _copy_factor_state(value: Mapping[str, object]) -> dict[str, object]:
    import json

    copied = json.loads(canonical_json_bytes(value))
    if (
        not isinstance(copied, dict)
        or copied.get("schema_version") != "research-factor-aggregate-v1"
    ):
        raise ValueError("Factor aggregate state is invalid")
    return copied


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} is invalid")
    return value
