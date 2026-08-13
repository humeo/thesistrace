from __future__ import annotations

import json
from pathlib import Path

import pytest

from thesistrace.data.io_benchmark import (
    EXACT_IO_BUDGET_METRICS,
    BenchmarkSample,
    assert_benchmark_budgets,
    derive_repository_budgets,
    summarize_samples,
)


def test_benchmark_summary_records_deterministic_nearest_rank_p50_and_p95() -> None:
    samples = [
        BenchmarkSample(
            duration_ms=float(value),
            peak_memory_bytes=value * 10,
            manifest_opens=value,
            parquet_object_opens=value,
            raw_financial_batch_opens=0,
            market_parquet_scans=value,
            financial_parquet_scans=0,
            bytes_read=value * 100,
            rows_scanned=value * 1000,
            columns_scanned=value * 5,
        )
        for value in (1, 2, 3, 4, 5)
    ]

    summary = summarize_samples(samples)

    assert summary["p50"]["duration_ms"] == 3.0
    assert summary["p95"]["duration_ms"] == 5.0
    assert summary["p95"]["rows_scanned"] == 5000


def test_repository_benchmark_contract_is_full_scale_and_budgeted() -> None:
    root = Path(__file__).resolve().parents[2]
    profile = json.loads((root / "benchmarks/financial-io-2010-profile.json").read_bytes())
    baseline = json.loads((root / "benchmarks/financial-io-2010-baseline.json").read_bytes())
    budgets = json.loads((root / "benchmarks/financial-io-2010-budgets.json").read_bytes())

    assert profile == {
        "format": "thesistrace-financial-io-profile",
        "version": 1,
        "calendar_start": "2010-01-04",
        "calendar_end": "2026-08-13",
        "ordinary_a_share_instrument_count": 5541,
        "execution_universe_size": 300,
        "market_dense_session_count": 4334,
        "financial_versions_per_instrument_endpoint": 34,
        "wide_non_null_stride": 16,
        "statement_source_field_counts": {
            "income": 82,
            "balancesheet": 140,
            "cashflow": 90,
        },
        "repetitions_per_phase": 5,
    }
    assert set(budgets["scenarios"]) == {
        "descriptor",
        "price_only",
        "financial_only",
        "mixed",
        "tracking_advance",
    }
    assert baseline["profile"] == profile
    assert set(baseline["scenarios"]) == set(budgets["scenarios"])
    assert all(
        phase["sample_count"] == profile["repetitions_per_phase"]
        for scenario in baseline["scenarios"].values()
        for phase in scenario.values()
    )
    assert all(set(phases) == {"cold", "warm"} for phases in budgets["scenarios"].values())
    assert budgets == derive_repository_budgets(baseline)
    assert all(
        limits["duration_ms"]
        > baseline["scenarios"][scenario_name][phase_name]["p95"]["duration_ms"]
        and limits["peak_memory_bytes"]
        > baseline["scenarios"][scenario_name][phase_name]["p95"]["peak_memory_bytes"]
        for scenario_name, scenario in budgets["scenarios"].items()
        for phase_name, limits in scenario.items()
    )


def test_repository_budgets_gate_exact_io_and_material_time_and_memory_regressions() -> None:
    result = {
        "scenarios": {
            "descriptor": {
                "cold": {
                    "p95": {
                        "duration_ms": 999,
                        "peak_memory_bytes": 888,
                        **{metric: index for index, metric in enumerate(EXACT_IO_BUDGET_METRICS)},
                    }
                }
            }
        }
    }

    budgets = derive_repository_budgets(result)

    assert budgets["scenarios"]["descriptor"]["cold"] == {
        **{metric: index for index, metric in enumerate(EXACT_IO_BUDGET_METRICS)},
        "duration_ms": 2997,
        "peak_memory_bytes": 1776,
    }


def test_budget_failure_names_the_exact_regressed_metric() -> None:
    results = {"scenarios": {"descriptor": {"cold": {"p95": {"rows_scanned": 1}}}}}
    budgets = {"scenarios": {"descriptor": {"cold": {"rows_scanned": 0}}}}

    with pytest.raises(AssertionError, match=r"descriptor\.cold\.rows_scanned: 1 > 0"):
        assert_benchmark_budgets(results, budgets)
