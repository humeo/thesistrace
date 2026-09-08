"""Deterministic, in-memory experiments; never opens Product State or suppliers.

Run with: uv run --project apps/core python \
  .scratch/compute-speed-audit-2026-09-08/benchmark.py

Candidates are scoped to this process. No production implementation is edited.
Arrow table creation, output comparison, and profiling are outside timed samples.
"""

from __future__ import annotations

import cProfile
import gc
import hashlib
import json
import os
import platform
import pstats
import time
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from unittest.mock import patch

import numpy as np
import pyarrow as pa

from thesistrace.alpha_language import alpha_language
from thesistrace.data.columnar_series import ColumnarResearchData
from thesistrace.research_kernel import strategy as strategy_module
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix,
    evaluate_columnar_alpha_matrix,
)
from thesistrace.research_kernel.factor import (
    HORIZONS,
    affected_label_sessions,
    build_forward_labels,
    evaluate_factor,
    prepare_columnar_forward_labels,
)
from thesistrace.research_kernel.kernel_run import RunInput, StrategyRunInput
from thesistrace.research_kernel.numeric import NUMERIC_CONTRACT_ID
from thesistrace.research_kernel.research_chunks import (
    AlphaFactorExecutionBinding,
    empty_research_continuation,
    execute_research_chunk,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_columnar_execution_matrix,
)

HERE = Path(__file__).resolve().parent
NOOP = lambda: None
REPETITIONS = 3


def fixture(stock_count=3000, session_count=85):
    days = []
    day = date(2025, 1, 2)
    while len(days) < session_count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    sessions = tuple(days)
    ids = tuple(f"equity:{index:06d}.SH" for index in range(stock_count))
    rng = np.random.default_rng(20260908)
    prices = np.round(
        (10.0 + np.arange(stock_count)[None, :] % 91)
        * np.cumprod(1 + rng.normal(0, 0.01, (session_count, stock_count)), axis=0),
        4,
    )
    decimals = pa.array(
        [Decimal(f"{value:.4f}") for value in prices.ravel()],
        type=pa.decimal128(20, 4),
    )
    coords = {
        "session": pa.array(np.repeat(sessions, stock_count)),
        "instrument_id": pa.array(np.tile(ids, session_count)),
    }
    empty = pa.table(
        {
            "session": pa.array([], type=pa.string()),
            "instrument_id": pa.array([], type=pa.string()),
            "sw_l1_id": pa.array([], type=pa.string()),
        }
    )
    return ColumnarResearchData(
        sessions=sessions,
        _instruments=pa.table(
            {
                "instrument_id": ids,
                "board": ["main"] * stock_count,
                "listed_to": [""] * stock_count,
            }
        ),
        _eod_prices=pa.table(
            {
                "session_date": coords["session"],
                "instrument_id": coords["instrument_id"],
                "open_raw": decimals,
                "open_adj": decimals,
                "close_adj": decimals,
                "turnover_amount_cny": pa.array([Decimal("1000000")] * len(decimals)),
            }
        ),
        _universes=pa.table(
            {"session": sessions, "instrument_ids": [ids] * len(sessions)}
        ),
        _trading_states=pa.table({**coords, "state": ["normal"] * len(decimals)}),
        _price_limits=pa.table(
            {
                **coords,
                "upper": pa.array([Decimal("1000000")] * len(decimals)),
                "lower": pa.array([Decimal("0.01")] * len(decimals)),
            }
        ),
        _industries=empty,
        _financial_values=None,
        _field_columns={"price.close.adjusted": "close_adj"},
    )


