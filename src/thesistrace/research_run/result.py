from __future__ import annotations

import copy
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow import ArrowException

from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    VerifiedBundle,
)
from thesistrace.publication.serialization import (
    ParquetContractError,
    ParquetWriterContract,
    canonicalize_parquet_rows,
)
from thesistrace.research_kernel.kernel_run import RunOutput
from thesistrace.research_kernel.numeric import canonical_decimal
from thesistrace.research_kernel.strategy import advance_strategy_metric_state


class ResearchResultError(ValueError):
    pass


RESULT_BUDGET_SESSION_BLOCK = 504
RESULT_BUDGET_BYTE_BLOCK = 1_048_576
RESULT_VALUE_NAMES = frozenset(
    {
        "factor_summary",
        "strategy_summary",
        "strategy_daily_observations",
        "terminal_strategy_state",
    }
)
FORBIDDEN_DURABLE_RESULT_KEYS = frozenset(
    {
        "alpha_matrix",
        "alpha_values",
        "forward_labels",
        "daily_factor_observations",
        "strategy_ledger",
        "orders",
        "child_orders",
        "fills",
        "position_history",
    }
)
STRATEGY_DAILY_OBSERVATIONS_CONTRACT = ParquetWriterContract(
    name="research-result-strategy-daily-observations",
    version=1,
    schema=pa.schema(
        [
            pa.field("session", pa.string(), nullable=False),
            pa.field("gross_nav", pa.string(), nullable=False),
            pa.field("net_nav", pa.string(), nullable=False),
            pa.field("benchmark_nav", pa.string(), nullable=False),
            pa.field("net_cash", pa.string(), nullable=False),
            pa.field("transaction_cost_cny", pa.string(), nullable=False),
            pa.field("holdings_count", pa.int64(), nullable=False),
            pa.field("maximum_single_name_weight", pa.float64(), nullable=False),
            pa.field("upper_limit_buy_rejections", pa.int64(), nullable=False),
            pa.field("lower_limit_sell_rejections", pa.int64(), nullable=False),
            pa.field("suspension_rejections", pa.int64(), nullable=False),
        ]
    ),
    sort_keys=("session",),
)


def result_bundle_byte_budget(research_period_session_count: int) -> int:
    if (
        isinstance(research_period_session_count, bool)
        or not isinstance(research_period_session_count, int)
        or research_period_session_count < 1
    ):
        raise ResearchResultError("Result budget requires a positive Research Period")
    blocks = (
        research_period_session_count + RESULT_BUDGET_SESSION_BLOCK - 1
    ) // RESULT_BUDGET_SESSION_BLOCK
    return blocks * RESULT_BUDGET_BYTE_BLOCK


def enforce_result_bundle_budget(
    exact_bytes: int,
    research_period_session_count: int,
) -> int:
    budget = result_bundle_byte_budget(research_period_session_count)
    if isinstance(exact_bytes, bool) or not isinstance(exact_bytes, int) or exact_bytes < 0:
        raise ResearchResultError("Result Bundle exact bytes are invalid")
    if exact_bytes > budget:
        raise ResearchResultError("Result Bundle exceeds session-scaled byte budget")
    return exact_bytes


def result_publication_payloads(
    result: Mapping[str, object],
) -> dict[str, JsonPayload | ParquetRowsPayload]:
    if set(result) != RESULT_VALUE_NAMES:
        raise ResearchResultError("Result must contain exactly four durable values")
    _reject_transient_values(result)
    observations = result.get("strategy_daily_observations")
    if (
        not isinstance(observations, list)
        or not observations
        or any(not isinstance(row, Mapping) for row in observations)
    ):
        raise ResearchResultError("Strategy Daily Observations are invalid")
    return {
        "factor_summary": JsonPayload(copy.deepcopy(result["factor_summary"])),
        "strategy_summary": JsonPayload(copy.deepcopy(result["strategy_summary"])),
        "strategy_daily_observations": ParquetRowsPayload(
            rows=tuple(dict(row) for row in observations),
            contract=STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
        ),
        "terminal_strategy_state": JsonPayload(copy.deepcopy(result["terminal_strategy_state"])),
    }


