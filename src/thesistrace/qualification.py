import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from thesistrace.objects import canonical_json_bytes


@dataclass(frozen=True)
class QualificationKind:
    name: str


CAPACITY_QUALIFICATION = QualificationKind("capacity")
LAUNCH_QUALIFICATION = QualificationKind("launch")


def build_qualification(
    *,
    kind: QualificationKind,
    actor: str,
    release_bundle_id: str,
    evidence: dict[str, object],
    failures: list[str],
) -> tuple[dict[str, object], dict[str, object]]:
    measured_at = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
    audit_event_id = f"audit_{uuid4().hex}"
    qualification = {
        "id": f"{kind.name}_{uuid4().hex}",
        "status": "passed" if not failures else "failed",
        "release_bundle_id": release_bundle_id,
        "evidence_sha256": digest,
        "evidence": evidence,
        "failures": failures,
        "recorded_by": actor,
        "measured_at": measured_at,
        "audit_event_id": audit_event_id,
    }
    audit_event = {
        "id": audit_event_id,
        "occurred_at": measured_at,
        "actor": actor,
        "action": f"{kind.name}_qualification.record",
        "outcome": "succeeded" if not failures else "rejected",
        "reason_code": (
            None
            if not failures
            else f"{kind.name.upper()}_QUALIFICATION_FAILED"
        ),
        "subject_type": f"{kind.name}_qualification",
        "subject_id": qualification["id"],
        "details": {
            "release_bundle_id": release_bundle_id,
            "evidence_sha256": digest,
            "status": qualification["status"],
            "failure_count": len(failures),
        },
    }
    return qualification, audit_event


def qualification_matches_release(
    qualification: dict[str, object] | None,
    required_release_bundle_id: str | None,
) -> bool:
    return (
        qualification is not None
        and qualification.get("status") == "passed"
        and (
            required_release_bundle_id is None
            or qualification.get("release_bundle_id") == required_release_bundle_id
        )
    )
