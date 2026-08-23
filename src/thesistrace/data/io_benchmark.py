from __future__ import annotations

import gc
import math
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from thesistrace.data.io_metrics import cold_file_reads, measure_data_io
from thesistrace.product_state import PRODUCT_STATE_COUNT_NAMES

EXACT_IO_BUDGET_METRICS = (
    "bytes_read",
    "columns_scanned",
    "financial_parquet_scans",
    "manifest_opens",
    "market_parquet_scans",
    "parquet_object_opens",
    "raw_financial_batch_opens",
    "rows_scanned",
)
LONG_RESEARCH_FORMULA = "cs_rank(pct_change(close_adj, 20))"
LONG_RESEARCH_START_DATE = "2010-01-04"
LONG_RESEARCH_END_DATE = "2026-08-13"
LONG_RESEARCH_UNIVERSE = "top3000"
LONG_RESEARCH_SAMPLE_COUNT = 5
LONG_RESEARCH_COLD_P95_LIMIT_MS = 600_000
LONG_RESEARCH_WARM_P95_LIMIT_MS = 300_000
LONG_RESEARCH_PEAK_RSS_LIMIT_BYTES = 1536 * 1024 * 1024
LONG_RESEARCH_FIRST_CHECKPOINT_LIMIT_MS = 45_000
LONG_RESEARCH_CANCELLATION_LIMIT_MS = 5_000
LONG_RESEARCH_KINDS = ("factor_evaluation", "strategy_backtest")
_DURATION_REGRESSION_FACTOR = 3
_PEAK_MEMORY_REGRESSION_FACTOR = 2


@dataclass(frozen=True)
class BenchmarkSample:
    duration_ms: float
    peak_memory_bytes: int
    manifest_opens: int
    parquet_object_opens: int
    raw_financial_batch_opens: int
    market_parquet_scans: int
    financial_parquet_scans: int
    bytes_read: int
    rows_scanned: int
    columns_scanned: int

    def descriptor(self) -> dict[str, int | float]:
        return {
            "duration_ms": round(self.duration_ms, 3),
            "peak_memory_bytes": self.peak_memory_bytes,
            "manifest_opens": self.manifest_opens,
            "parquet_object_opens": self.parquet_object_opens,
            "raw_financial_batch_opens": self.raw_financial_batch_opens,
            "market_parquet_scans": self.market_parquet_scans,
            "financial_parquet_scans": self.financial_parquet_scans,
            "bytes_read": self.bytes_read,
            "rows_scanned": self.rows_scanned,
            "columns_scanned": self.columns_scanned,
        }


def measure_operation[Result](
    operation: Callable[[], Result],
    *,
    cold: bool = False,
) -> BenchmarkSample:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    try:
        if cold:
            with cold_file_reads(), measure_data_io() as measurement:
                result = operation()
        else:
            with measure_data_io() as measurement:
                result = operation()
        duration_ms = (time.perf_counter() - started) * 1000
        _retain_until_measured(result)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return BenchmarkSample(
        duration_ms=duration_ms,
        peak_memory_bytes=peak,
        **measurement.snapshot(),
    )


def summarize_samples(samples: Sequence[BenchmarkSample]) -> dict[str, object]:
    if not samples:
        raise ValueError("benchmark requires at least one sample")
    descriptors = [sample.descriptor() for sample in samples]
    keys = tuple(descriptors[0])
    return {
        "sample_count": len(samples),
        "p50": {key: _percentile([item[key] for item in descriptors], 0.50) for key in keys},
        "p95": {key: _percentile([item[key] for item in descriptors], 0.95) for key in keys},
        "samples": descriptors,
    }


def assert_benchmark_budgets(
    results: Mapping[str, object],
    budgets: Mapping[str, object],
) -> None:
    result_scenarios = results.get("scenarios")
    budget_scenarios = budgets.get("scenarios")
    if not isinstance(result_scenarios, Mapping) or not isinstance(budget_scenarios, Mapping):
        raise AssertionError("benchmark result or budget scenarios are invalid")
    if set(result_scenarios) != set(budget_scenarios):
        raise AssertionError("benchmark scenario set changed")
    violations: list[str] = []
    for scenario, expected_phases in budget_scenarios.items():
        actual_phases = result_scenarios[scenario]
        if not isinstance(actual_phases, Mapping) or not isinstance(expected_phases, Mapping):
            raise AssertionError("benchmark phase contract is invalid")
        for phase, limits in expected_phases.items():
            actual = actual_phases.get(phase)
            if not isinstance(actual, Mapping) or not isinstance(limits, Mapping):
                raise AssertionError("benchmark phase result is invalid")
            p95 = actual.get("p95")
            if not isinstance(p95, Mapping):
                raise AssertionError("benchmark percentile result is invalid")
            for metric, maximum in limits.items():
                value = p95.get(metric)
                if not isinstance(value, int | float) or not isinstance(maximum, int | float):
                    raise AssertionError("benchmark budget metric is invalid")
                if value > maximum:
                    violations.append(f"{scenario}.{phase}.{metric}: {value} > {maximum}")
    if violations:
        raise AssertionError("benchmark budgets exceeded: " + "; ".join(violations))


