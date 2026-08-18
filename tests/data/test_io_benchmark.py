from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from thesistrace.data.io_benchmark import (
    EXACT_IO_BUDGET_METRICS,
    BenchmarkSample,
    assert_benchmark_budgets,
    assert_long_research_qualification,
    derive_repository_budgets,
    long_research_qualification_summary,
    summarize_samples,
)


def _long_research_evidence() -> dict[str, object]:
    sample = {
        "duration_ms": 1_000,
        "peak_rss_bytes": 512 * 1024 * 1024,
        "first_checkpoint_latency_ms": 500,
        "manifest_opens": 3,
        "parquet_object_opens": 4,
        "market_parquet_scans": 4,
        "financial_parquet_scans": 0,
        "raw_financial_batch_opens": 0,
        "bytes_read": 1024,
        "rows_scanned": 12_000,
        "columns_scanned": 4,
        "process_exit_code": 0,
        "result_manifest_sha256": "a" * 64,
    }
    evidence = {
        "format": "thesistrace-long-research-qualification",
        "version": 1,
        "image": {"revision": "sha256:" + "b" * 64},
        "capacity": {
            "cpu_count": 2,
            "memory_bytes": 2 * 1024 * 1024 * 1024,
            "execution_memory_bytes": 1536 * 1024 * 1024,
            "calculation_threads": 2,
            "slot_count": 1,
        },
        "workload": {
            "formula": "cs_rank(pct_change(close_adj, 20))",
            "universe": "top3000",
            "start_date": "2010-01-04",
            "end_date": "2026-08-13",
            "generation_manifest_sha256": "c" * 64,
            "chunk_session_count": 21,
            "chunk_count": 207,
        },
        "cold": {"samples": [dict(sample) for _ in range(5)]},
        "warm": {"samples": [dict(sample) for _ in range(5)]},
        "cancellation_latency_ms": 900,
    }
    evidence["summary"] = long_research_qualification_summary(evidence)
    return evidence


def test_long_research_qualification_accepts_only_the_exact_release_workload() -> None:
    evidence = _long_research_evidence()

    qualified = assert_long_research_qualification(evidence)

    assert qualified["cold_p95_duration_ms"] == 1_000
    assert qualified["warm_p95_duration_ms"] == 1_000
    assert qualified["peak_rss_bytes"] == 512 * 1024 * 1024
    assert qualified["first_checkpoint_latency_ms"] == 500
    assert evidence["summary"] == qualified


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["workload"].update(universe="top300"), "workload"),
        (lambda value: value["cold"]["samples"].pop(), "five cold"),
        (
            lambda value: value["cold"]["samples"][4].update(duration_ms=600_001),
            "cold execution P95",
        ),
        (
            lambda value: value["warm"]["samples"][4].update(duration_ms=300_001),
            "warm execution P95",
        ),
        (
            lambda value: value["warm"]["samples"][0].update(peak_rss_bytes=1536 * 1024 * 1024 + 1),
            "peak RSS",
        ),
        (
            lambda value: value["cold"]["samples"][0].update(first_checkpoint_latency_ms=45_001),
            "first Checkpoint",
        ),
        (lambda value: value.update(cancellation_latency_ms=5_001), "cancellation"),
        (
            lambda value: value["cold"]["samples"][0].update(financial_parquet_scans=1),
            "Financial Data",
        ),
        (lambda value: value["summary"].update(cold_p95_duration_ms=0), "summary"),
    ],
)
def test_long_research_qualification_rejects_incomplete_or_over_budget_evidence(
    mutation: object,
    message: str,
) -> None:
    evidence = _long_research_evidence()
    mutation(evidence)

    with pytest.raises(AssertionError, match=message):
        assert_long_research_qualification(evidence)


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
    assert hashlib.sha256(
        (root / "benchmarks/financial-io-2010-baseline.json").read_bytes()
    ).hexdigest() == ("e302a9c03eb600748b9c97adb36ed2ad577fce8b71738482d3cdb1c6bf50fe09")
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


def test_long_research_profile_is_the_fixed_top3000_release_fixture() -> None:
    root = Path(__file__).resolve().parents[2]

    profile = json.loads((root / "benchmarks/long-research-2010-profile.json").read_bytes())

    assert profile == {
        "format": "thesistrace-long-research-profile",
        "version": 1,
        "generation_calendar_start": "2009-12-07",
        "workload_start_date": "2010-01-04",
        "workload_end_date": "2026-08-13",
        "ordinary_a_share_instrument_count": 5541,
        "execution_universe_size": 3000,
        "market_dense_session_count": 4354,
        "formula": "cs_rank(pct_change(close_adj, 20))",
        "universe": "top3000",
        "repetitions_per_phase": 5,
    }


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
