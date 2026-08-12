from __future__ import annotations

import json
import platform
import time
import tracemalloc

from thesistrace.alpha_language import alpha_language
from thesistrace.alpha_language.language import (
    MAX_EFFECTIVE_LOOKBACK,
    MAX_ESTIMATED_WORK,
    MAX_EXPRESSION_DEPTH,
    MAX_EXPRESSION_NODES,
    MAX_FORMULA_LENGTH,
)
from thesistrace.research_kernel.alpha_expression import MAX_ALPHA_RUN_ESTIMATED_WORK
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_series_execution_matrix,
    evaluate_series_execution_plan,
)

FORMULA = " + ".join("ts_mean(close_adj, 252)" for _ in range(16))
SESSION_COUNT = 5_000
MAX_UNIVERSE_INSTRUMENTS = 3_000


def run_benchmark(
    *,
    formula: str = FORMULA,
    session_count: int = SESSION_COUNT,
) -> dict[str, object]:
    inputs = {
        "price.close.adjusted": [100.0 + (index % 31) * 0.1 for index in range(session_count)],
    }

    tracemalloc.start()
    compile_started = time.perf_counter()
    compiled = alpha_language.compile(formula)
    compile_ms = (time.perf_counter() - compile_started) * 1_000
    plan = build_series_execution_plan(compiled)
    evaluate_started = time.perf_counter()
    result = evaluate_series_execution_plan(plan, inputs)
    evaluate_ms = (time.perf_counter() - evaluate_started) * 1_000
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(result) == session_count
    return {
        "benchmark": "alpha-series-plan",
        "formula": formula,
        "sessions": session_count,
        "python": platform.python_version(),
        "limits": {
            "source_characters": MAX_FORMULA_LENGTH,
            "expression_nodes": MAX_EXPRESSION_NODES,
            "expression_depth": MAX_EXPRESSION_DEPTH,
            "effective_lookback": MAX_EFFECTIVE_LOOKBACK,
            "estimated_work": MAX_ESTIMATED_WORK,
            "alpha_run_estimated_work": MAX_ALPHA_RUN_ESTIMATED_WORK,
        },
        "observed": {
            "source_characters": len(formula),
            "expression_nodes": compiled.node_count,
            "plan_nodes": len(plan.nodes),
            "effective_lookback": compiled.effective_lookback,
            "estimated_work": compiled.estimated_work,
            "compile_ms": round(compile_ms, 3),
            "evaluate_ms": round(evaluate_ms, 3),
            "peak_bytes": peak_bytes,
        },
    }


def run_maximum_shape_benchmark() -> dict[str, object]:
    compiled = alpha_language.compile("close_adj")
    plan = build_series_execution_plan(compiled)
    inputs = {
        "price.close.adjusted": [100.0 + (index % 31) * 0.1 for index in range(SESSION_COUNT)],
    }

    tracemalloc.start()
    evaluate_started = time.perf_counter()
    matrix = evaluate_series_execution_matrix(
        plan,
        (f"instrument-{index}" for index in range(MAX_UNIVERSE_INSTRUMENTS)),
        lambda _instrument_id: inputs,
        length=SESSION_COUNT,
    )
    evaluate_ms = (time.perf_counter() - evaluate_started) * 1_000
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(matrix) == MAX_UNIVERSE_INSTRUMENTS
    assert all(len(result) == SESSION_COUNT for result in matrix.values())
    return {
        "universe_instruments": MAX_UNIVERSE_INSTRUMENTS,
        "sessions": SESSION_COUNT,
        "series_points": MAX_UNIVERSE_INSTRUMENTS * SESSION_COUNT,
        "formula": "close_adj",
        "formula_work": compiled.estimated_work,
        "evaluate_ms": round(evaluate_ms, 3),
        "peak_bytes": peak_bytes,
    }


def main() -> None:
    benchmark = run_benchmark()
    benchmark["maximum_universe_date_shape"] = run_maximum_shape_benchmark()
    print(json.dumps(benchmark, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
