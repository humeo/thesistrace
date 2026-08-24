from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from thesistrace.entrypoints.runtime import CoreRuntime

logger = logging.getLogger(__name__)

DEVELOPMENT_CPU_COUNT = 2
DEVELOPMENT_MEMORY_BYTES = 2 * 1024**3
DEVELOPMENT_EXECUTION_MEMORY_BYTES = 1536 * 1024**2
DEVELOPMENT_CALCULATION_THREADS = 2
_THREAD_ENVIRONMENT_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


class WorkerRole(StrEnum):
    RESEARCH = "research"
    BATCH_RESEARCH = "batch-research"
    TRACKING = "tracking"


@dataclass(frozen=True)
class WorkerCapacity:
    cpu_count: float
    memory_bytes: int
    execution_memory_bytes: int
    calculation_threads: int


@dataclass(frozen=True)
class WorkerConfiguration:
    role: WorkerRole
    capacity: WorkerCapacity
    slot: int = 1


@dataclass(frozen=True)
class AvailableCapacity:
    cpu_count: float
    memory_bytes: int


@dataclass(frozen=True)
class ParsedWorkerArguments:
    configuration: WorkerConfiguration
    once: bool


class WorkerCapacityError(RuntimeError):
    pass


class WorkerEventSink(Protocol):
    def __call__(self, event: dict[str, object]) -> None: ...


class WorkerClaimSink(Protocol):
    def __call__(
        self,
        resource_id: str,
        attempt_id: str,
        claim_context: Mapping[str, object] | None = None,
    ) -> None: ...


def parse_worker_arguments(arguments: Sequence[str] | None = None) -> ParsedWorkerArguments:
    parser = argparse.ArgumentParser(description="Run one fixed-role ThesisTrace Worker")
    parser.add_argument("--role", required=True, choices=tuple(WorkerRole))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cpu-count", type=float, default=DEVELOPMENT_CPU_COUNT)
    parser.add_argument("--memory-bytes", type=int, default=DEVELOPMENT_MEMORY_BYTES)
    parser.add_argument(
        "--execution-memory-bytes",
        type=int,
        default=DEVELOPMENT_EXECUTION_MEMORY_BYTES,
    )
    parser.add_argument(
        "--calculation-threads",
        type=int,
        default=DEVELOPMENT_CALCULATION_THREADS,
    )
    parsed = parser.parse_args(arguments)
    capacity = WorkerCapacity(
        cpu_count=parsed.cpu_count,
        memory_bytes=parsed.memory_bytes,
        execution_memory_bytes=parsed.execution_memory_bytes,
        calculation_threads=parsed.calculation_threads,
    )
    if capacity.cpu_count <= 0 or capacity.memory_bytes <= 0:
        parser.error("Worker CPU and memory declarations must be positive")
    if capacity.calculation_threads <= 0:
        parser.error("Worker calculation threads must be positive")
    if capacity.calculation_threads > capacity.cpu_count:
        parser.error("Worker calculation threads cannot exceed declared CPU")
    if capacity.execution_memory_bytes <= 0:
        parser.error("Worker execution memory must be positive")
    if capacity.execution_memory_bytes > capacity.memory_bytes * 3 // 4:
        parser.error("Worker execution memory cannot exceed 75 percent of memory")
    return ParsedWorkerArguments(
        configuration=WorkerConfiguration(
            role=WorkerRole(parsed.role),
            capacity=capacity,
        ),
        once=parsed.once,
    )