def derive_repository_budgets(results: Mapping[str, object]) -> dict[str, object]:
    result_scenarios = results.get("scenarios")
    if not isinstance(result_scenarios, Mapping):
        raise ValueError("benchmark scenarios are invalid")
    scenarios: dict[str, object] = {}
    for scenario_name, phases_value in result_scenarios.items():
        if not isinstance(scenario_name, str) or not isinstance(phases_value, Mapping):
            raise ValueError("benchmark scenario is invalid")
        phases: dict[str, object] = {}
        for phase_name, phase_value in phases_value.items():
            if not isinstance(phase_name, str) or not isinstance(phase_value, Mapping):
                raise ValueError("benchmark phase is invalid")
            p95 = phase_value.get("p95")
            if not isinstance(p95, Mapping):
                raise ValueError("benchmark percentile is invalid")
            limits: dict[str, int | float] = {}
            for metric in EXACT_IO_BUDGET_METRICS:
                value = p95.get(metric)
                if not isinstance(value, int | float):
                    raise ValueError("benchmark exact I/O metric is invalid")
                limits[metric] = value
            duration = p95.get("duration_ms")
            peak_memory = p95.get("peak_memory_bytes")
            if not isinstance(duration, int | float) or not isinstance(peak_memory, int | float):
                raise ValueError("benchmark resource metric is invalid")
            limits["duration_ms"] = math.ceil(duration * _DURATION_REGRESSION_FACTOR)
            limits["peak_memory_bytes"] = math.ceil(peak_memory * _PEAK_MEMORY_REGRESSION_FACTOR)
            phases[phase_name] = limits
        scenarios[scenario_name] = phases
    return {
        "format": "thesistrace-financial-io-budgets",
        "version": 1,
        "derived_from": "financial-io-2010-baseline.json",
        "scenarios": scenarios,
    }