def digest(value):
    if isinstance(value, np.ndarray):
        normalized = value.copy()
        normalized[np.isnan(normalized)] = np.nan
        return hashlib.sha256(normalized.tobytes()).hexdigest()
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def compare(name, factories):
    samples = {key: [] for key in factories}
    cpu_samples = {key: [] for key in factories}
    phases = {key: [] for key in factories}
    reference = None
    expected_digest = None
    for repetition in range(REPETITIONS):
        names = list(factories)
        if repetition % 2:
            names.reverse()
        for variant in names:
            operation = factories[variant]()
            gc.collect()
            cpu_start = time.process_time()
            started = time.perf_counter()
            value, timing = operation()
            elapsed = time.perf_counter() - started
            cpu_elapsed = time.process_time() - cpu_start
            value_digest = digest(value)
            if expected_digest is None:
                reference, expected_digest = value, value_digest
            if isinstance(value, np.ndarray):
                np.testing.assert_array_equal(value, reference, strict=True)
            else:
                assert value == reference, f"{name}/{variant} output differs"
            assert value_digest == expected_digest, f"{name}/{variant} bytes differ"
            samples[variant].append(elapsed)
            cpu_samples[variant].append(cpu_elapsed)
            phases[variant].append(timing)
            print(
                json.dumps(
                    {
                        "experiment": name,
                        "variant": variant,
                        "repetition": repetition,
                        "seconds": elapsed,
                        "exact_equal": True,
                    }
                ),
                flush=True,
            )
    return {
        "samples_seconds": samples,
        "median_seconds": {key: median(times) for key, times in samples.items()},
        "cpu_samples_seconds": cpu_samples,
        "phase_seconds": phases,
        "exact_equal": True,
        "sha256": expected_digest,
    }


def alpha_operation(data, columnar):
    compiled = alpha_language.compile("rank(pct_change(close, 20))")

    def operation():
        if columnar:
            value = evaluate_columnar_alpha_matrix(
                data,
                compiled_alpha=compiled,
                neutralization="none",
                cancellation_check=NOOP,
            )
        else:
            value = evaluate_alpha_matrix(
                data, compiled_alpha=compiled, neutralization="none"
            )
        return value, {}

    return operation


def factor_operation(data, matrix, columnar):
    selected = {
        h: affected_label_sessions(data.sessions, [data.sessions[-1]], h)
        for h in HORIZONS
    }

    def operation():
        if columnar:
            labels = prepare_columnar_forward_labels(data, cancellation_check=NOOP)
            result = labels.factor_days_by_horizon(
                matrix,
                signal_sessions_by_horizon=selected,
                cancellation_check=NOOP,
            )
        else:
            result = {}
            for horizon, sessions in selected.items():
                labels = build_forward_labels(
                    data, matrix, signal_sessions=sessions, horizons=(horizon,)
                )
                result[str(horizon)] = evaluate_factor(labels)["horizons"][
                    str(horizon)
                ]["daily"]
        return result, {}

    return operation


def chunk_operation(data, kind, float_rank=False):
    compiled = alpha_language.compile("rank(pct_change(close, 20))")
    strategy = (
        None
        if kind == "factor_evaluation"
        else StrategyRunInput(
            holdings_count=10,
            rebalance_interval=5,
            initial_cash_cny="10000000",
            commission_rate_all_in="0.0003",
            commission_min_cny="5",
            stamp_duty_sell_rate="0.0005",
            transfer_fee_rate="0.00001",
        )
    )
    run_input = RunInput(
        research_data=data,
        alpha_expression=compiled.expression,
        field_bindings={v: k for k, v in compiled.field_ids_by_identifier.items()},
        effective_alpha_lookback=compiled.effective_lookback,
        universe="top3000",
        neutralization="none",
        research_kind=kind,
        strategy=strategy,
        research_start_session=data.sessions[21],
        research_end_session=data.sessions[-1],
    )
    binding = AlphaFactorExecutionBinding.from_run_input(
        run_input,
        data_generation_id="audit-only-synthetic",
        numeric_execution_contract=NUMERIC_CONTRACT_ID,
        semantic_versions={"kernel": "audit-only-current-code"},
    )

    def calculate():
        started = time.perf_counter()
        labels = prepare_columnar_forward_labels(data, cancellation_check=NOOP)
        prepare_seconds = time.perf_counter() - started
        result = execute_research_chunk(
            run_input=run_input,
            binding=binding,
            research_data=data,
            forward_labels=labels,
            research_sessions=data.sessions[21:],
            final_chunk=True,
            continuation=empty_research_continuation(kind),
            cancellation_check=NOOP,
        )
        return {
            "continuation": result.continuation,
            "observations": list(result.strategy_daily_observations),
            "final_values": result.final_values,
        }, {"prepare_labels": prepare_seconds, **result.phase_seconds}

    def operation():
        if float_rank:
            with patch.object(
                strategy_module,
                "_alpha_rank_key",
                lambda row: (-float(row["value"]), str(row["instrument_id"])),
            ):
                return calculate()
        return calculate()

    return operation


