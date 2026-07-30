from pathlib import Path

from thesistrace.objects import ImmutableObjectStore, canonical_json_bytes
from thesistrace.research_runs import MAX_RESULT_BUNDLE_BYTES
from thesistrace.result_objects import (
    EXECUTION_AGGREGATE_CONTRACT,
    REBALANCE_AGGREGATE_CONTRACT,
    STRATEGY_DAILY_CONTRACT,
    TERMINAL_POSITION_CONTRACT,
)


def test_production_result_writer_fits_756_sessions_and_top3000_positions(
    tmp_path: Path,
) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    sessions = [f"session-{index:04d}" for index in range(756)]
    tables = {
        "strategy_daily_observations": (
            STRATEGY_DAILY_CONTRACT,
            [
                {
                    "session": session,
                    "gross_nav": f"{10_000_000 + index}",
                    "net_nav": f"{9_999_000 + index}",
                    "benchmark_nav": f"{1 + index / 10_000:.8f}",
                    "net_cash": f"{1_000_000 + index}",
                    "transaction_cost_cny": "18.88",
                    "holdings_count": 100,
                    "maximum_single_name_weight": 0.01,
                    "upper_limit_buy_rejections": 1,
                    "lower_limit_sell_rejections": 1,
                    "suspension_rejections": 1,
                }
                for index, session in enumerate(sessions)
            ],
        ),
        "rebalance_aggregates": (
            REBALANCE_AGGREGATE_CONTRACT,
            [
                {
                    "session": session,
                    "signal_session": sessions[max(0, index - 1)],
                    "turnover": 0.25,
                    "fill_count": 100,
                    "buy_order_count": 50,
                    "sell_order_count": 50,
                }
                for index, session in enumerate(sessions)
            ],
        ),
        "execution_aggregates": (
            EXECUTION_AGGREGATE_CONTRACT,
            [
                {
                    "session": session,
                    "order_count": 100,
                    "child_order_count": 100,
                    "fill_count": 100,
                    "buy_fill_count": 50,
                    "sell_fill_count": 50,
                    "filled_notional_cny": "10000000",
                    "transaction_cost_cny": "1888",
                    "upper_limit_buy_rejections": 1,
                    "lower_limit_sell_rejections": 1,
                    "suspension_rejections": 1,
                }
                for session in sessions
            ],
        ),
        "terminal_positions": (
            TERMINAL_POSITION_CONTRACT,
            [
                {
                    "instrument_id": f"equity:{index:06d}.SZ",
                    "execution_shares": 100,
                    "adjusted_units": "100",
                    "last_adjusted_price": "10.1234",
                }
                for index in range(3_000)
            ],
        ),
    }
    entries = {
        kind: {
            "kind": kind,
            **objects.put_parquet_rows(rows, contract),
        }
        for kind, (contract, rows) in tables.items()
    }
    for kind, value in {
        "factor_summary": {"horizons": {"1": {}, "5": {}, "20": {}}},
        "strategy_summary": {"metrics": {}, "alpha_checksum": "0" * 64},
        "diagnostic_summary": {"status": "complete"},
        "terminal_strategy_state": {
            "session": sessions[-1],
            "positions_object": {
                "sha256": entries["terminal_positions"]["sha256"],
            },
        },
    }.items():
        entries[kind] = {
            "kind": kind,
            "format": "json",
            **objects.put_json(value),
        }

    manifest = {
        "id": "result_capacity",
        "research_run_id": "run_capacity",
        "objects": entries,
        "logical_bytes": {
            "payloads": sum(int(entry["bytes"]) for entry in entries.values()),
            "manifest": 0,
            "total": 0,
            "limit": MAX_RESULT_BUNDLE_BYTES,
        },
    }
    manifest_bytes = len(canonical_json_bytes(manifest))
    logical_total = sum(int(entry["bytes"]) for entry in entries.values()) + manifest_bytes

    assert len(tables["strategy_daily_observations"][1]) == 756
    assert len(tables["rebalance_aggregates"][1]) == 756
    assert len(tables["execution_aggregates"][1]) == 756
    assert len(tables["terminal_positions"][1]) == 3_000
    assert logical_total <= MAX_RESULT_BUNDLE_BYTES
