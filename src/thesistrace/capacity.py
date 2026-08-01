import hashlib
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from thesistrace.objects import canonical_json_bytes

COMPUTE_ACTIVITY_COUNT = 4
COMPUTE_P99_MEMORY_LIMIT_MIB = 700
COMPUTE_PEAK_MEMORY_LIMIT_MIB = 800
NONWORKER_MEMORY_LIMIT_MIB = 5 * 1024
NONWORKER_CPU_LIMIT = 2.0


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
    def __init__(self, store: CapacityQualificationStore) -> None:
        self.store = store

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
        measured_at = datetime.now(UTC).isoformat()
        digest = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
        audit_event_id = f"audit_{uuid4().hex}"
        qualification = {
            "id": f"capacity_{uuid4().hex}",
            "status": "passed" if not failures else "failed",
            "release_bundle_id": normalized_release,
            "evidence_sha256": digest,
            "evidence": evidence,
            "failures": failures,
            "recorded_by": normalized_actor,
            "measured_at": measured_at,
            "audit_event_id": audit_event_id,
        }
        audit_event = {
            "id": audit_event_id,
            "occurred_at": measured_at,
            "actor": normalized_actor,
            "action": "capacity_qualification.record",
            "outcome": "succeeded" if not failures else "rejected",
            "reason_code": None if not failures else "CAPACITY_QUALIFICATION_FAILED",
            "subject_type": "capacity_qualification",
            "subject_id": qualification["id"],
            "details": {
                "release_bundle_id": normalized_release,
                "evidence_sha256": digest,
                "status": qualification["status"],
                "failure_count": len(failures),
            },
        }
        self.store.record_capacity_qualification(qualification, audit_event)
        return qualification

    def inspect(self) -> dict[str, object] | None:
        return self.store.latest_capacity_qualification()

    def is_qualified(self) -> bool:
        latest = self.inspect()
        return latest is not None and latest.get("status") == "passed"


def qualification_failures(evidence: dict[str, object]) -> list[str]:
    failures: list[str] = []
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
        "temporal",
        "object_store",
    }
    if not isinstance(paths, dict) or any(paths.get(key) is not True for key in required_paths):
        failures.append("production_paths_incomplete")
    if evidence.get("universe") != "top3000":
        failures.append("top3000_required")
    return sorted(set(failures))
