from typing import Protocol

from thesistrace.qualification import (
    CAPACITY_QUALIFICATION,
    build_qualification,
    qualification_matches_release,
)

COMPUTE_ACTIVITY_COUNT = 4
COMPUTE_P99_MEMORY_LIMIT_MIB = 700
COMPUTE_PEAK_MEMORY_LIMIT_MIB = 800
NONWORKER_MEMORY_LIMIT_MIB = 5 * 1024
NONWORKER_CPU_LIMIT = 2.0
CAPACITY_EVIDENCE_SCHEMA_VERSION = "capacity-qualification-v2"
MINIMUM_RUNTIME_LOGICAL_CPU = 6.0
MINIMUM_RUNTIME_MEMORY_BYTES = 12 * 1024 * 1024 * 1024


class CapacityQualificationStore(Protocol):
    def record_capacity_qualification(
        self,
        qualification: dict[str, object],
        audit_event: dict[str, object],
    ) -> None: ...

    def latest_capacity_qualification(self) -> dict[str, object] | None: ...


class CapacityQualificationError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class CapacityQualificationService:
    def __init__(
        self,
        store: CapacityQualificationStore,
        *,
        required_release_bundle_id: str | None = None,
    ) -> None:
        self.store = store
        self.required_release_bundle_id = required_release_bundle_id

    def record(
        self,
        *,
        actor: str,
        release_bundle_id: str,
        evidence: dict[str, object],
    ) -> dict[str, object]:
        normalized_actor = actor.strip()
        normalized_release = release_bundle_id.strip()
        if not normalized_actor or not normalized_release:
            raise CapacityQualificationError(
                "CAPACITY_QUALIFICATION_INVALID",
                "operator actor and release bundle are required",
            )
        failures = qualification_failures(evidence)
        qualification, audit_event = build_qualification(
            kind=CAPACITY_QUALIFICATION,
            actor=normalized_actor,
            release_bundle_id=normalized_release,
            evidence=evidence,
            failures=failures,
        )
        self.store.record_capacity_qualification(qualification, audit_event)
        return qualification

    def inspect(self) -> dict[str, object] | None:
        return self.store.latest_capacity_qualification()

    def is_qualified(self) -> bool:
        return qualification_matches_release(
            self.inspect(),
            self.required_release_bundle_id,
        )


def qualification_failures(evidence: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if evidence.get("schema_version") != CAPACITY_EVIDENCE_SCHEMA_VERSION:
        failures.append("capacity_schema_version")
    runtime_capacity = evidence.get("runtime_capacity")
    if not isinstance(runtime_capacity, dict):
        failures.append("runtime_capacity_missing")
    else:
        try:
            logical_cpu = float(runtime_capacity["logical_cpu"])
            memory_bytes = int(runtime_capacity["memory_bytes"])
        except (KeyError, TypeError, ValueError, OverflowError):
            failures.append("runtime_capacity_invalid")
        else:
            if runtime_capacity.get("source") != "docker-info":
                failures.append("runtime_capacity_invalid")
            if logical_cpu < MINIMUM_RUNTIME_LOGICAL_CPU:
                failures.append("runtime_cpu_budget_insufficient")
            if memory_bytes < MINIMUM_RUNTIME_MEMORY_BYTES:
                failures.append("runtime_memory_budget_insufficient")
    workers = evidence.get("compute_workers")
    if not isinstance(workers, list) or len(workers) != COMPUTE_ACTIVITY_COUNT:
        failures.append("four_compute_activities_required")
    else:
        for worker in workers:
            if not isinstance(worker, dict):
                failures.append("compute_measurement_invalid")
                continue
            if float(worker.get("p99_memory_mib", float("inf"))) > (
                COMPUTE_P99_MEMORY_LIMIT_MIB
            ):
                failures.append("compute_p99_memory_exceeded")
            if float(worker.get("peak_memory_mib", float("inf"))) > (
                COMPUTE_PEAK_MEMORY_LIMIT_MIB
            ):
                failures.append("compute_peak_memory_exceeded")
            if worker.get("status") != "succeeded":
                failures.append("compute_result_incorrect")
            if worker.get("activity_attempt") != 1:
                failures.append("compute_activity_retried")
    publication = evidence.get("dataset_publication")
    if not isinstance(publication, dict) or publication.get("status") != "succeeded":
        failures.append("dataset_publication_failed")
    if not isinstance(publication, dict) or publication.get("worker_slot") != "data-1":
        failures.append("dataset_publication_not_isolated")
    if not isinstance(publication, dict) or publication.get("activity_attempt") != 1:
        failures.append("dataset_publication_retried")
    nonworker = evidence.get("nonworker_services")
    if not isinstance(nonworker, dict):
        failures.append("nonworker_measurement_missing")
    else:
        if float(nonworker.get("memory_limit_mib", float("inf"))) > (
            NONWORKER_MEMORY_LIMIT_MIB
        ):
            failures.append("nonworker_memory_budget_exceeded")
        if float(nonworker.get("cpu_limit", float("inf"))) > NONWORKER_CPU_LIMIT:
            failures.append("nonworker_cpu_budget_exceeded")
    for key in (
        "swap_used",
        "oom_kill",
        "unexpected_restart",
        "missing_heartbeat",
        "duplicate_publication",
        "incorrect_result",
    ):
        if evidence.get(key) is not False:
            failures.append(key)
    paths = evidence.get("production_paths")
    required_paths = {
        "parquet",
        "result_bundle",
        "working_cache",
        "postgresql",
        "object_store",
    }
    if not isinstance(paths, dict) or any(paths.get(key) is not True for key in required_paths):
        failures.append("production_paths_incomplete")
    if evidence.get("universe") != "top3000":
        failures.append("top3000_required")
    return sorted(set(failures))