def read_result_bundle(bundle: VerifiedBundle) -> dict[str, object]:
    if bundle.kind != "research.result" or set(bundle.payloads) != RESULT_VALUE_NAMES:
        raise ResearchResultError("Result Bundle must contain exactly four durable values")
    result = {
        "factor_summary": _read_json_value(bundle, "factor_summary"),
        "strategy_summary": _read_json_value(bundle, "strategy_summary"),
        "strategy_daily_observations": _read_daily_observations(bundle),
        "terminal_strategy_state": _read_json_value(bundle, "terminal_strategy_state"),
    }
    _reject_transient_values(result)
    return result


def build_result_payload(
    output: RunOutput,
    *,
    rebalance_interval: int,
    universe: str,
) -> dict[str, object]:
    """Project transient Kernel output into the bounded durable Result contract."""
    artifacts = output.artifacts_snapshot()
    factor = _mapping(artifacts, "factor_evaluation")
    strategy = _mapping(artifacts, "strategy_backtest")
    daily = _rows(strategy, "daily")
    if not daily:
        raise ResearchResultError("Result requires a positive Research Period")
    return {
        "factor_summary": _factor_summary(factor),
        "strategy_summary": _strategy_summary(strategy, universe=universe),
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
        daily = value.get("daily")
        if not isinstance(daily, list):
            raise ResearchResultError(f"Factor horizon {horizon} has no observations")
        summary = copy.deepcopy(dict(value["summary"]))
        ic = summary.get("ic")
        rank_ic = summary.get("rank_ic")
        if not isinstance(ic, Mapping) or not isinstance(rank_ic, Mapping):
            raise ResearchResultError(f"Factor horizon {horizon} summary is invalid")
        projected[horizon] = {
            "horizon": int(value["horizon"]),
            "alpha_checksum": str(value["alpha_checksum"]),
            "label_checksum": str(value["label_checksum"]),
            "source_checksum": str(value["checksum"]),
            "summary": summary,
            "coverage": {
                "signal_session_count": len(daily),
                "ic_valid_session_count": int(ic["valid_session_count"]),
                "rank_ic_valid_session_count": int(rank_ic["valid_session_count"]),
                "quantile_valid_session_count": sum(
                    isinstance(observation, Mapping) and observation.get("quantile_reason") is None
                    for observation in daily
                ),
            },
        }
    return {"horizons": projected}


def _strategy_summary(
    strategy: Mapping[str, object],
    *,
    universe: str,
) -> dict[str, object]:
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
        "benchmark": {
            "universe": universe,
            "methodology": "selected_universe_equal_weight",
        },
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
                "maximum_single_name_weight": float(row["maximum_single_name_weight"]),
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


def _read_json_value(bundle: VerifiedBundle, name: str) -> object:
    payload = bundle.payloads[name]
    if payload.media_type != "application/json" or payload.serialization != {
        "format": "canonical-json",
        "version": 1,
    }:
        raise ResearchResultError(f"Result value {name} has an invalid encoding")
    try:
        return json.loads(payload.content)
    except (TypeError, ValueError) as error:
        raise ResearchResultError(f"Result value {name} is invalid JSON") from error


def _read_daily_observations(bundle: VerifiedBundle) -> list[dict[str, object]]:
    payload = bundle.payloads["strategy_daily_observations"]
    expected_serialization = {
        "format": "canonical-parquet",
        "writer_contract": STRATEGY_DAILY_OBSERVATIONS_CONTRACT.descriptor(),
    }
    if (
        payload.media_type != "application/vnd.apache.parquet"
        or payload.serialization != expected_serialization
    ):
        raise ResearchResultError("Strategy Daily Observations have an invalid encoding")
    try:
        table = pq.read_table(pa.BufferReader(payload.content))
        if table.schema != STRATEGY_DAILY_OBSERVATIONS_CONTRACT.schema:
            raise ResearchResultError("Strategy Daily Observations schema is invalid")
        rows = canonicalize_parquet_rows(
            table.to_pylist(),
            STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
        )
    except (ArrowException, ParquetContractError, TypeError, ValueError) as error:
        raise ResearchResultError("Strategy Daily Observations are invalid") from error
    if not rows:
        raise ResearchResultError("Strategy Daily Observations cannot be empty")
    return rows


def _reject_transient_values(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = set(value) & FORBIDDEN_DURABLE_RESULT_KEYS
        if forbidden:
            raise ResearchResultError(f"Result contains transient value: {sorted(forbidden)[0]}")
        for nested in value.values():
            _reject_transient_values(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_transient_values(nested)
