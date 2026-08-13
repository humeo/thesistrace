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
    "derive_repository_budgets",
    "measure_operation",
    "summarize_samples",
)
