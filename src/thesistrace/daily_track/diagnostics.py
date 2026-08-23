from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track.failure_policy import (
    MAX_TRACKING_CYCLE_ATTEMPTS,
    tracking_attempt_failure_code,
    tracking_attempt_retry_eligible,
)

_BLOCKED_REASON_CODES = {
    "DailyTrack could not process the current dataset.": "TRACKING_FAILED",
    "DailyTrack target exceeds Tracking Worker capacity.": "CAPACITY_EXCEEDED",
    "Financial Coverage ends before the next Research Session.": (
        "FINANCIAL_COVERAGE_UNAVAILABLE"
    ),
    "DailyTrack exhausted its automatic infrastructure retries.": (
        "INFRASTRUCTURE_RETRIES_EXHAUSTED"
    ),
}


class DailyTrackDiagnosticNotFound(LookupError):
    pass


class DailyTrackDiagnostics:
    """Private PostgreSQL-only diagnostic reader owned by DailyTrack."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def inspect(self, track_id: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            transaction.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            track = transaction.execute(
                """
                SELECT transaction_timestamp() AS diagnosed_at,
                       track.id AS track_id,
                       track.seed_run_id,
                       track.status AS track_status,
                       track.blocked_reason,
                       state.origin_session,
                       head.boundary_session AS head_session,
                       state.updated_at AS head_updated_at,
                       advance.id AS advance_id,
                       advance.status AS advance_status,
                       advance.target_start_session,
                       advance.target_end_session,
                       cardinality(advance.target_sessions) AS target_session_count,
                       advance.current_cycle_ordinal,
                       advance.next_attempt_eligible_at,
                       advance.queue_position,
                       advance.created_at AS advance_created_at,
                       advance.finished_at AS advance_finished_at,
                       EXISTS (
                           SELECT 1
                           FROM daily_tracks.session_checkpoints AS published
                           WHERE published.track_id = track.id
                             AND published.progression_id = advance.id
                       ) AS advance_checkpoint_present,
                       latest.status AS latest_attempt_status,
                       latest.execution_phase AS latest_attempt_phase,
                       latest.current_session AS latest_current_session,
                       latest.cycle_ordinal AS latest_cycle_ordinal,
                       latest.cycle_attempt_ordinal AS latest_cycle_attempt_ordinal,
                       latest.failure_reason AS latest_failure_reason
                FROM daily_tracks.tracks AS track
                LEFT JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                LEFT JOIN daily_tracks.session_checkpoints AS head
                  ON head.track_id = state.track_id
                 AND head.manifest_sha256 = state.current_checkpoint_manifest_sha256
                LEFT JOIN LATERAL (
                    SELECT progression.id, progression.status,
                           progression.target_sessions,
                           progression.target_start_session,
                           progression.target_end_session,
                           progression.current_cycle_ordinal,
                           progression.next_attempt_eligible_at,
                           progression.queue_position,
                           progression.created_at,
                           progression.finished_at
                    FROM daily_tracks.session_progressions AS progression
                    WHERE progression.track_id = track.id
                    ORDER BY
                        (progression.status IN ('running', 'stopping', 'blocked')) DESC,
                        progression.created_at DESC,
                        progression.id DESC
                    LIMIT 1
                ) AS advance ON true
                LEFT JOIN LATERAL (
                    SELECT attempt.status, attempt.execution_phase,
                           attempt.current_session, attempt.cycle_ordinal,
                           attempt.cycle_attempt_ordinal, attempt.failure_reason
                    FROM daily_tracks.session_progression_attempts AS attempt
                    WHERE attempt.progression_id = advance.id
                    ORDER BY attempt.ordinal DESC, attempt.id DESC
                    LIMIT 1
                ) AS latest ON true
                WHERE track.id = %s
                """,
                (track_id,),
            ).fetchone()
            if track is None:
                raise DailyTrackDiagnosticNotFound
            progression_id = track.get("advance_id")
            attempts = (
                []
                if progression_id is None
                else transaction.execute(
                    """
                    SELECT attempt.id, attempt.ordinal,
                           attempt.cycle_ordinal,
                           attempt.cycle_attempt_ordinal,
                           attempt.status, attempt.execution_phase,
                           attempt.current_session,
                           attempt.started_at, attempt.finished_at,
                           attempt.heartbeat_at, attempt.lease_expires_at,
                           attempt.failure_reason
                    FROM daily_tracks.session_progression_attempts AS attempt
                    WHERE attempt.progression_id = %s
                    ORDER BY attempt.ordinal, attempt.id
                    """,
                    (progression_id,),
                ).fetchall()
            )
        return _snapshot(track, attempts)


def _snapshot(
    track: Mapping[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, object]:
    diagnosed_at = _required_datetime(track["diagnosed_at"])
    advance_present = track.get("advance_id") is not None
    head_present = track.get("head_session") is not None
    latest = attempts[-1] if attempts else None
    retry_eligible = bool(
        advance_present
        and str(track["advance_status"]) == "running"
        and latest is not None
        and latest["status"] == "failed"
        and tracking_attempt_retry_eligible(
            latest.get("failure_reason"),
            int(latest["cycle_attempt_ordinal"]),
        )
    )
    retry_at = (
        _optional_timestamp(track.get("next_attempt_eligible_at"))
        if retry_eligible
        else None
    )
    attempts_value = [
        _attempt(
            row,
            diagnosed_at=diagnosed_at,
            retry_at=(retry_at if index == len(attempts) - 1 else None),
        )
        for index, row in enumerate(attempts)
    ]
    advance_checkpoint_present = bool(track["advance_checkpoint_present"])
    return {
        "schema": "daily_track_diagnostic",
        "diagnosed_at": _timestamp(diagnosed_at),
        "track": {
            "id": str(track["track_id"]),
            "seed_run_id": str(track["seed_run_id"]),
            "status": str(track["track_status"]),
        },
        "head": {
            "present": head_present,
            "origin_session": _optional_date(track.get("origin_session")),
            "session": _optional_date(track.get("head_session")),
            "updated_at": _optional_timestamp(track.get("head_updated_at")),
        },
        "advance": (
            _advance(
                track,
                retry_eligible=retry_eligible,
                retry_at=retry_at,
                checkpoint_present=advance_checkpoint_present,
            )
            if advance_present
            else None
        ),
        "progress": _progress(track, head_present=head_present),
        "recovery": _recovery(
            track,
            latest=latest,
            diagnosed_at=diagnosed_at,
            retry_eligible=retry_eligible,
            retry_at=retry_at,
        ),
        "private_artifacts": {
            "head_checkpoint_present": head_present,
            "advance_checkpoint_present": advance_checkpoint_present,
        },
        "publication": {
            "state": (
                "advance_published"
                if advance_checkpoint_present
                else "head_published" if head_present else "unpublished"
            ),
            "head_checkpoint_present": head_present,
            "advance_checkpoint_present": advance_checkpoint_present,
        },
        "attempts": attempts_value,
    }


def _advance(
    row: Mapping[str, Any],
    *,
    retry_eligible: bool,
    retry_at: str | None,
    checkpoint_present: bool,
) -> dict[str, object]:
    return {
        "id": str(row["advance_id"]),
        "status": str(row["advance_status"]),
        "target": {
            "start_session": _required_date(row["target_start_session"]),
            "end_session": _required_date(row["target_end_session"]),
            "session_count": int(row["target_session_count"]),
        },
        "cycle": {
            "ordinal": _optional_int(row.get("current_cycle_ordinal")),
            "attempt": _optional_int(row.get("latest_cycle_attempt_ordinal")),
            "attempt_limit": MAX_TRACKING_CYCLE_ATTEMPTS,
        },
        "queue_position": _optional_int(row.get("queue_position")),
        "retry_eligible": retry_eligible,
        "retry_at": retry_at,
        "blocked": {
            "present": str(row["advance_status"]) == "blocked",
            "reason_code": _blocked_reason_code(row.get("blocked_reason")),
        },
        "checkpoint_present": checkpoint_present,
        "created_at": _timestamp(_required_datetime(row["advance_created_at"])),
        "finished_at": _optional_timestamp(row.get("advance_finished_at")),
    }


def _progress(row: Mapping[str, Any], *, head_present: bool) -> dict[str, object]:
    advance_present = row.get("advance_id") is not None
    latest_status = row.get("latest_attempt_status")
    next_attempt = row.get("next_attempt_eligible_at")
    diagnosed_at = _required_datetime(row["diagnosed_at"])
    if row["track_status"] == "stopping":
        phase = "stopping"
    elif row["track_status"] == "stopped":
        phase = "stopped"
    elif not advance_present:
        phase = "idle"
    elif row["advance_status"] == "blocked":
        phase = "blocked"
    elif latest_status in {"running", "stopping"}:
        phase = str(row["latest_attempt_phase"])
    elif isinstance(next_attempt, datetime) and next_attempt > diagnosed_at:
        phase = "retry_wait"
    elif row["advance_status"] == "running":
        phase = "queued"
    elif row["advance_status"] == "succeeded":
        phase = "published"
    else:
        phase = "stopped"
    return {
        "phase": phase,
        "head_session": _optional_date(row.get("head_session")) if head_present else None,
        "target_start_session": (
            _optional_date(row.get("target_start_session")) if advance_present else None
        ),
        "target_end_session": (
            _optional_date(row.get("target_end_session")) if advance_present else None
        ),
        "target_session_count": (
            int(row["target_session_count"]) if advance_present else 0
        ),
        "completed_target_sessions": (
            int(row["target_session_count"])
            if advance_present and bool(row["advance_checkpoint_present"])
            else 0
        ),
        "current_session": (
            _optional_date(row.get("latest_current_session"))
            if latest_status in {"running", "stopping"}
            else None
        ),
    }


def _attempt(
    row: Mapping[str, Any],
    *,
    diagnosed_at: datetime,
    retry_at: str | None,
) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "ordinal": int(row["ordinal"]),
        "cycle_ordinal": int(row["cycle_ordinal"]),
        "cycle_attempt_ordinal": int(row["cycle_attempt_ordinal"]),
        "status": str(row["status"]),
        "phase": str(row["execution_phase"]),
        "current_session": _optional_date(row.get("current_session")),
        "started_at": _timestamp(_required_datetime(row["started_at"])),
        "finished_at": _optional_timestamp(row.get("finished_at")),
        "heartbeat_at": _timestamp(_required_datetime(row["heartbeat_at"])),
        "lease_expires_at": _timestamp(_required_datetime(row["lease_expires_at"])),
        "lease_state": _lease_state(row, diagnosed_at=diagnosed_at),
        "retry_at": retry_at,
        "failure_code": tracking_attempt_failure_code(row.get("failure_reason")),
    }


def _recovery(
    track: Mapping[str, Any],
    *,
    latest: Mapping[str, Any] | None,
    diagnosed_at: datetime,
    retry_eligible: bool,
    retry_at: str | None,
) -> dict[str, object]:
    if track["track_status"] == "stopping":
        state = "stopping"
    elif track["track_status"] == "stopped":
        state = "not_applicable"
    elif track["track_status"] == "blocked":
        state = "blocked"
    elif retry_eligible:
        eligible_at = track.get("next_attempt_eligible_at")
        state = (
            "retry_wait"
            if isinstance(eligible_at, datetime) and eligible_at > diagnosed_at
            else "retry_ready"
        )
    elif latest is not None and latest["status"] in {"running", "stopping"}:
        state = (
            "active"
            if _lease_state(latest, diagnosed_at=diagnosed_at) == "current"
            else "lease_expired"
        )
    else:
        state = "idle"
    return {
        "state": state,
        "retry_eligible": retry_eligible,
        "retry_at": retry_at,
        "failure_code": tracking_attempt_failure_code(
            None if latest is None else latest.get("failure_reason")
        ),
    }


def _lease_state(row: Mapping[str, Any], *, diagnosed_at: datetime) -> str:
    lease_expires_at = _required_datetime(row["lease_expires_at"])
    return "current" if lease_expires_at > diagnosed_at else "expired"


def _blocked_reason_code(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return "UNCLASSIFIED_BLOCK"
    return _BLOCKED_REASON_CODES.get(value, "UNCLASSIFIED_BLOCK")


def _required_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("DailyTrack diagnostic timestamp is invalid")
    return value


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _optional_timestamp(value: object) -> str | None:
    return None if value is None else _timestamp(_required_datetime(value))


def _required_date(value: object) -> str:
    if not isinstance(value, date):
        raise ValueError("DailyTrack diagnostic date is invalid")
    return value.isoformat()


def _optional_date(value: object) -> str | None:
    return None if value is None else _required_date(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


__all__ = ("DailyTrackDiagnosticNotFound", "DailyTrackDiagnostics")