def validate_worker_capacity(
    configuration: WorkerConfiguration,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> AvailableCapacity:
    actual = _available_capacity(cgroup_root)
    declared = configuration.capacity
    if actual.cpu_count < declared.cpu_count:
        raise WorkerCapacityError(
            f"{configuration.role.value} Worker requires {declared.cpu_count:g} CPU; "
            f"cgroup provides {actual.cpu_count:g}"
        )
    if actual.memory_bytes < declared.memory_bytes:
        raise WorkerCapacityError(
            f"{configuration.role.value} Worker requires {declared.memory_bytes} memory bytes; "
            f"cgroup provides {actual.memory_bytes}"
        )
    return actual


def process_one_poll(
    runtime: CoreRuntime,
    configuration: WorkerConfiguration,
    *,
    emit: WorkerEventSink,
) -> None:
    claim = _claim_event(configuration, emit)
    execution_event = _execution_event(configuration, emit)
    if configuration.role is WorkerRole.RESEARCH:
        if (
            runtime.research_runs.execution_memory_bytes
            > configuration.capacity.execution_memory_bytes
        ):
            raise WorkerCapacityError(
                "Research Worker execution memory cannot fit frozen planning capacity"
            )
        product_worked = runtime.research_runs.process_next(
            on_claim=claim,
            on_execution_event=execution_event,
        )
    elif configuration.role is WorkerRole.BATCH_RESEARCH:
        if (
            runtime.research_batches.execution_memory_bytes
            > configuration.capacity.execution_memory_bytes
        ):
            raise WorkerCapacityError(
                "Batch Research Worker execution memory cannot fit planning capacity"
            )
        product_worked = runtime.research_batches.process_next(
            on_claim=claim,
            on_execution_event=execution_event,
        )
    else:
        if (
            runtime.daily_tracks.execution_memory_bytes
            > configuration.capacity.execution_memory_bytes
        ):
            raise WorkerCapacityError(
                "Tracking Worker execution memory cannot fit planning capacity"
            )
        product_worked = _process_tracking(runtime, claim, execution_event)
    if configuration.role is WorkerRole.TRACKING:
        removed_caches = runtime.daily_tracks.reconcile_working_cache()
        if removed_caches:
            emit(
                {
                    "event": "worker_cache_reconciliation",
                    "role": configuration.role.value,
                    "slot": configuration.slot,
                    "removed_cache_count": removed_caches,
                }
            )
    elif configuration.role is WorkerRole.BATCH_RESEARCH:
        removed_attempt_files = runtime.research_batches.reconcile_attempt_files()
        if removed_attempt_files:
            emit(
                {
                    "event": "worker_batch_attempt_file_reconciliation",
                    "role": configuration.role.value,
                    "slot": configuration.slot,
                    "removed_file_count": removed_attempt_files,
                }
            )
    if product_worked:
        return
    _collect_one_publication(runtime)


def main(arguments: Sequence[str] | None = None) -> None:
    parsed = parse_worker_arguments(arguments)
    configuration = parsed.configuration
    try:
        actual = validate_worker_capacity(configuration)
    except WorkerCapacityError as error:
        print(f"Worker startup failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    _configure_calculation_threads(configuration.capacity.calculation_threads)
    _emit_event(
        {
            "event": "worker_started",
            "role": configuration.role.value,
            "slot": configuration.slot,
            "slot_count": 1,
            "declared_cpu_count": configuration.capacity.cpu_count,
            "declared_memory_bytes": configuration.capacity.memory_bytes,
            "execution_memory_bytes": configuration.capacity.execution_memory_bytes,
            "calculation_threads": configuration.capacity.calculation_threads,
            "actual_cpu_count": actual.cpu_count,
            "actual_memory_bytes": actual.memory_bytes,
        }
    )
    from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime

    settings = CoreSettings.from_environment()
    with open_core_runtime(settings) as runtime:
        process_one_poll(runtime, configuration, emit=_emit_event)
        if parsed.once:
            _emit_event(
                {
                    "event": "worker_stopped",
                    "role": configuration.role.value,
                    "slot": configuration.slot,
                    "reason": "once_completed",
                }
            )
            return
        while True:
            time.sleep(5)
            process_one_poll(runtime, configuration, emit=_emit_event)


def _available_capacity(cgroup_root: Path) -> AvailableCapacity:
    return AvailableCapacity(
        cpu_count=_available_cpu_count(cgroup_root),
        memory_bytes=_available_memory_bytes(cgroup_root),
    )


def _available_cpu_count(cgroup_root: Path) -> float:
    cpu_max = cgroup_root / "cpu.max"
    if cpu_max.is_file():
        quota, period = cpu_max.read_text().split()
        if quota != "max":
            return int(quota) / int(period)
    quota_file = cgroup_root / "cpu" / "cpu.cfs_quota_us"
    period_file = cgroup_root / "cpu" / "cpu.cfs_period_us"
    if quota_file.is_file() and period_file.is_file():
        quota = int(quota_file.read_text())
        if quota > 0:
            return quota / int(period_file.read_text())
    if hasattr(os, "sched_getaffinity"):
        return float(len(os.sched_getaffinity(0)))
    return float(os.cpu_count() or 1)


def _available_memory_bytes(cgroup_root: Path) -> int:
    memory_max = cgroup_root / "memory.max"
    if memory_max.is_file():
        value = memory_max.read_text().strip()
        if value != "max":
            return int(value)
    memory_limit = cgroup_root / "memory" / "memory.limit_in_bytes"
    if memory_limit.is_file():
        value = int(memory_limit.read_text())
        if value < 1 << 60:
            return value
    return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))


