import copy
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal

import pyarrow as pa

from thesistrace.numeric import canonical_decimal
from thesistrace.objects import ImmutableObjectStore, ParquetWriterContract
from thesistrace.strategy import maximum_drawdown


class CompactResultError(ValueError):
    pass


def required_string(name: str) -> pa.Field:
    return pa.field(name, pa.string(), nullable=False)


STRATEGY_DAILY_CONTRACT = ParquetWriterContract(
    name="result.strategy_daily_observation",
    version=1,
    schema=pa.schema(
        [
            required_string("session"),
            required_string("gross_nav"),
            required_string("net_nav"),
            required_string("benchmark_nav"),
            required_string("net_cash"),
            required_string("transaction_cost_cny"),
            pa.field("holdings_count", pa.int32(), nullable=False),
            pa.field("maximum_single_name_weight", pa.float64(), nullable=False),
            pa.field("upper_limit_buy_rejections", pa.int32(), nullable=False),
            pa.field("lower_limit_sell_rejections", pa.int32(), nullable=False),
            pa.field("suspension_rejections", pa.int32(), nullable=False),
        ]
    ),
    sort_keys=("session",),
)

REBALANCE_AGGREGATE_CONTRACT = ParquetWriterContract(
    name="result.rebalance_aggregate",
    version=1,
    schema=pa.schema(
        [
            required_string("session"),
            required_string("signal_session"),
            pa.field("turnover", pa.float64(), nullable=False),
            pa.field("fill_count", pa.int32(), nullable=False),
            pa.field("buy_order_count", pa.int32(), nullable=False),
            pa.field("sell_order_count", pa.int32(), nullable=False),
        ]
    ),
    sort_keys=("session",),
)

EXECUTION_AGGREGATE_CONTRACT = ParquetWriterContract(
    name="result.execution_aggregate",
    version=1,
    schema=pa.schema(
        [
            required_string("session"),
            pa.field("order_count", pa.int32(), nullable=False),
            pa.field("child_order_count", pa.int32(), nullable=False),
            pa.field("fill_count", pa.int32(), nullable=False),
            pa.field("buy_fill_count", pa.int32(), nullable=False),
            pa.field("sell_fill_count", pa.int32(), nullable=False),
            required_string("filled_notional_cny"),
            required_string("transaction_cost_cny"),
            pa.field("upper_limit_buy_rejections", pa.int32(), nullable=False),
            pa.field("lower_limit_sell_rejections", pa.int32(), nullable=False),
            pa.field("suspension_rejections", pa.int32(), nullable=False),
        ]
    ),
    sort_keys=("session",),
)

TERMINAL_POSITION_CONTRACT = ParquetWriterContract(
    name="result.terminal_position",
    version=1,
    schema=pa.schema(
        [
            required_string("instrument_id"),
            pa.field("execution_shares", pa.int64(), nullable=False),
            required_string("adjusted_units"),
            required_string("last_adjusted_price"),
        ]
    ),
    sort_keys=("instrument_id",),
)

RESULT_PARQUET_CONTRACTS = {
    "strategy_daily_observations": STRATEGY_DAILY_CONTRACT,
    "rebalance_aggregates": REBALANCE_AGGREGATE_CONTRACT,
    "execution_aggregates": EXECUTION_AGGREGATE_CONTRACT,
    "terminal_positions": TERMINAL_POSITION_CONTRACT,
}


