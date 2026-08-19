from __future__ import annotations

import gc
import math
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from thesistrace.data.io_metrics import cold_file_reads, measure_data_io

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
) -> dict[str, int | float]:
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

    summary = long_research_qualification_summary(evidence)
    cold_p95 = summary["cold_p95_duration_ms"]
    warm_p95 = summary["warm_p95_duration_ms"]
    if cold_p95 > LONG_RESEARCH_COLD_P95_LIMIT_MS:
        raise AssertionError("cold execution P95 exceeds ten minutes")
    if warm_p95 > LONG_RESEARCH_WARM_P95_LIMIT_MS:
        raise AssertionError("warm execution P95 exceeds five minutes")
    peak_rss = summary["peak_rss_bytes"]
    if peak_rss > LONG_RESEARCH_PEAK_RSS_LIMIT_BYTES:
        raise AssertionError("peak RSS exceeds the 1.5 GiB execution budget")
    first_checkpoint = summary["first_checkpoint_latency_ms"]
    if first_checkpoint > LONG_RESEARCH_FIRST_CHECKPOINT_LIMIT_MS:
        raise AssertionError("first Checkpoint exceeds 45 seconds")
    cancellation = summary["cancellation_latency_ms"]
    if cancellation > LONG_RESEARCH_CANCELLATION_LIMIT_MS:
        raise AssertionError("cancellation exceeds five seconds")
    recorded_summary = _mapping(evidence.get("summary"), "summary")
    if recorded_summary != summary:
        raise AssertionError("long Research qualification summary is missing or inconsistent")
    return summary


def long_research_qualification_summary(
    evidence: Mapping[str, object],
) -> dict[str, int | float]:
    cold = _qualification_samples(evidence.get("cold"), phase="cold")
    warm = _qualification_samples(evidence.get("warm"), phase="warm")
    all_samples = (*cold, *warm)
    return {
        "cold_p95_duration_ms": _percentile(
            [_number(item, "duration_ms") for item in cold], 0.95
        ),
        "warm_p95_duration_ms": _percentile(
            [_number(item, "duration_ms") for item in warm], 0.95
        ),
        "peak_rss_bytes": max(_number(item, "peak_rss_bytes") for item in all_samples),
        "first_checkpoint_latency_ms": max(
            _number(item, "first_checkpoint_latency_ms") for item in all_samples
        ),
        "cancellation_latency_ms": _number(evidence, "cancellation_latency_ms"),
    }


def _qualification_samples(value: object, *, phase: str) -> tuple[Mapping[str, object], ...]:
    samples_value = _mapping(value, phase).get("samples")
    if not isinstance(samples_value, list) or len(samples_value) != LONG_RESEARCH_SAMPLE_COUNT:
        raise AssertionError(f"long Research requires five {phase} samples")
    samples = tuple(_mapping(item, f"{phase} sample") for item in samples_value)
    required = {
        "duration_ms",
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
        "result_manifest_sha256",
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
        manifest = sample["result_manifest_sha256"]
        if not isinstance(manifest, str) or len(manifest) != 64:
            raise AssertionError("long Research Result manifest identity is invalid")
        for metric in required - {"result_manifest_sha256"}:
            _number(sample, metric)
    return samples


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