def _configure_calculation_threads(calculation_threads: int) -> None:
    value = str(calculation_threads)
    for name in _THREAD_ENVIRONMENT_NAMES:
        os.environ[name] = value


def _claim_event(
    configuration: WorkerConfiguration,
    emit: WorkerEventSink,
) -> WorkerClaimSink:
    resource_type = (
        "ResearchRun"
        if configuration.role is WorkerRole.RESEARCH
        else (
            "ResearchBatch"
            if configuration.role is WorkerRole.BATCH_RESEARCH
            else "TrackingAdvance"
        )
    )

    def claimed(
        resource_id: str,
        attempt_id: str,
        claim_context: Mapping[str, object] | None = None,
    ) -> None:
        event: dict[str, object] = {
            "event": "worker_claim",
            "role": configuration.role.value,
            "slot": configuration.slot,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "attempt_id": attempt_id,
        }
        if claim_context is not None:
            for name in (
                "batch_kind",
                "claim_order",
                "owner_kind",
                "owner_id",
                "item_count",
            ):
                if name in claim_context:
                    event[name] = claim_context[name]
        emit(event)

    return claimed


def _execution_event(
    configuration: WorkerConfiguration,
    emit: WorkerEventSink,
) -> WorkerEventSink:
    def enriched(event: dict[str, object]) -> None:
        emit(
            {
                **event,
                "role": configuration.role.value,
                "slot": configuration.slot,
            }
        )

    return enriched


def _process_tracking(
    runtime: CoreRuntime,
    on_claim: Callable[[str, str], None],
    emit: WorkerEventSink,
) -> bool:
    from thesistrace.daily_track import DailyTrackProgressionFailed

    try:
        return runtime.daily_tracks.process_next(
            on_claim=on_claim,
            on_execution_event=emit,
        )
    except DailyTrackProgressionFailed as error:
        logger.error(
            "Tracking Worker isolated one DailyTrack failure at its current target",
            extra={"error_type": type(error.__cause__).__name__},
        )
        return True


def _collect_one_publication(runtime: CoreRuntime) -> None:
    from thesistrace.publication import (
        PublicationPreparationError,
        PublicationUnavailableError,
    )

    try:
        removed = runtime.publication.collect_one_pending_deletion()
    except (PublicationPreparationError, PublicationUnavailableError) as error:
        logger.warning(
            "Worker retained a pending Publication deletion for retry",
            extra={"error_type": type(error).__name__},
        )
        return
    if removed:
        logger.info("Worker removed one unreferenced Publication object")
        return
    try:
        orphan_removed = runtime.publication.collect_one_orphan(
            uploaded_before=datetime.now(UTC) - timedelta(hours=1)
        )
    except (PublicationPreparationError, PublicationUnavailableError) as error:
        logger.warning(
            "Worker retained an orphan Publication upload for retry",
            extra={"error_type": type(error).__name__},
        )
        return
    if orphan_removed:
        logger.info("Worker removed one orphan Publication upload")


def _emit_event(event: dict[str, object]) -> None:
    print(
        json.dumps(event, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    main()
