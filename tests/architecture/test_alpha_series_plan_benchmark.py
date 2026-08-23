from __future__ import annotations

import json
import sys
from pathlib import Path

from thesistrace.alpha_language.language import (
    MAX_EFFECTIVE_LOOKBACK,
    MAX_ESTIMATED_WORK,
    MAX_EXPRESSION_DEPTH,
    MAX_EXPRESSION_NODES,
    MAX_FORMULA_LENGTH,
)
from thesistrace.research_kernel.alpha_expression import MAX_ALPHA_RUN_ESTIMATED_WORK

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_alpha_series_plan import (  # noqa: E402
    run_benchmark,
    run_maximum_shape_benchmark,
)


def test_committed_alpha_series_plan_benchmark_fixes_admission_limits() -> None:
    benchmark = json.loads(
        (ROOT / "docs" / "research" / "alpha-series-plan-benchmark.json").read_text()
    )

    assert benchmark["benchmark"] == "alpha-series-plan"
    assert benchmark["sessions"] == 5_000
    assert benchmark["limits"] == {
        "source_characters": MAX_FORMULA_LENGTH,
        "expression_nodes": MAX_EXPRESSION_NODES,
        "expression_depth": MAX_EXPRESSION_DEPTH,
        "effective_lookback": MAX_EFFECTIVE_LOOKBACK,
        "estimated_work": MAX_ESTIMATED_WORK,
        "alpha_run_estimated_work": MAX_ALPHA_RUN_ESTIMATED_WORK,
    }
    observed = benchmark["observed"]
    assert observed["plan_nodes"] == observed["expression_nodes"]
    assert observed["source_characters"] <= benchmark["limits"]["source_characters"]
    assert observed["expression_nodes"] <= benchmark["limits"]["expression_nodes"]
    assert observed["effective_lookback"] <= benchmark["limits"]["effective_lookback"]
    assert observed["estimated_work"] <= benchmark["limits"]["estimated_work"]
    assert observed["estimated_work"] == benchmark["limits"]["estimated_work"] - 1
    assert observed["compile_ms"] > 0
    assert observed["evaluate_ms"] > 0
    assert observed["peak_bytes"] > 0
    maximum_shape = benchmark["maximum_universe_date_shape"]
    assert maximum_shape["universe_instruments"] == 3_000
    assert maximum_shape["sessions"] == 5_000
    assert maximum_shape["series_points"] == 15_000_000
    assert maximum_shape["formula_work"] == 1
    assert maximum_shape["series_points"] == MAX_ALPHA_RUN_ESTIMATED_WORK


def test_alpha_series_plan_has_an_executable_performance_regression_gate() -> None:
    benchmark = run_benchmark(
        formula=" + ".join("ts_mean(close, 64)" for _ in range(4)),
        session_count=1_000,
    )
    observed = benchmark["observed"]

    assert observed["compile_ms"] < 250
    assert observed["evaluate_ms"] < 2_000
    assert observed["peak_bytes"] < 20_000_000


def test_maximum_universe_date_shape_has_an_executable_memory_gate() -> None:
    observed = run_maximum_shape_benchmark()

    assert observed["evaluate_ms"] > 0
    assert observed["peak_bytes"] < 200_000_000