def publish_compact_result_objects(
    objects: ImmutableObjectStore,
    artifacts: Mapping[str, Mapping[str, object]],
    definition: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    projection = compact_projection(artifacts, definition)
    entries: dict[str, dict[str, object]] = {}
    for kind, contract in RESULT_PARQUET_CONTRACTS.items():
        rows = projection[kind]
        if not isinstance(rows, list):
            raise CompactResultError(f"{kind} projection must be a table")
        entries[kind] = {
            "kind": kind,
            **objects.put_parquet_rows(rows, contract),
        }

    terminal_state = projection["terminal_strategy_state"]
    if not isinstance(terminal_state, dict):
        raise CompactResultError("Terminal Strategy State projection is invalid")
    terminal_state = {
        **terminal_state,
        "positions_object": object_reference(entries["terminal_positions"]),
    }
    json_payloads = {
        "factor_summary": projection["factor_summary"],
        "strategy_summary": projection["strategy_summary"],
        "diagnostic_summary": projection["diagnostic_summary"],
        "terminal_strategy_state": terminal_state,
    }
    for kind, payload in json_payloads.items():
        entries[kind] = {
            "kind": kind,
            "format": "json",
            **objects.put_json(payload),
        }
    return {kind: entries[kind] for kind in sorted(entries)}


def compact_projection(
    artifacts: Mapping[str, Mapping[str, object]],
    definition: Mapping[str, object],
) -> dict[str, object]:
    factor = require_mapping(artifacts, "factor_evaluation")
    strategy = require_mapping(artifacts, "strategy_backtest")
    matrix = require_mapping(artifacts, "alpha_matrix")
    diagnostics = require_mapping(artifacts, "diagnostics")
    daily = require_rows(strategy, "daily")
    if not daily:
        raise CompactResultError("Strategy result has no Daily Observations")
    positions = require_rows(strategy, "positions")
    return {
        "factor_summary": factor_summary(factor),
        "strategy_summary": strategy_summary(strategy),
        "diagnostic_summary": diagnostic_summary(
            matrix,
            factor,
            diagnostics,
        ),
        "strategy_daily_observations": strategy_daily_rows(strategy),
        "rebalance_aggregates": rebalance_aggregate_rows(strategy),
        "execution_aggregates": execution_aggregate_rows(strategy),
        "terminal_positions": [dict(row) for row in positions],
        "terminal_strategy_state": terminal_strategy_state(
            strategy,
            definition,
        ),
    }


def factor_summary(factor: Mapping[str, object]) -> dict[str, object]:
    horizons = factor.get("horizons")
    if not isinstance(horizons, Mapping):
        raise CompactResultError("Factor Evaluation has no horizons")
    projected: dict[str, object] = {}
    for horizon, value in sorted(horizons.items()):
        if not isinstance(value, Mapping):
            raise CompactResultError("Factor horizon is invalid")
        daily = value.get("daily")
        summary = value.get("summary")
        if not isinstance(daily, list) or not isinstance(summary, Mapping):
            raise CompactResultError("Factor horizon is incomplete")
        correlation_reasons = Counter(
            str(row["correlation_reason"])
            for row in daily
            if isinstance(row, Mapping) and row.get("correlation_reason") is not None
        )
        quantile_reasons = Counter(
            str(row["quantile_reason"])
            for row in daily
            if isinstance(row, Mapping) and row.get("quantile_reason") is not None
        )
        projected[str(horizon)] = {
            "horizon": int(value["horizon"]),
            "alpha_checksum": str(value["alpha_checksum"]),
            "label_checksum": str(value["label_checksum"]),
            "source_checksum": str(value["checksum"]),
            "summary": copy.deepcopy(dict(summary)),
            "diagnostics": {
                "session_count": len(daily),
                "missing_session_count": sum(
                    isinstance(row, Mapping)
                    and (
                        row.get("correlation_reason") is not None
                        or row.get("quantile_reason") is not None
                    )
                    for row in daily
                ),
                "correlation_reason_counts": dict(sorted(correlation_reasons.items())),
                "quantile_reason_counts": dict(sorted(quantile_reasons.items())),
            },
        }
    return {"horizons": projected}


def strategy_summary(strategy: Mapping[str, object]) -> dict[str, object]:
    metrics = strategy.get("metrics")
    if not isinstance(metrics, Mapping):
        raise CompactResultError("Strategy result has no metrics")
    projected_metrics = copy.deepcopy(dict(metrics))
    remove_nested(projected_metrics, "maximum_drawdown", "series")
    remove_nested(projected_metrics, "turnover", "events")
    remove_nested(projected_metrics, "holdings_count", "daily")
    remove_nested(projected_metrics, "maximum_single_name_weight", "daily")
    remove_nested(projected_metrics, "cash_ratio", "daily")
    return {
        "alpha_checksum": str(strategy["alpha_checksum"]),
        "initial_cash_cny": str(strategy["initial_cash_cny"]),
        "source_checksum": str(strategy["checksum"]),
        "metrics": projected_metrics,
    }


def strategy_daily_rows(strategy: Mapping[str, object]) -> list[dict[str, object]]:
    daily = require_rows(strategy, "daily")
    rejections = require_rows(strategy, "rejections")
    rejection_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for rejection in rejections:
        rejection_counts[str(rejection["session"])][str(rejection["reason"])] += 1
    prior_cost = Decimal(0)
    rows: list[dict[str, object]] = []
    for observation in daily:
        cumulative_cost = Decimal(str(observation["cumulative_transaction_cost"]))
        session_cost = cumulative_cost - prior_cost
        prior_cost = cumulative_cost
        counts = rejection_counts[str(observation["session"])]
        rows.append(
            {
                "session": str(observation["session"]),
                "gross_nav": str(observation["gross_nav"]),
                "net_nav": str(observation["net_nav"]),
                "benchmark_nav": str(observation["benchmark_nav"]),
                "net_cash": str(observation["net_cash"]),
                "transaction_cost_cny": canonical_decimal(session_cost),
                "holdings_count": int(observation["holdings_count"]),
                "maximum_single_name_weight": float(
                    observation["maximum_single_name_weight"]
                ),
                "upper_limit_buy_rejections": counts["upper_limit_buy"],
                "lower_limit_sell_rejections": counts["lower_limit_sell"],
                "suspension_rejections": counts["suspension"],
            }
        )
    return rows


def rebalance_aggregate_rows(
    strategy: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "session": str(event["session"]),
            "signal_session": str(event["signal_session"]),
            "turnover": float(event["turnover"]),
            "fill_count": int(event["fill_count"]),
            "buy_order_count": Counter(event["side_order"])["buy"],
            "sell_order_count": Counter(event["side_order"])["sell"],
        }
        for event in require_rows(strategy, "rebalance_events")
    ]


