"""DailyTrack-owned immutable Checkpoint projection and Kernel restoration."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal

from thesistrace.daily_track.models import TrackingOrigin
from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha
from thesistrace.research_kernel.canonical_state import canonical_sessions
from thesistrace.research_kernel.kernel_advance import continuation_snapshot
from thesistrace.research_kernel.kernel_run import KernelRunError, KernelState, RunInput
from thesistrace.research_kernel.numeric import canonical_decimal
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import (
    advance_strategy_metric_state,
    strategy_metrics_from_state,
)
from thesistrace.research_kernel.terminal_state_schema import (
    TerminalStrategyStateValue,
)


def project_tracking_checkpoint(
    state: KernelState,
    *,
    retained_strategy_sessions: Sequence[str],
) -> dict[str, object]:
    """Project transient Kernel internals into bounded immutable product truth."""
    run_input = state.run_input_with_canonical(state.canonical_snapshot())
    output = state.output_snapshot()
    alpha = _mapping(output.get("alpha_matrix"), "Alpha Matrix")
    factor = _mapping(output.get("factor_evaluation"), "Factor Evaluation")
    strategy = _mapping(output.get("strategy_backtest"), "Strategy Backtest")
    continuation = continuation_snapshot(state)
    continuation_bytes = canonical_json_bytes(continuation)
    return {
        "schema_version": "daily-track-checkpoint-v1",
        "origin_session": state.origin_session,
        "session_count": state.session_count,
        "boundary_session": state.boundary_session,
        "run_input": {
            "alpha_expression": run_input.alpha_expression_snapshot(),
            "field_bindings": run_input.field_bindings_snapshot(),
            "universe": run_input.universe,
            "neutralization": run_input.neutralization,
            "holdings_count": run_input.holdings_count,
            "rebalance_interval": run_input.rebalance_interval,
            "initial_cash_cny": run_input.initial_cash_cny,
            "commission_rate_all_in": run_input.commission_rate_all_in,
            "commission_min_cny": run_input.commission_min_cny,
            "stamp_duty_sell_rate": run_input.stamp_duty_sell_rate,
            "transfer_fee_rate": run_input.transfer_fee_rate,
        },
        "alpha_state": {
            "expression": alpha["expression"],
            "effective_lookback": alpha["effective_lookback"],
            "neutralization": alpha["neutralization"],
        },
        "factor_summary": _factor_summary(factor),
        "strategy_state": _strategy_state(
            state,
            strategy,
            retained_strategy_sessions=retained_strategy_sessions,
        ),
        "continuation_sha256": hashlib.sha256(continuation_bytes).hexdigest(),
        "pending_alpha_sessions": len(continuation["pending_alpha"]),
        "rolling_factor_rows": len(continuation["rolling_factor"]),
    }


def restore_tracking_checkpoint(
    value: Mapping[str, object],
    *,
    canonical: dict[str, object],
) -> KernelState:
    """Restore the compact authoritative state; transient values remain absent."""
    contract = _mapping(value.get("run_input"), "Tracking run input")
    run_input = RunInput(
        canonical_data=canonical,
        alpha_expression=contract["alpha_expression"],
        field_bindings={
            str(key): str(item)
            for key, item in _mapping(contract.get("field_bindings"), "field bindings").items()
        },
        universe=str(contract["universe"]),
        neutralization=str(contract["neutralization"]),
        holdings_count=int(contract["holdings_count"]),
        rebalance_interval=int(contract["rebalance_interval"]),
        initial_cash_cny=str(contract["initial_cash_cny"]),
        commission_rate_all_in=str(contract["commission_rate_all_in"]),
        commission_min_cny=str(contract["commission_min_cny"]),
        stamp_duty_sell_rate=str(contract["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(contract["transfer_fee_rate"]),
    )
    sessions = canonical_sessions(canonical, "DailyTrack Canonical Data")
    if len(sessions) != int(value["session_count"]) or sessions[-1] != str(
        value["boundary_session"]
    ):
        raise KernelRunError("DailyTrack Checkpoint boundary does not match Canonical Data")
    factor_summary = _mapping(value.get("factor_summary"), "Factor Summary")
    factor_horizons = _mapping(factor_summary.get("horizons"), "Factor horizons")
    if set(factor_horizons) != {"1", "5", "20"}:
        raise KernelRunError("DailyTrack Factor Summary horizons are invalid")
    strategy_state = _mapping(value.get("strategy_state"), "Strategy state")
    terminal = _mapping(strategy_state.get("terminal"), "Terminal Strategy State")
    resume_observation = _mapping(
        terminal.get("continuation_observation"),
        "Strategy continuation observation",
    )
    positions = terminal.get("positions")
    continuation_positions = terminal.get("continuation_positions")
    metric_state = _mapping(
        terminal.get("continuation_metric_state"),
        "Strategy metric continuation",
    )
    retained_delta = strategy_state.get("retained_delta")
    summary = _mapping(strategy_state.get("summary"), "Strategy summary")
    if (
        not isinstance(positions, list)
        or not isinstance(continuation_positions, list)
        or not isinstance(retained_delta, list)
    ):
        raise KernelRunError("DailyTrack Strategy state is invalid")
    return KernelState(
        run_input=run_input,
        output={
            "alpha_matrix": {
                **dict(_mapping(value.get("alpha_state"), "Alpha state")),
                "sessions": [],
            },
            "forward_labels": {"horizons": {}},
            "factor_evaluation": {
                "horizons": {
                    str(horizon): {**dict(_mapping(item, "Factor horizon")), "daily": []}
                    for horizon, item in factor_horizons.items()
                }
            },
            "strategy_backtest": {
                "daily": [dict(item) for item in retained_delta if isinstance(item, Mapping)],
                "positions": copy.deepcopy(positions),
                "metrics": dict(summary),
                "orders": [],
                "child_orders": [],
                "fills": [],
                "rebalance_events": [],
                "rejections": [],
                "diagnostics": [],
            },
            "strategy_time_series": {"daily": []},
            "strategy_events": {},
            "diagnostics": {},
        },
        strategy_resume={
            "daily": [dict(resume_observation)],
            "positions": copy.deepcopy(continuation_positions),
            "report_session_count": int(terminal["continuation_report_session_count"]),
            "metric_state": dict(metric_state),
        },
        origin_session=str(value["origin_session"]),
    )


def restore_tracking_origin(
    origin: TrackingOrigin,
    terminal_value: Mapping[str, object],
    canonical: dict[str, object],
) -> KernelState:
    """Build the first forward-only Kernel state without replaying the seed Run."""
    terminal = TerminalStrategyStateValue.model_validate(terminal_value)
    run_input = _origin_run_input(origin, canonical)
    parsed_alpha = validate_normalized_alpha(
        run_input.alpha_expression_snapshot(),
        field_bindings=run_input.field_bindings_snapshot(),
    )
    metric_state = terminal.metric_state.model_dump(mode="json", exclude_unset=True)
    last_daily = terminal.last_daily_observation.model_dump(mode="json")
    positions = [item.model_dump(mode="json") for item in terminal.positions]
    factor_horizons = {
        str(horizon): {
            "horizon": horizon,
            "summary": {},
            "coverage": {
                "signal_session_count": 0,
                "ic_valid_session_count": 0,
                "rank_ic_valid_session_count": 0,
                "quantile_valid_session_count": 0,
            },
            "daily": [],
        }
        for horizon in (1, 5, 20)
    }
    return KernelState(
        run_input=run_input,
        output={
            "alpha_matrix": {
                "expression": run_input.alpha_expression_snapshot(),
                "effective_lookback": parsed_alpha.effective_lookback,
                "neutralization": run_input.neutralization,
                "sessions": [],
            },
            "forward_labels": {"horizons": {}},
            "factor_evaluation": {"horizons": factor_horizons},
            "strategy_backtest": {
                "daily": [last_daily],
                "positions": positions,
                "metrics": strategy_metrics_from_state(metric_state),
                "metric_state": metric_state,
                "orders": [],
                "child_orders": [],
                "fills": [],
                "rebalance_events": [],
                "rejections": [],
                "diagnostics": [],
            },
            "strategy_time_series": {"daily": []},
            "strategy_events": {},
            "diagnostics": {},
        },
        strategy_resume={
            "daily": [last_daily],
            "positions": positions,
            "report_session_count": terminal.rebalance_phase.report_session_count,
            "metric_state": metric_state,
        },
        origin_session=terminal.rebalance_phase.origin_session,
    )


def terminal_strategy_state(state: KernelState) -> dict[str, object]:
    """Project the finalized account boundary used by durable session coordinates."""
    strategy = _mapping(
        state.output_snapshot().get("strategy_backtest"),
        "Strategy Backtest",
    )
    daily = _rows(strategy.get("daily"), "Strategy daily observations")
    positions = _rows(strategy.get("positions"), "Strategy positions")
    metric_state = _mapping(strategy.get("metric_state"), "Strategy metric state")
    terminal = daily[-1]
    session_count = int(metric_state["session_count"])
    rebalance_interval = state.run_input_with_canonical(
        state.canonical_snapshot()
    ).rebalance_interval
    return {
        "session": str(terminal["session"]),
        "gross_cash": str(terminal["gross_cash"]),
        "net_cash": str(terminal["net_cash"]),
        "gross_nav": str(terminal["gross_nav"]),
        "net_nav": str(terminal["net_nav"]),
        "benchmark_nav": str(terminal["benchmark_nav"]),
        "cumulative_transaction_cost": str(
            terminal["cumulative_transaction_cost"]
        ),
        "positions": [copy.deepcopy(dict(item)) for item in positions],
        "rebalance_phase": {
            "origin_session": state.origin_session,
            "report_session_count": session_count,
            "rebalance_interval": rebalance_interval,
            "completed_intervals": session_count - 1,
        },
        "pending_signal": (
            {
                "signal_session": str(terminal["session"]),
                "execution": "next_research_session_open",
            }
            if (session_count - 1) % rebalance_interval == 0
            else None
        ),
        "last_daily_observation": copy.deepcopy(dict(terminal)),
        "metric_state": copy.deepcopy(dict(metric_state)),
    }


def _origin_run_input(
    origin: TrackingOrigin,
    canonical: dict[str, object],
) -> RunInput:
    immutable_input = origin.immutable_input
    definition = _mapping(immutable_input.get("definition"), "Tracking Definition")
    content = _mapping(definition.get("content"), "Tracking Definition content")
    alpha = _mapping(content.get("alpha"), "Tracking Alpha")
    strategy = _mapping(immutable_input.get("strategy"), "Tracking Strategy")
    costs = _mapping(immutable_input.get("costs"), "Tracking Costs")
    field_bindings = _mapping(
        immutable_input.get("field_bindings"),
        "Tracking field bindings",
    )
    return RunInput(
        canonical_data=canonical,
        alpha_expression=dict(alpha),
        field_bindings={str(key): str(value) for key, value in field_bindings.items()},
        universe=str(content["universe"]),
        neutralization=str(content["neutralization"]),
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_every_sessions"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
    )


def _factor_summary(factor: Mapping[str, object]) -> dict[str, object]:
    horizons = _mapping(factor.get("horizons"), "Factor horizons")
    if set(horizons) != {"1", "5", "20"}:
        raise KernelRunError("Factor result must contain horizons 1, 5, and 20")
    projected: dict[str, object] = {}
    for horizon in ("1", "5", "20"):
        value = _mapping(horizons[horizon], "Factor horizon")
        summary = copy.deepcopy(dict(_mapping(value.get("summary"), "Factor summary")))
        daily = _rows(value.get("daily"), "Factor daily observations")
        ic = _mapping(summary.get("ic"), "Factor IC summary")
        rank_ic = _mapping(summary.get("rank_ic"), "Factor Rank IC summary")
        projected[horizon] = {
            "horizon": int(value["horizon"]),
            "summary": summary,
            "coverage": {
                "signal_session_count": len(daily),
                "ic_valid_session_count": int(ic["valid_session_count"]),
                "rank_ic_valid_session_count": int(rank_ic["valid_session_count"]),
                "quantile_valid_session_count": sum(
                    observation.get("quantile_reason") is None for observation in daily
                ),
            },
        }
    return {"horizons": projected}


def _strategy_state(
    state: KernelState,
    strategy: Mapping[str, object],
    *,
    retained_strategy_sessions: Sequence[str],
) -> dict[str, object]:
    daily = _rows(strategy.get("daily"), "Strategy daily observations")
    finalized_positions = _rows(strategy.get("positions"), "Strategy positions")
    rejections = _rows(strategy.get("rejections"), "Strategy rejections")
    metrics = _mapping(strategy.get("metrics"), "Strategy metrics")
    resume = state.strategy_resume_snapshot()
    resume_daily = _rows(resume.get("daily"), "Strategy resume observations")
    resume_positions = _rows(resume.get("positions"), "Strategy resume positions")
    metric_state = resume.get("metric_state")
    if not isinstance(metric_state, Mapping):
        resume_metrics = _mapping(resume.get("metrics"), "Strategy resume metrics")
        turnover = _mapping(resume_metrics.get("turnover"), "Strategy turnover")
        turnover_events = _rows(turnover.get("events"), "Strategy turnover events")
        resume_rejections = _rows(resume.get("rejections"), "Strategy resume rejections")
        resume_terminal = resume_daily[-1]
        metric_state = advance_strategy_metric_state(
            None,
            daily=[dict(item) for item in resume_daily],
            turnover_events=[dict(item) for item in turnover_events],
            cumulative_cost=Decimal(str(resume_terminal["cumulative_transaction_cost"])),
            rejections=[dict(item) for item in resume_rejections],
        )
    retained_set = {str(session) for session in retained_strategy_sessions}
    retained_delta = _minimal_strategy_observations(
        daily,
        rejections,
        retained_set=retained_set,
    )
    if [item["session"] for item in retained_delta] != [
        session for session in retained_strategy_sessions if session in retained_set
    ]:
        raise KernelRunError("Strategy retained delta does not cover the Advance")
    finalized_terminal = daily[-1]
    continuation_terminal = resume_daily[-1]
    report_count = int(metric_state["session_count"])
    final_report_count = report_count + 1
    rebalance_interval = state.run_input_with_canonical(
        state.canonical_snapshot()
    ).rebalance_interval
    return {
        "summary": _compact_strategy_metrics(metrics),
        "retained_delta": retained_delta,
        "terminal": {
            "session": str(finalized_terminal["session"]),
            "gross_cash": str(finalized_terminal["gross_cash"]),
            "net_cash": str(finalized_terminal["net_cash"]),
            "gross_nav": str(finalized_terminal["gross_nav"]),
            "net_nav": str(finalized_terminal["net_nav"]),
            "benchmark_nav": str(finalized_terminal["benchmark_nav"]),
            "cumulative_transaction_cost": str(finalized_terminal["cumulative_transaction_cost"]),
            "positions": [copy.deepcopy(dict(item)) for item in finalized_positions],
            "rebalance_phase": {
                "origin_session": state.origin_session,
                "report_session_count": final_report_count,
                "rebalance_interval": rebalance_interval,
                "completed_intervals": final_report_count - 1,
            },
            "pending_signal": (
                {
                    "signal_session": str(finalized_terminal["session"]),
                    "execution": "next_research_session_open",
                }
                if (final_report_count - 1) % rebalance_interval == 0
                else None
            ),
            "continuation_observation": _continuation_observation(continuation_terminal),
            "continuation_positions": [copy.deepcopy(dict(item)) for item in resume_positions],
            "continuation_report_session_count": report_count,
            "continuation_metric_state": copy.deepcopy(dict(metric_state)),
        },
    }


def _minimal_strategy_observations(
    daily: list[Mapping[str, object]],
    rejections: list[Mapping[str, object]],
    *,
    retained_set: set[str],
) -> list[dict[str, object]]:
    rejection_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for rejection in rejections:
        rejection_counts[str(rejection["session"])][str(rejection["reason"])] += 1
    observations: list[dict[str, object]] = []
    for index, row in enumerate(daily):
        session = str(row["session"])
        if session not in retained_set:
            continue
        prior_cost = (
            Decimal(0)
            if index == 0
            else Decimal(str(daily[index - 1]["cumulative_transaction_cost"]))
        )
        session_cost = Decimal(str(row["cumulative_transaction_cost"])) - prior_cost
        counts = rejection_counts[session]
        observations.append(
            {
                "session": session,
                "gross_nav": str(row["gross_nav"]),
                "net_nav": str(row["net_nav"]),
                "benchmark_nav": str(row["benchmark_nav"]),
                "net_cash": str(row["net_cash"]),
                "transaction_cost_cny": canonical_decimal(session_cost),
                "holdings_count": int(row["holdings_count"]),
                "maximum_single_name_weight": float(row["maximum_single_name_weight"]),
                "upper_limit_buy_rejections": counts["upper_limit_buy"],
                "lower_limit_sell_rejections": counts["lower_limit_sell"],
                "suspension_rejections": counts["suspension"],
            }
        )
    return observations


def _continuation_observation(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: copy.deepcopy(value[key])
        for key in (
            "session",
            "gross_cash",
            "net_cash",
            "cumulative_transaction_cost",
            "benchmark_nav",
            "gross_nav",
            "net_nav",
        )
    }


def _compact_strategy_metrics(metrics: Mapping[str, object]) -> dict[str, object]:
    value = copy.deepcopy(dict(metrics))
    for parent, child in (
        ("maximum_drawdown", "series"),
        ("turnover", "events"),
        ("holdings_count", "daily"),
        ("maximum_single_name_weight", "daily"),
        ("cash_ratio", "daily"),
    ):
        nested = value.get(parent)
        if isinstance(nested, dict):
            nested.pop(child, None)
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise KernelRunError(f"{name} is invalid")
    return value


def _rows(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise KernelRunError(f"{name} is invalid")
    return value
