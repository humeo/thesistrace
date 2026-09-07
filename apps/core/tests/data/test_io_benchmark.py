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
    is_research_execution_child_started_event,
    long_research_qualification_outcome,
    long_research_qualification_summary,
    long_research_sample_qualification,
    summarize_samples,
)
from thesistrace.product_state import PRODUCT_STATE_COUNT_NAMES


def _long_research_evidence() -> dict[str, object]:
    empty_state = {name: 0 for name in PRODUCT_STATE_COUNT_NAMES}

    def sample(research_kind: str, phase: str, index: int) -> dict[str, object]:
        strategy = research_kind == "strategy_backtest"
        return {
            "research_kind": research_kind,
            "phase": phase,
            "index": index,
            "run_id": f"run-{research_kind}-{phase}-{index}",
            "attempt_id": f"attempt-{research_kind}-{phase}-{index}",
            "duration_ms": 1_000,
            "admission_duration_ms": 10,
            "attempt_duration_ms": 990,
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
            "worker_exit_code": 0,
            "result_manifest_sha256": "a" * 64,
            "generation_manifest_sha256": "c" * 64,
            "chunk_session_count": 21,
            "chunk_count": 207,
            "factor_summary_sha256": "f" * 64,
            "result_object_names": (
                [
                    "factor_summary",
                    "strategy_daily_observations",
                    "strategy_summary",
                    "terminal_strategy_state",
                ]
                if strategy
                else ["factor_summary"]
            ),
            "result_payload_names": (
                [
                    "factor_summary",
                    "strategy_daily_observations",
                    "strategy_daily_observations.part-000000",
                    "strategy_summary",
                    "terminal_positions",
                    "terminal_positions.part-000000",
                    "terminal_strategy_state",
                ]
                if strategy
                else ["factor_summary"]
            ),
            "phase_timings_seconds": {
                "data_read": 1.0,
                "calculation": 2.0,
                "input": 0.1,
                "alpha_and_pending": 0.4,
                "factor": 0.5,
                "strategy": 0.5 if strategy else 0.0,
                "finalize": 0.1,
                "checkpoint_commit": 0.2,
            },
            "strategy_continuation_present": strategy,
            "strategy_observation_count": 4_000 if strategy else 0,
            "fresh_product_state_verified": True,
            "fresh_product_state_counts": dict(empty_state),
            "checkpoint_count_after_success": 0,
            "active_pin_count_after_success": 0,
        }

    def cancellation(research_kind: str) -> dict[str, object]:
        return {
            "research_kind": research_kind,
            "status": "cancelled",
            "cancellation_latency_ms": 900,
            "worker_exit_code": 0,
            "child_exit_code": 0,
            "child_acknowledged": False,
            "result_manifest_sha256": None,
            "checkpoint_count": 0,
            "active_pin_count": 0,
            "fresh_product_state_verified": True,
            "fresh_product_state_counts": dict(empty_state),
        }

    evidence = {
        "format": "thesistrace-long-research-qualification",
        "version": 2,
        "image": {"revision": "sha256:" + "b" * 64},
        "capacity": {
            "cpu_count": 2,
            "memory_bytes": 2 * 1024 * 1024 * 1024,
            "execution_memory_bytes": 1536 * 1024 * 1024,
            "calculation_threads": 2,
            "slot_count": 1,
        },
        "workload": {
            "formula": "rank(pct_change(close, 20))",
            "universe": "top3000",
            "start_date": "2010-01-04",
            "end_date": "2026-08-13",
            "generation_manifest_sha256": "c" * 64,
            "chunk_session_count": 21,
            "chunk_count": 207,
        },
        "warm_preload": {
            "generation_manifest_sha256": "c" * 64,
            "market_parquet_scans": 4,
            "product_state_before": dict(empty_state),
            "product_state_after": dict(empty_state),
        },
        "research_kinds": {
            research_kind: {
                "cold": {"samples": [sample(research_kind, "cold", index) for index in range(5)]},
                "warm": {"samples": [sample(research_kind, "warm", index) for index in range(5)]},
                "cancellation": cancellation(research_kind),
            }
            for research_kind in ("factor_evaluation", "strategy_backtest")
        },
        "scientific_equivalence": {
            "factor_summary_sha256": "f" * 64,
            "sample_count": 20,
        },
    }
    evidence["summary"] = long_research_qualification_summary(evidence)
    return evidence


def _qualification_sample(
    evidence: dict[str, object],
    research_kind: str,
    phase: str,
    index: int,
) -> dict[str, object]:
    return evidence["research_kinds"][research_kind][phase]["samples"][index]


def _qualification_cancellation(
    evidence: dict[str, object], research_kind: str
) -> dict[str, object]:
    return evidence["research_kinds"][research_kind]["cancellation"]