def execution_aggregate_rows(
    strategy: Mapping[str, object],
) -> list[dict[str, object]]:
    orders = group_by_session(require_rows(strategy, "orders"))
    child_orders = group_by_session(require_rows(strategy, "child_orders"))
    fills = group_by_session(require_rows(strategy, "fills"))
    rejections = group_by_session(require_rows(strategy, "rejections"))
    sessions = sorted(set(orders) | set(child_orders) | set(fills) | set(rejections))
    rows: list[dict[str, object]] = []
    for session in sessions:
        session_fills = fills[session]
        session_rejections = Counter(
            str(rejection["reason"]) for rejection in rejections[session]
        )
        rows.append(
            {
                "session": session,
                "order_count": len(orders[session]),
                "child_order_count": len(child_orders[session]),
                "fill_count": len(session_fills),
                "buy_fill_count": sum(
                    str(fill["side"]) == "buy" for fill in session_fills
                ),
                "sell_fill_count": sum(
                    str(fill["side"]) == "sell" for fill in session_fills
                ),
                "filled_notional_cny": canonical_decimal(
                    sum(
                        (Decimal(str(fill["raw_notional"])) for fill in session_fills),
                        Decimal(0),
                    )
                ),
                "transaction_cost_cny": canonical_decimal(
                    sum(
                        (Decimal(str(fill["cost"])) for fill in session_fills),
                        Decimal(0),
                    )
                ),
                "upper_limit_buy_rejections": session_rejections["upper_limit_buy"],
                "lower_limit_sell_rejections": session_rejections["lower_limit_sell"],
                "suspension_rejections": session_rejections["suspension"],
            }
        )
    return rows


