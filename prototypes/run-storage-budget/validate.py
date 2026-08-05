#!/usr/bin/env python3
"""THROWAWAY: prove bounded ResearchRun results and Daily Tracking caches."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.alpha import evaluate_alpha_matrix
from thesistrace.factor import (
    build_forward_labels,
    correlation_summary,
    evaluate_factor,
    mean_or_none,
)
from thesistrace.fixture import build_fixture
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.strategy import run_strategy, strategy_metrics

SESSION_COUNT = 756
POSITION_COUNT = 3000
TOP3000_COUNT = 3000
MAX_ALPHA_LOOKBACK_SESSIONS = 252
PENDING_ALPHA_SESSION_COUNT = 21
FACTOR_ROLLING_SESSION_COUNT = 504
FACTOR_HORIZONS = (1, 5, 20)
ONE_MIB = 1024 * 1024
DEFINITION = {
    "universe": "top300",
    "strategy": {
        "holdings_count": 30,
        "rebalance_interval": 5,
        "initial_cash_cny": "10000000",
        "execution": "next_open_full_fill",
    },
    "costs": {
        "commission_rate_all_in": "0.0003",
        "commission_min_cny": "5",
        "stamp_duty_sell_rate": "0.0005",
        "transfer_fee_rate": "0.00001",
    },
}


def current_factor_summary(daily: list[dict[str, object]]) -> dict[str, object]:
    return {
        "ic": correlation_summary(daily, "ic"),
        "rank_ic": correlation_summary(daily, "rank_ic"),
        "quantile_returns": {
            name: mean_or_none(
                [
                    float(day["quantile_returns"][name])
                    for day in daily
                    if day["quantile_returns"][name] is not None
                ]
            )
            for name in ("q1", "q2", "q3", "q4", "q5")
        },
        "top_bottom_return": mean_or_none(
            [
                float(day["top_bottom_return"])
                for day in daily
                if day["top_bottom_return"] is not None
            ]
        ),
    }


def compact_strategy_metrics(metrics: dict[str, object]) -> dict[str, object]:
    compact = json.loads(canonical_json_bytes(metrics))
    compact["maximum_drawdown"].pop("series")
    compact["turnover"].pop("events")
    compact["holdings_count"].pop("daily")
    compact["maximum_single_name_weight"].pop("daily")
    compact["cash_ratio"].pop("daily")
    return compact


def prove_metric_boundary() -> tuple[dict[str, object], dict[str, object]]:
    _, market = build_fixture()
    alpha = evaluate_alpha_matrix(
        market,
        expression="pct_change($close_adj, 20)",
        universe_name="top300",
        neutralization="industry",
    )
    labels = build_forward_labels(market, alpha)
    factor = evaluate_factor(labels)
    strategy = run_strategy(market, alpha, DEFINITION)

    expected_factor = {
        horizon: artifact["summary"] for horizon, artifact in factor["horizons"].items()
    }
    expected_strategy = canonical_json_bytes(strategy["metrics"])
    rejection_counts = Counter(str(item["reason"]) for item in strategy["rejections"])
    retained = {
        "factor_summary": {
            horizon: current_factor_summary(artifact["daily"])
            for horizon, artifact in factor["horizons"].items()
        },
        "strategy_daily": [
            {
                "session": row["session"],
                "gross_nav": row["gross_nav"],
                "net_nav": row["net_nav"],
                "benchmark_nav": row["benchmark_nav"],
                "net_cash": row["net_cash"],
                "holdings_count": row["holdings_count"],
                "maximum_single_name_weight": row["maximum_single_name_weight"],
            }
            for row in strategy["daily"]
        ],
        "rebalance_aggregates": [
            {"session": event["session"], "value": event["turnover"]}
            for event in strategy["rebalance_events"]
        ],
        "execution_summary": {
            "cumulative_cost": strategy["daily"][-1]["cumulative_transaction_cost"],
            "rejection_counts": dict(sorted(rejection_counts.items())),
        },
        "terminal_account": {
            "session": strategy["daily"][-1]["session"],
            "gross_cash": strategy["daily"][-1]["gross_cash"],
            "net_cash": strategy["daily"][-1]["net_cash"],
            "gross_nav": strategy["daily"][-1]["gross_nav"],
            "net_nav": strategy["daily"][-1]["net_nav"],
            "benchmark_nav": strategy["daily"][-1]["benchmark_nav"],
            "cumulative_transaction_cost": strategy["daily"][-1]["cumulative_transaction_cost"],
            "rebalance_phase": 0,
            "pending_signal_session": strategy["daily"][-1]["session"],
        },
    }
    assert set(retained) == {
        "factor_summary",
        "strategy_daily",
        "rebalance_aggregates",
        "execution_summary",
        "terminal_account",
    }
    retained = json.loads(canonical_json_bytes(retained))
    del alpha, labels, factor, strategy, market

    metric_daily = [
        {
            **row,
            "cash_ratio": float(Decimal(str(row["net_cash"])) / Decimal(str(row["net_nav"]))),
        }
        for row in retained["strategy_daily"]
    ]
    synthetic_rejections = [
        {"reason": reason}
        for reason, count in retained["execution_summary"]["rejection_counts"].items()
        for _ in range(count)
    ]
    reconstructed_strategy = strategy_metrics(
        daily=metric_daily,
        turnover_events=retained["rebalance_aggregates"],
        cumulative_cost=Decimal(str(retained["execution_summary"]["cumulative_cost"])),
        rejections=synthetic_rejections,
    )
    factor_exact = canonical_json_bytes(retained["factor_summary"]) == canonical_json_bytes(
        expected_factor
    )
    strategy_exact = canonical_json_bytes(reconstructed_strategy) == expected_strategy
    assert factor_exact
    assert strategy_exact

    result_summary = {
        "factor": retained["factor_summary"],
        "strategy": compact_strategy_metrics(reconstructed_strategy),
        "terminal_account": retained["terminal_account"],
    }
    return result_summary, {
        "factor_summary_exact": factor_exact,
        "strategy_metrics_exact": strategy_exact,
        "retained_keys": sorted(retained),
    }


def business_dates(count: int) -> list[date]:
    sessions: list[date] = []
    cursor = date(2023, 1, 2)
    while len(sessions) < count:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    return sessions


def canonical_decimals(rng: random.Random, count: int, exponent: int) -> list[str]:
    return [
        f"{rng.randrange(10**32, 10**33) * 10 + rng.randrange(1, 10)}e{exponent:+d}"
        for _ in range(count)
    ]


def high_entropy_tables() -> dict[str, pa.Table]:
    rng = random.Random(20260730)
    sessions = business_dates(SESSION_COUNT)
    signal_sessions = [sessions[max(index - 1, 0)] for index in range(SESSION_COUNT)]

    strategy_daily = pa.table(
        {
            "trade_date": pa.array(sessions, type=pa.date32()),
            "gross_nav_canonical": canonical_decimals(rng, SESSION_COUNT, -26),
            "net_nav_canonical": canonical_decimals(rng, SESSION_COUNT, -26),
            "benchmark_nav_canonical": canonical_decimals(rng, SESSION_COUNT, -26),
            "net_cash_canonical": canonical_decimals(rng, SESSION_COUNT, -28),
            "holdings_count": pa.array(
                [rng.randrange(1, POSITION_COUNT + 1) for _ in sessions],
                type=pa.uint16(),
            ),
            "maximum_single_name_weight": [0.01 + rng.random() * 0.19 for _ in sessions],
        }
    )
    rebalance_summary = pa.table(
        {
            "execution_date": pa.array(sessions, type=pa.date32()),
            "signal_date": pa.array(signal_sessions, type=pa.date32()),
            "before_holdings_count": pa.array(
                [rng.randrange(POSITION_COUNT + 1) for _ in sessions],
                type=pa.uint16(),
            ),
            "target_holdings_count": pa.array(
                [rng.randrange(1, 101) for _ in sessions], type=pa.uint16()
            ),
            "after_holdings_count": pa.array(
                [rng.randrange(1, POSITION_COUNT + 1) for _ in sessions],
                type=pa.uint16(),
            ),
            "buy_order_count": pa.array(
                [rng.randrange(POSITION_COUNT + 1) for _ in sessions],
                type=pa.uint16(),
            ),
            "sell_order_count": pa.array(
                [rng.randrange(POSITION_COUNT + 1) for _ in sessions],
                type=pa.uint16(),
            ),
            "buy_notional_canonical": canonical_decimals(rng, SESSION_COUNT, -27),
            "sell_notional_canonical": canonical_decimals(rng, SESSION_COUNT, -27),
            "turnover": [rng.random() for _ in sessions],
        }
    )
    execution_daily = pa.table(
        {
            "trade_date": pa.array(sessions, type=pa.date32()),
            "commission_canonical": canonical_decimals(rng, SESSION_COUNT, -31),
            "stamp_tax_canonical": canonical_decimals(rng, SESSION_COUNT, -31),
            "transfer_fee_canonical": canonical_decimals(rng, SESSION_COUNT, -32),
            "upper_limit_buy_rejections": pa.array(
                [rng.randrange(101) for _ in sessions], type=pa.uint16()
            ),
            "lower_limit_sell_rejections": pa.array(
                [rng.randrange(101) for _ in sessions], type=pa.uint16()
            ),
            "suspension_rejections": pa.array(
                [rng.randrange(101) for _ in sessions], type=pa.uint16()
            ),
        }
    )
    terminal_positions = pa.table(
        {
            "instrument_id": [
                f"equity:{hashlib.sha256(f'instrument:{index}'.encode()).hexdigest()[:12]}.SZ"
                for index in range(POSITION_COUNT)
            ],
            "execution_shares": pa.array(
                [rng.randrange(100, 2_000_001) for _ in range(POSITION_COUNT)],
                type=pa.int64(),
            ),
            "adjusted_units_canonical": canonical_decimals(rng, POSITION_COUNT, -28),
            "last_adjusted_price_canonical": canonical_decimals(rng, POSITION_COUNT, -31),
        }
    )
    return {
        "strategy_daily": strategy_daily,
        "rebalance_summary": rebalance_summary,
        "execution_daily": execution_daily,
        "terminal_positions": terminal_positions,
    }


def daily_tracking_cache_tables() -> dict[str, pa.Table]:
    rng = random.Random(20260731)
    factor_sessions = business_dates(FACTOR_ROLLING_SESSION_COUNT)
    pending_sessions = factor_sessions[-PENDING_ALPHA_SESSION_COUNT:]
    instruments = [
        f"equity:{hashlib.sha256(f'tracked-instrument:{index}'.encode()).hexdigest()[:12]}.SZ"
        for index in range(TOP3000_COUNT)
    ]
    pending_rows = PENDING_ALPHA_SESSION_COUNT * TOP3000_COUNT
    aggregate_rows = FACTOR_ROLLING_SESSION_COUNT * len(FACTOR_HORIZONS)

    pending_alpha = pa.table(
        {
            "signal_date": pa.array(
                [
                    session
                    for session in pending_sessions
                    for _ in range(TOP3000_COUNT)
                ],
                type=pa.date32(),
            ),
            "instrument_id": instruments * PENDING_ALPHA_SESSION_COUNT,
            "final_alpha_binary64": pa.array(
                [rng.uniform(-5.0, 5.0) for _ in range(pending_rows)],
                type=pa.float64(),
            ),
        }
    )
    aggregate_dates = [
        session
        for session in factor_sessions
        for _ in FACTOR_HORIZONS
    ]
    rolling_factor_daily = pa.table(
        {
            "signal_date": pa.array(aggregate_dates, type=pa.date32()),
            "horizon_sessions": pa.array(
                list(FACTOR_HORIZONS) * FACTOR_ROLLING_SESSION_COUNT,
                type=pa.uint8(),
            ),
            "status": ["valid"] * aggregate_rows,
            "sample_count": pa.array(
                [rng.randrange(30, TOP3000_COUNT + 1) for _ in range(aggregate_rows)],
                type=pa.uint16(),
            ),
            "ic_binary64": pa.array(
                [rng.uniform(-1.0, 1.0) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "rank_ic_binary64": pa.array(
                [rng.uniform(-1.0, 1.0) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "q1_return_binary64": pa.array(
                [rng.uniform(-0.2, 0.2) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "q2_return_binary64": pa.array(
                [rng.uniform(-0.2, 0.2) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "q3_return_binary64": pa.array(
                [rng.uniform(-0.2, 0.2) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "q4_return_binary64": pa.array(
                [rng.uniform(-0.2, 0.2) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "q5_return_binary64": pa.array(
                [rng.uniform(-0.2, 0.2) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
            "top_bottom_return_binary64": pa.array(
                [rng.uniform(-0.4, 0.4) for _ in range(aggregate_rows)],
                type=pa.float64(),
            ),
        }
    )
    return {
        "pending_final_alpha": pending_alpha,
        "rolling_factor_daily_aggregates": rolling_factor_daily,
    }


def write_zstd(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=3,
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
        data_page_version="2.0",
    )
    metadata = pq.ParquetFile(path).metadata
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        assert all(
            row_group.column(index).compression == "ZSTD" for index in range(row_group.num_columns)
        )


def measure_layout(
    root: Path,
    tables: dict[str, pa.Table],
    result_summary: dict[str, object],
    *,
    daily: bool,
) -> dict[str, int]:
    parquet_paths: list[Path] = []
    for name, table in tables.items():
        if daily and name != "terminal_positions":
            for index, session in enumerate(table.column(0).to_pylist()):
                path = root / name / f"{session.isoformat()}.parquet"
                write_zstd(path, table.slice(index, 1))
                parquet_paths.append(path)
        else:
            path = root / f"{name}.parquet"
            write_zstd(path, table)
            parquet_paths.append(path)

    summary_path = root / "result_summary.json"
    summary_path.write_bytes(canonical_json_bytes(result_summary))
    manifest_path = root / "result_manifest.json"
    manifest_path.write_bytes(
        canonical_json_bytes(
            {
                "layout": "daily" if daily else "one_file_per_table",
                "objects": [
                    {
                        "path": str(path.relative_to(root)),
                        "bytes": path.stat().st_size,
                    }
                    for path in [*parquet_paths, summary_path]
                ],
            }
        )
    )
    files = [path for path in root.rglob("*") if path.is_file()]
    return {
        "bytes": sum(path.stat().st_size for path in files),
        "file_count": len(files),
        "parquet_file_count": len(parquet_paths),
    }


def measure_daily_tracking_cache(
    root: Path,
    tables: dict[str, pa.Table],
) -> dict[str, object]:
    pending_table = tables["pending_final_alpha"]
    pending_paths: list[Path] = []
    for index in range(PENDING_ALPHA_SESSION_COUNT):
        offset = index * TOP3000_COUNT
        signal_date = pending_table.column("signal_date")[offset].as_py()
        path = (
            root
            / "pending_alpha"
            / f"signal_date={signal_date.isoformat()}.parquet"
        )
        write_zstd(path, pending_table.slice(offset, TOP3000_COUNT))
        pending_paths.append(path)

    factor_path = root / "factor_observations.parquet"
    write_zstd(factor_path, tables["rolling_factor_daily_aggregates"])
    parquet_paths = [*pending_paths, factor_path]

    basis_path = root / "basis.json"
    basis_path.write_bytes(
        canonical_json_bytes(
            {
                "kind": "daily_tracking_working_cache",
                "authoritative": False,
                "rebuildable": True,
                "daily_track_id": "track_" + "d" * 20,
                "generation_id": "generation_" + "e" * 20,
                "basis_checkpoint_id": "checkpoint_" + "a" * 20,
                "target_dataset_release_id": "release_" + "f" * 20,
                "definition_hash": "b" * 64,
                "kernel_version": "kernel-v1",
                "numeric_execution_contract": "numeric-v1",
                "max_alpha_lookback_sessions": MAX_ALPHA_LOOKBACK_SESSIONS,
                "pending_alpha_session_limit": PENDING_ALPHA_SESSION_COUNT,
                "factor_rolling_session_limit": FACTOR_ROLLING_SESSION_COUNT,
                "factor_horizons": list(FACTOR_HORIZONS),
                "objects": [
                    {
                        "path": str(path.relative_to(root)),
                        "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in parquet_paths
                ],
            }
        )
    )
    files = [path for path in root.rglob("*") if path.is_file()]
    return {
        "bytes": sum(path.stat().st_size for path in files),
        "file_count": len(files),
        "parquet_file_count": len(parquet_paths),
        "objects": {
            "pending_final_alpha": {
                "bytes": sum(path.stat().st_size for path in pending_paths),
                "rows": pending_table.num_rows,
                "file_count": len(pending_paths),
                "max_partition_bytes": max(
                    path.stat().st_size for path in pending_paths
                ),
            },
            "rolling_factor_daily_aggregates": {
                "bytes": factor_path.stat().st_size,
                "rows": tables["rolling_factor_daily_aggregates"].num_rows,
                "file_count": 1,
            },
        },
        "cache_basis_bytes": basis_path.stat().st_size,
        "normal_advance_write_upper_bound_bytes": (
            max(path.stat().st_size for path in pending_paths)
            + factor_path.stat().st_size
            + basis_path.stat().st_size
        ),
    }


def main() -> int:
    result_summary, metric_result = prove_metric_boundary()
    tables = high_entropy_tables()
    assert {name: table.num_rows for name, table in tables.items()} == {
        "strategy_daily": SESSION_COUNT,
        "rebalance_summary": SESSION_COUNT,
        "execution_daily": SESSION_COUNT,
        "terminal_positions": POSITION_COUNT,
    }
    cache_tables = daily_tracking_cache_tables()
    assert {
        name: table.num_rows for name, table in cache_tables.items()
    } == {
        "pending_final_alpha": PENDING_ALPHA_SESSION_COUNT * TOP3000_COUNT,
        "rolling_factor_daily_aggregates": (
            FACTOR_ROLLING_SESSION_COUNT * len(FACTOR_HORIZONS)
        ),
    }

    with TemporaryDirectory(prefix="thesistrace-run-budget-") as temporary:
        root = Path(temporary)
        bounded = measure_layout(
            root / "one-file-per-table",
            tables,
            result_summary,
            daily=False,
        )
        partitioned = measure_layout(
            root / "daily-partitioned",
            tables,
            result_summary,
            daily=True,
        )
        daily_tracking_cache = measure_daily_tracking_cache(
            root / "daily-tracking-cache",
            cache_tables,
        )

    assert bounded["bytes"] < ONE_MIB
    assert bounded["file_count"] == 6
    assert partitioned["bytes"] >= ONE_MIB
    assert partitioned["file_count"] == SESSION_COUNT * 3 + 3
    assert daily_tracking_cache["file_count"] == PENDING_ALPHA_SESSION_COUNT + 2
    assert daily_tracking_cache["parquet_file_count"] == PENDING_ALPHA_SESSION_COUNT + 1
    assert (
        daily_tracking_cache["objects"]["pending_final_alpha"]["file_count"]
        == PENDING_ALPHA_SESSION_COUNT
    )
    assert daily_tracking_cache["objects"]["rolling_factor_daily_aggregates"][
        "file_count"
    ] == 1
    assert (
        daily_tracking_cache["normal_advance_write_upper_bound_bytes"]
        < daily_tracking_cache["bytes"]
    )
    print(
        json.dumps(
            {
                "metric_boundary": metric_result,
                "storage_budget": {
                    "encoding": "ADR-0109 canonical decimal strings",
                    "sessions": SESSION_COUNT,
                    "daily_rebalances": SESSION_COUNT,
                    "daily_execution_aggregates": SESSION_COUNT,
                    "terminal_positions": POSITION_COUNT,
                    "one_file_per_table": bounded,
                    "daily_partitioned": partitioned,
                    "limit_bytes": ONE_MIB,
                },
                "daily_tracking_cache": {
                    "budget_scope": "separate_from_research_run",
                    "authoritative": False,
                    "rebuildable": True,
                    "top_n": TOP3000_COUNT,
                    "alpha_lookback": {
                        "max_sessions": MAX_ALPHA_LOOKBACK_SESSIONS,
                        "persisted_lookback_history_rows": 0,
                    },
                    "pending_final_alpha": {
                        "max_signal_sessions": PENDING_ALPHA_SESSION_COUNT,
                        "rows": (
                            PENDING_ALPHA_SESSION_COUNT * TOP3000_COUNT
                        ),
                    },
                    "rolling_factor_daily_aggregates": {
                        "max_signal_sessions": FACTOR_ROLLING_SESSION_COUNT,
                        "horizons": list(FACTOR_HORIZONS),
                        "rows": (
                            FACTOR_ROLLING_SESSION_COUNT
                            * len(FACTOR_HORIZONS)
                        ),
                    },
                    "persistent_stock_level_label_rows": 0,
                    "research_run_factor_daily_curve_rows": 0,
                    "layout": daily_tracking_cache,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    print("VALIDATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
