from __future__ import annotations

import copy
from collections import Counter, defaultdict
from collections.abc import Mapping
from decimal import Decimal

from thesistrace.research_kernel.kernel_run import RunOutput
from thesistrace.research_kernel.numeric import canonical_decimal
from thesistrace.research_kernel.strategy import advance_strategy_metric_state


class ResearchResultError(ValueError):
    pass


def build_result_payload(
    output: RunOutput,
    *,
    rebalance_interval: int,
) -> dict[str, object]:
    """Project transient Kernel output into the bounded durable Result contract."""
    artifacts = output.artifacts_snapshot()
    factor = _mapping(artifacts, "factor_evaluation")
    strategy = _mapping(artifacts, "strategy_backtest")
    daily = _rows(strategy, "daily")
    if len(daily) != 504:
        raise ResearchResultError("Result requires exactly 504 Strategy observations")
    return {
        "factor_summary": _factor_summary(factor),
        "strategy_summary": _strategy_summary(strategy),
        "strategy_daily_observations": _strategy_daily_observations(strategy),
        "terminal_strategy_state": _terminal_strategy_state(
            strategy,
            rebalance_interval=rebalance_interval,
        ),
    }


def _factor_summary(factor: Mapping[str, object]) -> dict[str, object]:
    horizons = factor.get("horizons")
    if not isinstance(horizons, Mapping) or set(horizons) != {"1", "5", "20"}:
        raise ResearchResultError("Factor result must contain horizons 1, 5, and 20")
    projected: dict[str, object] = {}
    for horizon in ("1", "5", "20"):
        value = horizons[horizon]
        if not isinstance(value, Mapping) or not isinstance(value.get("summary"), Mapping):
            raise ResearchResultError(f"Factor horizon {horizon} is incomplete")
        projected[horizon] = {
            "horizon": int(value["horizon"]),
            "alpha_checksum": str(value["alpha_checksum"]),
            "label_checksum": str(value["label_checksum"]),
            "source_checksum": str(value["checksum"]),
            "summary": copy.deepcopy(dict(value["summary"])),
        }
    return {"horizons": projected}


def _strategy_summary(strategy: Mapping[str, object]) -> dict[str, object]:
    metrics = strategy.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ResearchResultError("Strategy result has no metrics")
    projected = copy.deepcopy(dict(metrics))
    _remove_nested(projected, "maximum_drawdown", "series")
    _remove_nested(projected, "turnover", "events")
    _remove_nested(projected, "holdings_count", "daily")
    _remove_nested(projected, "maximum_single_name_weight", "daily")
    _remove_nested(projected, "cash_ratio", "daily")
    return {
        "alpha_checksum": str(strategy["alpha_checksum"]),
        "initial_cash_cny": str(strategy["initial_cash_cny"]),
        "source_checksum": str(strategy["checksum"]),
        "metrics": projected,
    }


def _strategy_daily_observations(
    strategy: Mapping[str, object],
) -> list[dict[str, object]]:
    daily = _rows(strategy, "daily")
    rejections = _rows(strategy, "rejections")
    rejection_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for rejection in rejections:
        rejection_counts[str(rejection["session"])][str(rejection["reason"])] += 1

    prior_cost = Decimal(0)
    observations: list[dict[str, object]] = []
    for row in daily:
        cumulative_cost = Decimal(str(row["cumulative_transaction_cost"]))
        session_cost = cumulative_cost - prior_cost
        prior_cost = cumulative_cost
        counts = rejection_counts[str(row["session"])]
        observations.append(
            {
                "session": str(row["session"]),
                "gross_nav": str(row["gross_nav"]),
                "net_nav": str(row["net_nav"]),
                "benchmark_nav": str(row["benchmark_nav"]),
                "net_cash": str(row["net_cash"]),
                "transaction_cost_cny": canonical_decimal(session_cost),
                "holdings_count": int(row["holdings_count"]),
                "maximum_single_name_weight": float(
                    row["maximum_single_name_weight"]
                ),
                "upper_limit_buy_rejections": counts["upper_limit_buy"],
                "lower_limit_sell_rejections": counts["lower_limit_sell"],
                "suspension_rejections": counts["suspension"],
            }
        )
    return observations


def _terminal_strategy_state(
    strategy: Mapping[str, object],
    *,
    rebalance_interval: int,
) -> dict[str, object]:
    daily = _rows(strategy, "daily")
    terminal = daily[-1]
    positions = _rows(strategy, "positions")
    turnover = strategy.get("metrics")
    rejections = _rows(strategy, "rejections")
    if not isinstance(turnover, Mapping):
        raise ResearchResultError("Strategy metric continuation is missing")
    turnover_value = turnover.get("turnover")
    if not isinstance(turnover_value, Mapping) or not isinstance(
        turnover_value.get("events"), list
    ):
        raise ResearchResultError("Strategy turnover continuation is missing")
    pending_signal = (
        {
            "signal_session": str(terminal["session"]),
            "execution": "next_research_session_open",
        }
        if (len(daily) - 1) % rebalance_interval == 0
        else None
    )
    return {
        "session": str(terminal["session"]),
        "gross_cash": str(terminal["gross_cash"]),
        "net_cash": str(terminal["net_cash"]),
        "gross_nav": str(terminal["gross_nav"]),
        "net_nav": str(terminal["net_nav"]),
        "benchmark_nav": str(terminal["benchmark_nav"]),
        "cumulative_transaction_cost": str(terminal["cumulative_transaction_cost"]),
        "positions": [copy.deepcopy(dict(position)) for position in positions],
        "rebalance_phase": {
            "origin_session": str(daily[0]["session"]),
            "report_session_count": len(daily),
            "rebalance_interval": rebalance_interval,
            "completed_intervals": len(daily) - 1,
        },
        "pending_signal": pending_signal,
        "last_daily_observation": copy.deepcopy(dict(terminal)),
        "metric_state": advance_strategy_metric_state(
            None,
            daily=[dict(item) for item in daily],
            turnover_events=[dict(item) for item in turnover_value["events"]],
            cumulative_cost=Decimal(str(terminal["cumulative_transaction_cost"])),
            rejections=[dict(item) for item in rejections],
        ),
    }


def _mapping(source: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = source.get(name)
    if not isinstance(value, Mapping):
        raise ResearchResultError(f"Kernel output is missing {name}")
    return value


def _rows(source: Mapping[str, object], name: str) -> list[Mapping[str, object]]:
    value = source.get(name)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ResearchResultError(f"Kernel output has invalid {name}")
    return value


def _remove_nested(value: dict[str, object], parent: str, child: str) -> None:
    nested = value.get(parent)
    if isinstance(nested, dict):
        nested.pop(child, None)