def assert_long_research_qualification(
    evidence: Mapping[str, object],
) -> dict[str, dict[str, int | float]]:
    if (
        evidence.get("format") != "thesistrace-long-research-qualification"
        or evidence.get("version") != 1
    ):
        raise AssertionError("long Research evidence format is invalid")
    capacity = _mapping(evidence.get("capacity"), "capacity")
    if capacity != {
        "cpu_count": 2,
        "memory_bytes": 2 * 1024 * 1024 * 1024,
        "execution_memory_bytes": LONG_RESEARCH_PEAK_RSS_LIMIT_BYTES,
        "calculation_threads": 2,
        "slot_count": 1,
    }:
        raise AssertionError("long Research capacity is not the Production Image contract")
    image = _mapping(evidence.get("image"), "image")
    revision = image.get("revision")
    if not isinstance(revision, str) or not revision:
        raise AssertionError("long Research image revision is missing")
    workload = _mapping(evidence.get("workload"), "workload")
    expected_workload = {
        "formula": LONG_RESEARCH_FORMULA,
        "universe": LONG_RESEARCH_UNIVERSE,
        "start_date": LONG_RESEARCH_START_DATE,
        "end_date": LONG_RESEARCH_END_DATE,
    }
    if any(workload.get(key) != value for key, value in expected_workload.items()):
        raise AssertionError("long Research workload is not the fixed reference workload")
    generation = workload.get("generation_manifest_sha256")
    if not isinstance(generation, str) or len(generation) != 64:
        raise AssertionError("long Research frozen Generation identity is invalid")
    if _positive_int(workload.get("chunk_session_count"), "Chunk session count") > 64:
        raise AssertionError("long Research Chunk exceeds 64 sessions")
    _positive_int(workload.get("chunk_count"), "Chunk count")

    preload = _mapping(evidence.get("warm_preload"), "warm preload")
    if preload.get("generation_manifest_sha256") != generation:
        raise AssertionError("warm preload used another Generation")
    _empty_product_state(preload.get("product_state_before"), "warm preload before")
    _empty_product_state(preload.get("product_state_after"), "warm preload after")
    if _positive_int(preload.get("market_parquet_scans"), "warm preload scans") <= 0:
        raise AssertionError("warm preload read no Canonical Market Data")

    kinds = _mapping(evidence.get("research_kinds"), "Research Kinds")
    if set(kinds) != set(LONG_RESEARCH_KINDS):
        raise AssertionError("long Research Kind set is invalid")
    summary = long_research_qualification_summary(evidence)
    factor_summary_ids: set[str] = set()
    sample_generation_ids: set[str] = set()
    sample_plans: set[tuple[int, int]] = set()
    sample_run_ids: set[str] = set()
    sample_attempt_ids: set[str] = set()
    for research_kind in LONG_RESEARCH_KINDS:
        kind_evidence = _mapping(kinds[research_kind], research_kind)
        cold = _qualification_samples(
            kind_evidence.get("cold"), phase="cold", research_kind=research_kind
        )
        warm = _qualification_samples(
            kind_evidence.get("warm"), phase="warm", research_kind=research_kind
        )
        factor_summary_ids.update(str(item["factor_summary_sha256"]) for item in (*cold, *warm))
        sample_generation_ids.update(
            str(item["generation_manifest_sha256"]) for item in (*cold, *warm)
        )
        sample_plans.update(
            (int(item["chunk_session_count"]), int(item["chunk_count"]))
            for item in (*cold, *warm)
        )
        sample_run_ids.update(str(item["run_id"]) for item in (*cold, *warm))
        sample_attempt_ids.update(str(item["attempt_id"]) for item in (*cold, *warm))
        kind_summary = summary[research_kind]
        if kind_summary["cold_p95_duration_ms"] > LONG_RESEARCH_COLD_P95_LIMIT_MS:
            raise AssertionError(f"{research_kind} cold execution P95 exceeds ten minutes")
        if kind_summary["warm_p95_duration_ms"] > LONG_RESEARCH_WARM_P95_LIMIT_MS:
            raise AssertionError(f"{research_kind} warm execution P95 exceeds five minutes")
        if kind_summary["peak_rss_bytes"] > LONG_RESEARCH_PEAK_RSS_LIMIT_BYTES:
            raise AssertionError(f"{research_kind} peak RSS exceeds the 1.5 GiB execution budget")
        if (
            kind_summary["first_checkpoint_latency_ms"]
            > LONG_RESEARCH_FIRST_CHECKPOINT_LIMIT_MS
        ):
            raise AssertionError(f"{research_kind} first Checkpoint exceeds 45 seconds")
        if kind_summary["cancellation_latency_ms"] > LONG_RESEARCH_CANCELLATION_LIMIT_MS:
            raise AssertionError(f"{research_kind} cancellation exceeds five seconds")
        _validate_cancellation(kind_evidence.get("cancellation"), research_kind)
    if sample_generation_ids != {generation} or sample_plans != {
        (
            int(workload["chunk_session_count"]),
            int(workload["chunk_count"]),
        )
    }:
        raise AssertionError("long Research samples changed frozen Generation or plan")
    expected_sample_count = LONG_RESEARCH_SAMPLE_COUNT * 2 * len(LONG_RESEARCH_KINDS)
    if (
        len(sample_run_ids) != expected_sample_count
        or len(sample_attempt_ids) != expected_sample_count
    ):
        raise AssertionError("long Research samples did not use fresh Runs and Attempts")
    if len(factor_summary_ids) != 1:
        raise AssertionError("Research Kinds are not Factor Summary equivalent")
    scientific = _mapping(evidence.get("scientific_equivalence"), "scientific equivalence")
    if scientific != {
        "factor_summary_sha256": next(iter(factor_summary_ids)),
        "sample_count": expected_sample_count,
    }:
        raise AssertionError("scientific equivalence evidence is inconsistent")
    recorded_summary = _mapping(evidence.get("summary"), "summary")
    if recorded_summary != summary:
        raise AssertionError("long Research qualification summary is missing or inconsistent")
    return summary