def terminal_strategy_state(
    strategy: Mapping[str, object],
    definition: Mapping[str, object],
) -> dict[str, object]:
    daily = require_rows(strategy, "daily")
    terminal = daily[-1]
    strategy_definition = definition.get("strategy")
    if not isinstance(strategy_definition, Mapping):
        raise CompactResultError("Strategy Definition is invalid")
    rebalance_interval = int(strategy_definition["rebalance_interval"])
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
        "cumulative_transaction_cost": str(
            terminal["cumulative_transaction_cost"]
        ),
        "rebalance_phase": {
            "origin_session": str(daily[0]["session"]),
            "report_session_count": len(daily),
            "rebalance_interval": rebalance_interval,
            "completed_intervals": len(daily) - 1,
        },
        "pending_signal": pending_signal,
    }


def diagnostic_summary(
    matrix: Mapping[str, object],
    factor: Mapping[str, object],
    diagnostics: Mapping[str, object],
) -> dict[str, object]:
    matrix_sessions = matrix.get("sessions")
    strategy_diagnostics = diagnostics.get("strategy")
    if not isinstance(matrix_sessions, list) or not isinstance(
        strategy_diagnostics,
        list,
    ):
        raise CompactResultError("calculation diagnostics are invalid")
    alpha_reasons: Counter[str] = Counter()
    alpha_loss_sessions = 0
    for session in matrix_sessions:
        if not isinstance(session, Mapping):
            continue
        losses = session.get("coverage_loss")
        if not isinstance(losses, Mapping):
            continue
        if any(int(value) > 0 for value in losses.values()):
            alpha_loss_sessions += 1
        alpha_reasons.update(
            {
                str(reason): int(count)
                for reason, count in losses.items()
                if int(count) > 0
            }
        )
    strategy_reasons = Counter(
        str(item["reason"])
        for item in strategy_diagnostics
        if isinstance(item, Mapping) and "reason" in item
    )
    factor_horizons = factor.get("horizons")
    if not isinstance(factor_horizons, Mapping):
        raise CompactResultError("Factor diagnostics are invalid")
    return {
        "alpha_coverage_summary": {
            "session_count": len(matrix_sessions),
            "loss_session_count": alpha_loss_sessions,
            "reason_counts": dict(sorted(alpha_reasons.items())),
        },
        "factor_summary": {
            str(horizon): {
                "session_count": len(value.get("daily", []))
                if isinstance(value, Mapping)
                else 0
            }
            for horizon, value in sorted(factor_horizons.items())
        },
        "strategy_summary": {
            "event_count": len(strategy_diagnostics),
            "reason_counts": dict(sorted(strategy_reasons.items())),
        },
    }


