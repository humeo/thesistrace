import hashlib
import hmac
from typing import Protocol

from thesistrace.objects import canonical_json_bytes
from thesistrace.qualification import (
    LAUNCH_QUALIFICATION,
    build_qualification,
    qualification_matches_release,
)

REQUIRED_LAUNCH_CHECKS = frozenset(
    {
        "backend",
        "browser",
        "capacity",
        "coordinated_backup",
        "direct_origin_security",
        "frontend",
        "full_restore",
        "migrations",
        "postgresql_rls",
        "public_origin",
        "source_authorization",
        "storage",
    }
)


class LaunchQualificationStore(Protocol):
    def record_launch_qualification(
        self,
        qualification: dict[str, object],
        audit_event: dict[str, object],
    ) -> None: ...

    def latest_launch_qualification(self) -> dict[str, object] | None: ...


class LaunchQualificationError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class LaunchQualificationService:
    def __init__(
        self,
        store: LaunchQualificationStore,
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
        attestation: str,
        attestation_key: bytes,
    ) -> dict[str, object]:
        normalized_actor = actor.strip()
        normalized_release = release_bundle_id.strip()
        if not normalized_actor or not normalized_release:
            raise LaunchQualificationError(
                "LAUNCH_QUALIFICATION_INVALID",
                "operator actor and release bundle are required",
            )
        if evidence.get("schema_version") == "hosted-v2-local-v1":
            raise LaunchQualificationError(
                "LAUNCH_QUALIFICATION_LOCAL_EVIDENCE_FORBIDDEN",
                "Hosted Local Acceptance evidence cannot be recorded as Launch Qualification",
            )
        expected_attestation = launch_attestation(evidence, attestation_key)
        if not hmac.compare_digest(attestation, expected_attestation):
            raise LaunchQualificationError(
                "LAUNCH_QUALIFICATION_ATTESTATION_INVALID",
                "launch evidence was not attested by the release acceptance runner",
            )
        failures = launch_failures(
            evidence,
            expected_release_bundle_id=normalized_release,
        )
        qualification, audit_event = build_qualification(
            kind=LAUNCH_QUALIFICATION,
            actor=normalized_actor,
            release_bundle_id=normalized_release,
            evidence=evidence,
            failures=failures,
        )
        self.store.record_launch_qualification(qualification, audit_event)
        return qualification

    def inspect(self) -> dict[str, object] | None:
        return self.store.latest_launch_qualification()

    def is_qualified(self) -> bool:
        return qualification_matches_release(
            self.inspect(),
            self.required_release_bundle_id,
        )


def launch_failures(
    evidence: dict[str, object],
    *,
    expected_release_bundle_id: str | None = None,
) -> list[str]:
    failures: list[str] = []
    if evidence.get("schema_version") != "hosted-v2-launch-v1":
        failures.append("schema_version")
    if evidence.get("clean_stack") is not True:
        failures.append("clean_stack")
    if (
        expected_release_bundle_id is not None
        and evidence.get("release_bundle_id") != expected_release_bundle_id
    ):
        failures.append("release_bundle_id")
    checks = evidence.get("checks")
    if not isinstance(checks, dict):
        failures.extend(sorted(REQUIRED_LAUNCH_CHECKS))
    else:
        failures.extend(
            sorted(name for name in REQUIRED_LAUNCH_CHECKS if checks.get(name) is not True)
        )
    records = evidence.get("records")
    if not isinstance(records, dict):
        failures.extend(f"record:{name}" for name in sorted(REQUIRED_LAUNCH_CHECKS))
    else:
        failures.extend(
            f"record:{name}"
            for name in sorted(REQUIRED_LAUNCH_CHECKS)
            if not isinstance(records.get(name), dict)
            or records[name].get("status") != "passed"
        )
    return sorted(set(failures))


def launch_attestation(
    evidence: dict[str, object],
    attestation_key: bytes,
) -> str:
    if len(attestation_key) < 32:
        raise LaunchQualificationError(
            "LAUNCH_QUALIFICATION_ATTESTATION_INVALID",
            "launch attestation key is invalid",
        )
    return hmac.new(
        attestation_key,
        canonical_json_bytes(evidence),
        hashlib.sha256,
    ).hexdigest()