def long_research_qualification_summary(
    evidence: Mapping[str, object],
) -> dict[str, dict[str, int | float]]:
    kinds = _mapping(evidence.get("research_kinds"), "Research Kinds")
    summary: dict[str, dict[str, int | float]] = {}
    for research_kind in LONG_RESEARCH_KINDS:
        kind = _mapping(kinds.get(research_kind), research_kind)
        cold = _qualification_samples(
            kind.get("cold"), phase="cold", research_kind=research_kind
        )
        warm = _qualification_samples(
            kind.get("warm"), phase="warm", research_kind=research_kind
        )
        all_samples = (*cold, *warm)
        cancellation = _mapping(kind.get("cancellation"), f"{research_kind} cancellation")
        summary[research_kind] = {
            "cold_p95_duration_ms": _percentile(
                [_number(item, "duration_ms") for item in cold], 0.95
            ),
            "warm_p95_duration_ms": _percentile(
                [_number(item, "duration_ms") for item in warm], 0.95
            ),
            "peak_rss_bytes": max(
                _number(item, "peak_rss_bytes") for item in all_samples
            ),
            "first_checkpoint_latency_ms": max(
                _number(item, "first_checkpoint_latency_ms") for item in all_samples
            ),
            "cancellation_latency_ms": _number(
                cancellation, "cancellation_latency_ms"
            ),
        }
    return summary


def _qualification_samples(
    value: object,
    *,
    phase: str,
    research_kind: str,
) -> tuple[Mapping[str, object], ...]:
    samples_value = _mapping(value, phase).get("samples")
    if not isinstance(samples_value, list) or len(samples_value) != LONG_RESEARCH_SAMPLE_COUNT:
        raise AssertionError(f"long Research requires five {phase} samples")
    samples = tuple(_mapping(item, f"{phase} sample") for item in samples_value)
    required = {
        "duration_ms",
        "admission_duration_ms",
        "attempt_duration_ms",
        "peak_rss_bytes",
        "first_checkpoint_latency_ms",
        "manifest_opens",
        "parquet_object_opens",
        "market_parquet_scans",
        "financial_parquet_scans",
        "raw_financial_batch_opens",
        "bytes_read",
        "rows_scanned",
        "columns_scanned",
        "process_exit_code",
        "worker_exit_code",
        "result_manifest_sha256",
        "run_id",
        "attempt_id",
        "generation_manifest_sha256",
        "chunk_session_count",
        "chunk_count",
        "result_payload_names",
        "result_object_names",
        "factor_summary_sha256",
        "phase_timings_seconds",
        "strategy_continuation_present",
        "strategy_observation_count",
        "fresh_product_state_verified",
        "fresh_product_state_counts",
        "checkpoint_count_after_success",
        "active_pin_count_after_success",
    }
    for sample in samples:
        if not required.issubset(sample):
            raise AssertionError(f"{phase} sample evidence is incomplete")
        if sample["financial_parquet_scans"] != 0 or sample["raw_financial_batch_opens"] != 0:
            raise AssertionError("market-only long Research opened Financial Data")
        if sample["market_parquet_scans"] == 0:
            raise AssertionError("market-only long Research did not scan Market Data")
        if sample["process_exit_code"] != 0:
            raise AssertionError("long Research child process did not exit successfully")
        if sample["worker_exit_code"] != 0 or sample.get("research_kind") != research_kind:
            raise AssertionError("long Research Worker or Research Kind evidence is invalid")
        if (
            not isinstance(sample["run_id"], str)
            or not sample["run_id"]
            or not isinstance(sample["attempt_id"], str)
            or not sample["attempt_id"]
        ):
            raise AssertionError("long Research Run or Attempt identity is invalid")
        if sample["fresh_product_state_verified"] is not True:
            raise AssertionError("long Research sample reused Product State")
        _empty_product_state(sample["fresh_product_state_counts"], f"{phase} sample")
        manifest = sample["result_manifest_sha256"]
        if not isinstance(manifest, str) or len(manifest) != 64:
            raise AssertionError("long Research Result manifest identity is invalid")
        factor_summary_sha256 = sample["factor_summary_sha256"]
        if not isinstance(factor_summary_sha256, str) or len(factor_summary_sha256) != 64:
            raise AssertionError("long Research Factor Summary identity is invalid")
        _validate_kind_specific_sample(sample, research_kind)
        if (
            sample["checkpoint_count_after_success"] != 0
            or sample["active_pin_count_after_success"] != 0
        ):
            raise AssertionError("long Research success leaked Checkpoints or Generation Pins")
        generation = sample["generation_manifest_sha256"]
        if not isinstance(generation, str) or len(generation) != 64:
            raise AssertionError("long Research sample Generation identity is invalid")
        if _positive_int(sample["chunk_session_count"], "sample Chunk size") > 64:
            raise AssertionError("long Research sample Chunk exceeds 64 sessions")
        _positive_int(sample["chunk_count"], "sample Chunk count")
        for metric in required - {
            "result_manifest_sha256",
            "generation_manifest_sha256",
            "chunk_session_count",
            "chunk_count",
            "result_payload_names",
            "result_object_names",
            "factor_summary_sha256",
            "phase_timings_seconds",
            "strategy_continuation_present",
            "fresh_product_state_verified",
            "fresh_product_state_counts",
            "run_id",
            "attempt_id",
        }:
            _number(sample, metric)
    if (
        sorted(int(sample.get("index", -1)) for sample in samples)
        != list(range(LONG_RESEARCH_SAMPLE_COUNT))
        or any(sample.get("phase") != phase for sample in samples)
    ):
        raise AssertionError(f"long Research {phase} sample identities are invalid")
    return samples