def deduplicated_plan(plan):
    nodes, seen, remap = [], {}, {}
    for index, node in enumerate(plan.nodes):
        mapped = replace(node, inputs=tuple(remap[value] for value in node.inputs))
        key = (mapped, type(mapped.value))
        if key not in seen:
            seen[key] = len(nodes)
            nodes.append(mapped)
        remap[index] = seen[key]
    return replace(plan, nodes=tuple(nodes), root=remap[plan.root])


def profile(name, operation):
    profiler = cProfile.Profile()
    profiler.runcall(operation)
    profiler.dump_stats(str(HERE / f"{name}.pstats"))
    with (HERE / f"{name}-profile.txt").open("w") as output:
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats(
            "cumulative"
        ).print_stats(35)


def main():
    data = fixture()
    tracking_data = data.slice_sessions(data.sessions[-22:])
    report = {
        "description": "Synthetic in-memory actual-kernel audit; no end-to-end Worker or storage claim",
        "stock_count": 3000,
        "research_sessions": 64,
        "context_sessions": 21,
        "repetitions": REPETITIONS,
        "seed": 20260908,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pyarrow": pa.__version__,
        "host_load_start": os.getloadavg(),
        "experiments": {},
    }

    def save(name, result):
        report["experiments"][name] = result
        (HERE / "results.json").write_text(json.dumps(report, indent=2) + "\n")

    save(
        "tracking_alpha_22_sessions",
        compare(
            "tracking_alpha_22_sessions",
            {
                "current_row": lambda: alpha_operation(replace(tracking_data), False),
                "existing_columnar": lambda: alpha_operation(
                    replace(tracking_data), True
                ),
            },
        ),
    )
    matrix, _ = alpha_operation(replace(data), True)()
    save(
        "tracking_factor_1_new_session",
        compare(
            "tracking_factor_1_new_session",
            {
                "current_row": lambda: factor_operation(
                    replace(tracking_data), matrix, False
                ),
                "existing_columnar": lambda: factor_operation(
                    replace(tracking_data), matrix, True
                ),
            },
        ),
    )
    save(
        "factor_evaluation_chunk",
        compare(
            "factor_evaluation_chunk",
            {
                "current": lambda: chunk_operation(replace(data), "factor_evaluation"),
            },
        ),
    )
    save(
        "strategy_backtest_chunk",
        compare(
            "strategy_backtest_chunk",
            {
                "current": lambda: chunk_operation(replace(data), "strategy_backtest"),
                "float_score_ranking": lambda: chunk_operation(
                    replace(data), "strategy_backtest", True
                ),
            },
        ),
    )
    small = fixture(300, 85)
    ids = tuple(small.instruments)
    fields = small.numeric_field_matrices(("price.close.adjusted",), ids)
    compiled = alpha_language.compile(" + ".join(["rank(ts_mean(close, 20))"] * 8))
    original = build_series_execution_plan(compiled)
    shared = deduplicated_plan(original)

    def series_operation(plan):
        return lambda: (
            evaluate_columnar_execution_matrix(
                plan,
                ids,
                small.sessions,
                fields,
                small.universe_members,
                cancellation_check=NOOP,
            ),
            {},
        )

    save(
        "repeated_alpha_subexpressions",
        {
            "stocks": 300,
            "sessions": 85,
            "formula": compiled.source
            if hasattr(compiled, "source")
            else "8 x rank(ts_mean(close, 20)) added in the original order",
            "nodes_before": len(original.nodes),
            "nodes_after": len(shared.nodes),
            **compare(
                "repeated_alpha_subexpressions",
                {
                    "current_tree": lambda: series_operation(original),
                    "deduplicated_dag": lambda: series_operation(shared),
                },
            ),
        },
    )
    profile("tracking-alpha", alpha_operation(replace(tracking_data), False))
    profile("tracking-factor", factor_operation(replace(tracking_data), matrix, False))
    profile("research-factor", chunk_operation(replace(data), "factor_evaluation"))
    profile("research-strategy", chunk_operation(replace(data), "strategy_backtest"))
    report["host_load_end"] = os.getloadavg()
    (HERE / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