def reconstruct_result_view(
    objects: ImmutableObjectStore,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    entries = manifest.get("objects")
    if not isinstance(entries, Mapping):
        raise CompactResultError("Result Manifest object index is invalid")
    factor = read_json_object(objects, entries, "factor_summary")
    strategy_summary_value = read_json_object(objects, entries, "strategy_summary")
    diagnostics = read_json_object(objects, entries, "diagnostic_summary")
    terminal_state = read_json_object(
        objects,
        entries,
        "terminal_strategy_state",
    )
    tables = {
        kind: read_table_object(objects, entries, kind)
        for kind in RESULT_PARQUET_CONTRACTS
    }
    daily = tables["strategy_daily_observations"]
    metrics = reconstruct_strategy_metrics(
        strategy_summary_value,
        daily,
        tables["rebalance_aggregates"],
    )
    positions = tables["terminal_positions"]
    terminal_state.pop("positions_object", None)
    terminal_state["positions"] = positions
    public_manifest = copy.deepcopy(dict(manifest))
    public_manifest.pop("compatibility_objects", None)
    return {
        "manifest": public_manifest,
        "factor_evaluation": factor,
        "strategy_backtest": {
            "alpha_checksum": strategy_summary_value["alpha_checksum"],
            "initial_cash_cny": strategy_summary_value["initial_cash_cny"],
            "daily": [
                {
                    **row,
                    "cash_ratio": (
                        float(Decimal(str(row["net_cash"])) / Decimal(str(row["net_nav"])))
                        if Decimal(str(row["net_nav"])) != 0
                        else 0.0
                    ),
                }
                for row in daily
            ],
            "metrics": metrics,
            "rebalance_aggregates": tables["rebalance_aggregates"],
            "execution_aggregates": tables["execution_aggregates"],
        },
        "diagnostics": diagnostics,
        "terminal_strategy_state": terminal_state,
    }


def reconstruct_strategy_metrics(
    strategy_summary_value: Mapping[str, object],
    daily: Sequence[Mapping[str, object]],
    rebalance_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    metrics_value = strategy_summary_value.get("metrics")
    if not isinstance(metrics_value, Mapping):
        raise CompactResultError("Strategy Summary metrics are invalid")
    metrics = copy.deepcopy(dict(metrics_value))
    net_nav = [Decimal(str(item["net_nav"])) for item in daily]
    drawdown = maximum_drawdown([dict(item) for item in daily], net_nav)
    maximum_drawdown_summary = metrics.get("maximum_drawdown")
    if not isinstance(maximum_drawdown_summary, dict):
        raise CompactResultError("Maximum Drawdown summary is invalid")
    maximum_drawdown_summary["series"] = drawdown["series"]
    turnover = metrics.get("turnover")
    if not isinstance(turnover, dict):
        raise CompactResultError("Turnover summary is invalid")
    turnover["events"] = [
        {"session": str(row["session"]), "value": float(row["turnover"])}
        for row in rebalance_rows
    ]
    holdings = metrics.get("holdings_count")
    weights = metrics.get("maximum_single_name_weight")
    cash = metrics.get("cash_ratio")
    if not all(isinstance(value, dict) for value in (holdings, weights, cash)):
        raise CompactResultError("Strategy exposure summaries are invalid")
    holdings["daily"] = [int(row["holdings_count"]) for row in daily]
    weights["daily"] = [
        float(row["maximum_single_name_weight"]) for row in daily
    ]
    cash["daily"] = [
        (
            float(Decimal(str(row["net_cash"])) / Decimal(str(row["net_nav"])))
            if Decimal(str(row["net_nav"])) != 0
            else 0.0
        )
        for row in daily
    ]
    return metrics


def read_json_object(
    objects: ImmutableObjectStore,
    entries: Mapping[str, object],
    kind: str,
) -> dict[str, object]:
    entry = entries.get(kind)
    if not isinstance(entry, Mapping) or not isinstance(entry.get("sha256"), str):
        raise CompactResultError(f"Result Manifest is missing {kind}")
    value = objects.read_json(str(entry["sha256"]))
    if not isinstance(value, dict):
        raise CompactResultError(f"{kind} object is invalid")
    return value


def read_table_object(
    objects: ImmutableObjectStore,
    entries: Mapping[str, object],
    kind: str,
) -> list[dict[str, object]]:
    entry = entries.get(kind)
    if not isinstance(entry, Mapping) or not isinstance(entry.get("sha256"), str):
        raise CompactResultError(f"Result Manifest is missing {kind}")
    contract = RESULT_PARQUET_CONTRACTS[kind]
    if entry.get("writer_contract_id") != contract.identifier:
        raise CompactResultError(f"{kind} writer contract is unsupported")
    return objects.read_parquet(str(entry["sha256"]), contract).to_pylist()


def require_mapping(
    value: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise CompactResultError(f"missing calculation artifact: {key}")
    return item


def require_rows(
    value: Mapping[str, object],
    key: str,
) -> list[Mapping[str, object]]:
    rows = value.get(key)
    if not isinstance(rows, list) or not all(
        isinstance(row, Mapping) for row in rows
    ):
        raise CompactResultError(f"{key} must be a table")
    return rows


def group_by_session(
    rows: Sequence[Mapping[str, object]],
) -> defaultdict[str, list[Mapping[str, object]]]:
    grouped: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["session"])].append(row)
    return grouped


def remove_nested(value: dict[str, object], key: str, nested_key: str) -> None:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise CompactResultError(f"Strategy metric is invalid: {key}")
    nested.pop(nested_key, None)


def object_reference(entry: Mapping[str, object]) -> dict[str, object]:
    return {
        key: entry[key]
        for key in ("sha256", "bytes", "writer_contract_id")
    }