def _validate_kind_specific_sample(
    sample: Mapping[str, object], research_kind: str
) -> None:
    timings = _mapping(sample.get("phase_timings_seconds"), "phase timings")
    expected_phases = {
        "data_read",
        "calculation",
        "input",
        "alpha_and_pending",
        "factor",
        "strategy",
        "finalize",
        "checkpoint_commit",
    }
    if set(timings) != expected_phases:
        raise AssertionError("long Research phase timing set is invalid")
    for phase in expected_phases:
        _number(timings, phase)
    if any(_number(timings, phase) <= 0 for phase in expected_phases - {"strategy"}):
        raise AssertionError("long Research phase timing is empty")
    payload_names = sample.get("result_payload_names")
    object_names = sample.get("result_object_names")
    if not isinstance(payload_names, list) or not isinstance(object_names, list):
        raise AssertionError("long Research Result object evidence is invalid")
    if research_kind == "factor_evaluation":
        if (
            _number(timings, "strategy") != 0
            or sample.get("strategy_continuation_present") is not False
            or sample.get("strategy_observation_count") != 0
            or payload_names != ["factor_summary"]
            or object_names != ["factor_summary"]
        ):
            raise AssertionError("Factor Evaluation performed or published Strategy work")
        return
    expected_objects = [
        "factor_summary",
        "strategy_daily_observations",
        "strategy_summary",
        "terminal_strategy_state",
    ]
    partition_names = {
        str(name)
        for name in payload_names
        if str(name).startswith("strategy_daily_observations.part-")
    }
    if (
        _number(timings, "strategy") <= 0
        or sample.get("strategy_continuation_present") is not True
        or _number(sample, "strategy_observation_count") <= 0
        or object_names != expected_objects
        or not partition_names
        or set(payload_names) != set(expected_objects) | partition_names
    ):
        raise AssertionError("Strategy Backtest journey evidence is incomplete")


def _validate_cancellation(value: object, research_kind: str) -> None:
    cancellation = _mapping(value, f"{research_kind} cancellation")
    if (
        cancellation.get("research_kind") != research_kind
        or cancellation.get("status") != "cancelled"
        or cancellation.get("fresh_product_state_verified") is not True
        or cancellation.get("result_manifest_sha256") is not None
        or cancellation.get("checkpoint_count") != 0
        or cancellation.get("active_pin_count") != 0
        or cancellation.get("worker_exit_code") != 0
        or cancellation.get("child_exit_code") != 0
        or cancellation.get("child_acknowledged") is not False
    ):
        raise AssertionError(f"{research_kind} cancellation evidence is invalid")
    _empty_product_state(
        cancellation.get("fresh_product_state_counts"),
        f"{research_kind} cancellation",
    )


def _empty_product_state(value: object, subject: str) -> None:
    counts = _mapping(value, subject)
    if set(counts) != set(PRODUCT_STATE_COUNT_NAMES) or any(
        not isinstance(count, int) or isinstance(count, bool) or count != 0
        for count in counts.values()
    ):
        raise AssertionError(f"long Research {subject} Product State is not empty")


def _mapping(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"long Research {subject} evidence is invalid")
    return value


def _number(value: Mapping[str, object], key: str) -> int | float:
    result = value.get(key)
    if not isinstance(result, int | float) or isinstance(result, bool) or result < 0:
        raise AssertionError(f"long Research {key} evidence is invalid")
    return result


def _positive_int(value: object, subject: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AssertionError(f"long Research {subject} is invalid")
    return value


def _percentile(values: Sequence[int | float], percentile: float) -> int | float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _retain_until_measured(value: object) -> None:
    if value is None:
        return
    id(value)


__all__ = (
    "BenchmarkSample",
    "EXACT_IO_BUDGET_METRICS",
    "assert_benchmark_budgets",
    "assert_long_research_qualification",
    "derive_repository_budgets",
    "measure_operation",
    "summarize_samples",
)