def test_long_research_qualification_accepts_only_the_exact_release_workload() -> None:
    evidence = _long_research_evidence()

    qualified = assert_long_research_qualification(evidence)

    assert qualified["factor_evaluation"]["cold_max_duration_ms"] == 1_000
    assert qualified["strategy_backtest"]["warm_max_duration_ms"] == 1_000
    assert qualified["factor_evaluation"]["peak_rss_bytes"] == 512 * 1024 * 1024
    assert qualified["strategy_backtest"]["first_checkpoint_latency_ms"] == 500
    assert evidence["summary"] == qualified


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["workload"].update(universe="top300"), "workload"),
        (
            lambda value: value["research_kinds"]["factor_evaluation"]["cold"]["samples"].pop(),
            "five cold",
        ),
        (
            lambda value: _qualification_sample(value, "factor_evaluation", "cold", 4).update(
                duration_ms=600_001
            ),
            "factor_evaluation cold sample 4 exceeds ten minutes",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "warm", 4).update(
                duration_ms=300_001
            ),
            "strategy_backtest warm sample 4 exceeds five minutes",
        ),
        (
            lambda value: _qualification_sample(value, "factor_evaluation", "warm", 0).update(
                peak_rss_bytes=1536 * 1024 * 1024 + 1
            ),
            "factor_evaluation warm sample 0 exceeds the 1.5 GiB execution budget",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "cold", 0).update(
                first_checkpoint_latency_ms=45_001
            ),
            "strategy_backtest cold sample 0 first Checkpoint exceeds 45 seconds",
        ),
        (
            lambda value: _qualification_cancellation(value, "factor_evaluation").update(
                cancellation_latency_ms=5_001
            ),
            "cancellation",
        ),
        (
            lambda value: _qualification_sample(value, "factor_evaluation", "cold", 0).update(
                financial_parquet_scans=1
            ),
            "Financial Data",
        ),
        (
            lambda value: _qualification_sample(value, "factor_evaluation", "warm", 0).update(
                strategy_continuation_present=True
            ),
            "performed or published Strategy work",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "warm", 0)[
                "result_payload_names"
            ].remove("terminal_positions.part-000000"),
            "journey evidence is incomplete",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "warm", 0)[
                "result_payload_names"
            ].append("terminal_positions.part-unexpected-extra"),
            "journey evidence is incomplete",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "warm", 0)[
                "result_payload_names"
            ].__setitem__(
                2,
                "strategy_daily_observations.part-000001",
            ),
            "journey evidence is incomplete",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "warm", 0)[
                "result_payload_names"
            ].__setitem__(
                5,
                "terminal_positions.part-invalid",
            ),
            "journey evidence is incomplete",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "warm", 0)[
                "result_payload_names"
            ].append("factor_summary"),
            "payload evidence is invalid",
        ),
        (
            lambda value: _qualification_sample(value, "strategy_backtest", "cold", 0).update(
                factor_summary_sha256="e" * 64
            ),
            "Factor Summary equivalent",
        ),
        (
            lambda value: value["summary"]["factor_evaluation"].update(cold_max_duration_ms=0),
            "summary",
        ),
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


def test_long_research_sample_qualification_is_reportable_before_fail_fast() -> None:
    evidence = _long_research_evidence()
    sample = _qualification_sample(evidence, "factor_evaluation", "warm", 0)

    assert long_research_sample_qualification(
        sample,
        research_kind="factor_evaluation",
        phase="warm",
        index=0,
    ) == {"status": "passed", "failure_reason": None}

    sample["duration_ms"] = 300_001

    assert long_research_sample_qualification(
        sample,
        research_kind="factor_evaluation",
        phase="warm",
        index=0,
    ) == {
        "status": "failed",
        "failure_reason": "factor_evaluation warm sample 0 exceeds five minutes",
    }


def test_long_research_final_qualification_failure_is_reportable() -> None:
    evidence = _long_research_evidence()
    evidence["scientific_equivalence"]["factor_summary_sha256"] = "e" * 64

    assert long_research_qualification_outcome(evidence) == {
        "status": "failed",
        "failure_reason": "scientific equivalence evidence is inconsistent",
    }


def test_repository_benchmark_contract_is_full_scale_and_budgeted() -> None:
    root = Path(__file__).resolve().parents[4]
    profile = json.loads(
        (root / "apps/core/benchmarks/financial-io-2010-profile.json").read_bytes()
    )
    baseline = json.loads(
        (root / "apps/core/benchmarks/financial-io-2010-baseline.json").read_bytes()
    )
    budgets = json.loads(
        (root / "apps/core/benchmarks/financial-io-2010-budgets.json").read_bytes()
    )

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
        (root / "apps/core/benchmarks/financial-io-2010-baseline.json").read_bytes()
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
    root = Path(__file__).resolve().parents[4]

    profile = json.loads(
        (root / "apps/core/benchmarks/long-research-2010-profile.json").read_bytes()
    )

    assert profile == {
        "format": "thesistrace-long-research-profile",
        "version": 1,
        "generation_calendar_start": "2009-12-07",
        "workload_start_date": "2010-01-04",
        "workload_end_date": "2026-08-13",
        "ordinary_a_share_instrument_count": 5541,
        "execution_universe_size": 3000,
        "market_dense_session_count": 4354,
        "formula": "rank(pct_change(close, 20))",
        "universe": "top3000",
        "repetitions_per_phase": 5,
    }


def test_cancellation_wait_matches_the_public_worker_child_start_event() -> None:
    event = json.loads('{"event":"research_execution_child_started","run_id":"run_expected"}')

    assert is_research_execution_child_started_event(event, "run_expected")
    assert not is_research_execution_child_started_event(event, "run_other")
    assert not is_research_execution_child_started_event(
        {
            "event": "research_execution_child_started",
            "resource_id": "run_expected",
        },
        "run_expected",
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
