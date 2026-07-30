from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

MAX_ACTIVE_DAILY_TRACKS = 10
DEFAULT_MAX_NONTERMINAL_USER_COMPUTE_JOBS = 8
DEFAULT_MAX_PRIVATE_STORAGE_BYTES = 10 * 1024**3
QUOTA_DIMENSIONS = (
    "max_active_daily_tracks",
    "max_nonterminal_user_compute_jobs",
    "max_private_storage_bytes",
)
DEFAULT_QUOTA_PROFILE = {
    "max_active_daily_tracks": MAX_ACTIVE_DAILY_TRACKS,
    "max_nonterminal_user_compute_jobs": (
        DEFAULT_MAX_NONTERMINAL_USER_COMPUTE_JOBS
    ),
    "max_private_storage_bytes": DEFAULT_MAX_PRIVATE_STORAGE_BYTES,
}


class QuotaProfileError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class QuotaExceededError(RuntimeError):
    reason_code = "QUOTA_EXCEEDED"

    def __init__(self, *, dimension: str, limit: int) -> None:
        super().__init__(f"Personal Workspace quota exceeded: {dimension}")
        self.dimension = dimension
        self.limit = limit


class QuotaProfileStore(Protocol):
    def quota_profile(self, workspace_id: str) -> dict[str, int] | None: ...

    def update_quota_profile(
        self,
        *,
        workspace_id: str,
        overrides: dict[str, int],
        audit_event: dict[str, object],
    ) -> dict[str, int]: ...

    def append_management_audit_event(self, event: dict[str, object]) -> None: ...


class QuotaProfileService:
    def __init__(self, store: QuotaProfileStore) -> None:
        self.store = store

    def inspect(self, workspace_id: str) -> dict[str, int]:
        normalized_workspace_id = workspace_id.strip()
        profile = (
            self.store.quota_profile(normalized_workspace_id)
            if normalized_workspace_id
            else None
        )
        if profile is None:
            raise QuotaProfileError(
                "QUOTA_PROFILE_NOT_FOUND",
                "Personal Workspace Quota Profile not found",
            )
        return require_quota_profile(profile)

    def override(
        self,
        *,
        actor: str,
        workspace_id: str,
        max_active_daily_tracks: int | None = None,
        max_nonterminal_user_compute_jobs: int | None = None,
        max_private_storage_bytes: int | None = None,
    ) -> dict[str, int]:
        normalized_actor = actor.strip()
        normalized_workspace_id = workspace_id.strip()
        overrides = {
            key: value
            for key, value in {
                "max_active_daily_tracks": max_active_daily_tracks,
                "max_nonterminal_user_compute_jobs": (
                    max_nonterminal_user_compute_jobs
                ),
                "max_private_storage_bytes": max_private_storage_bytes,
            }.items()
            if value is not None
        }
        reason_code = self._validate_override(
            actor=normalized_actor,
            workspace_id=normalized_workspace_id,
            overrides=overrides,
        )
        current = (
            self.store.quota_profile(normalized_workspace_id)
            if normalized_workspace_id
            else None
        )
        if reason_code is None and current is None:
            reason_code = "QUOTA_PROFILE_NOT_FOUND"
        occurred_at = datetime.now(UTC).isoformat()
        if reason_code is not None:
            self.store.append_management_audit_event(
                quota_audit_event(
                    actor=normalized_actor or "unknown",
                    workspace_id=normalized_workspace_id or "unknown",
                    occurred_at=occurred_at,
                    outcome="rejected",
                    reason_code=reason_code,
                    dimensions=sorted(overrides),
                )
            )
            raise QuotaProfileError(
                reason_code,
                quota_error_message(reason_code),
            )

        assert current is not None
        require_quota_profile(current)
        audit_event = quota_audit_event(
            actor=normalized_actor,
            workspace_id=normalized_workspace_id,
            occurred_at=occurred_at,
            outcome="succeeded",
            reason_code=None,
            dimensions=sorted(overrides),
            overrides=overrides,
        )
        return require_quota_profile(
            self.store.update_quota_profile(
                workspace_id=normalized_workspace_id,
                overrides=overrides,
                audit_event=audit_event,
            )
        )

    @staticmethod
    def _validate_override(
        *,
        actor: str,
        workspace_id: str,
        overrides: dict[str, int],
    ) -> str | None:
        if not actor:
            return "OPERATOR_ACTOR_REQUIRED"
        if not workspace_id:
            return "QUOTA_WORKSPACE_REQUIRED"
        if not overrides:
            return "QUOTA_OVERRIDE_REQUIRED"
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in overrides.values()
        ):
            return "QUOTA_OVERRIDE_INVALID"
        active_limit = overrides.get("max_active_daily_tracks")
        if active_limit is not None and active_limit > MAX_ACTIVE_DAILY_TRACKS:
            return "QUOTA_OVERRIDE_EXCEEDS_HARD_MAXIMUM"
        return None


def require_quota_profile(profile: dict[str, int]) -> dict[str, int]:
    if set(profile) != set(QUOTA_DIMENSIONS):
        raise QuotaProfileError(
            "QUOTA_PROFILE_INVALID",
            "Quota Profile must contain exactly three dimensions",
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in profile.values()
    ):
        raise QuotaProfileError(
            "QUOTA_PROFILE_INVALID",
            "Quota Profile dimensions must be positive integers",
        )
    if profile["max_active_daily_tracks"] > MAX_ACTIVE_DAILY_TRACKS:
        raise QuotaProfileError(
            "QUOTA_PROFILE_INVALID",
            "Active DailyTrack quota exceeds the deployment hard maximum",
        )
    return {dimension: profile[dimension] for dimension in QUOTA_DIMENSIONS}


def quota_audit_event(
    *,
    actor: str,
    workspace_id: str,
    occurred_at: str,
    outcome: str,
    reason_code: str | None,
    dimensions: list[str],
    overrides: dict[str, int] | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {"dimensions": dimensions}
    if overrides is not None:
        details["overrides"] = {
            dimension: overrides[dimension] for dimension in sorted(overrides)
        }
    return {
        "id": f"audit_{uuid4().hex}",
        "occurred_at": occurred_at,
        "actor": actor,
        "action": "quota_profile.override",
        "outcome": outcome,
        "reason_code": reason_code,
        "subject_type": "quota_profile",
        "subject_id": workspace_id,
        "details": details,
    }


def quota_error_message(reason_code: str) -> str:
    return {
        "OPERATOR_ACTOR_REQUIRED": "operator actor is required",
        "QUOTA_WORKSPACE_REQUIRED": "Personal Workspace id is required",
        "QUOTA_OVERRIDE_REQUIRED": "at least one quota override is required",
        "QUOTA_OVERRIDE_INVALID": "quota overrides must be positive integers",
        "QUOTA_OVERRIDE_EXCEEDS_HARD_MAXIMUM": (
            "Active DailyTrack override cannot exceed 10"
        ),
        "QUOTA_PROFILE_NOT_FOUND": "Personal Workspace Quota Profile not found",
    }[reason_code]
