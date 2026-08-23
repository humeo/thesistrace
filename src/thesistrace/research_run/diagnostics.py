from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from thesistrace._postgres import PostgresDatabase
from thesistrace.research_run.failure_policy import (
    attempt_failure_code,
    attempt_retry_eligible,
)


class ResearchRunDiagnosticNotFound(LookupError):
    pass


class ResearchRunDiagnostics:
    """Private PostgreSQL-only diagnostic reader owned by ResearchRun."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def inspect(self, run_id: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            transaction.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            run = transaction.execute(
                """
                SELECT transaction_timestamp() AS diagnosed_at,
                       run.id AS run_id,
                       run.immutable_input->>'research_kind' AS research_kind,
                       run.status AS run_status,
                       run.failure_reason AS run_failure_reason,
                       run.result_manifest_sha256 IS NOT NULL AS result_bundle_present,
                       progress.phase AS progress_phase,
                       progress.completed_warmup_sessions,
                       progress.total_warmup_sessions,
                       progress.completed_research_sessions,
                       progress.total_research_sessions,
                       progress.committed_chunk_count,
                       progress.last_completed_warmup_session,
                       progress.last_completed_research_session,
                       progress.remaining_duration_estimate_seconds,
                       progress.updated_at AS progress_updated_at,
                       EXISTS (
                           SELECT 1
                           FROM research_runs.execution_checkpoints AS checkpoint
                           WHERE checkpoint.run_id = run.id
                       ) AS checkpoint_present
                FROM research_runs.runs AS run
                LEFT JOIN research_runs.progress AS progress ON progress.run_id = run.id
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise ResearchRunDiagnosticNotFound
            attempts = transaction.execute(
                """
                SELECT attempt.id, attempt.ordinal, attempt.status,
                       attempt.started_at, attempt.finished_at,
                       attempt.heartbeat_at, attempt.lease_expires_at,
                       attempt.failure_reason,
                       checkpoint.phase AS checkpoint_phase
                FROM research_runs.attempts AS attempt
                LEFT JOIN LATERAL (
                    SELECT execution.phase
                    FROM research_runs.execution_checkpoints AS execution
                    WHERE execution.attempt_id = attempt.id
                    ORDER BY execution.ordinal DESC
                    LIMIT 1
                ) AS checkpoint ON true
                WHERE attempt.run_id = %s
                ORDER BY attempt.ordinal, attempt.id
                """,
                (run_id,),
            ).fetchall()
        return _snapshot(run, attempts)


def _snapshot(
    run: Mapping[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, object]:
    diagnosed_at = _required_datetime(run["diagnosed_at"])
    progress_present = run.get("progress_phase") is not None
    attempt_values = [
        _attempt(
            row,
            diagnosed_at=diagnosed_at,
            current_phase=(
                str(run["progress_phase"])
                if (
                    progress_present
                    and index == len(attempts) - 1
                    and row["status"] in {"running", "cancelling"}
                )
                else None
            ),
        )
        for index, row in enumerate(attempts)
    ]
    latest = attempts[-1] if attempts else None
    result_bundle_present = bool(run["result_bundle_present"])
    return {
        "schema": "research_run_diagnostic",
        "diagnosed_at": _timestamp(diagnosed_at),
        "run": {
            "id": str(run["run_id"]),
            "research_kind": str(run["research_kind"]),
            "status": str(run["run_status"]),
            "current_phase": (
                str(run["progress_phase"]) if progress_present else None
            ),
            "failure_code": attempt_failure_code(run.get("run_failure_reason")),
        },
        "progress": {
            "present": progress_present,
            "phase": str(run["progress_phase"]) if progress_present else None,
            "completed_warmup_sessions": _optional_int(
                run.get("completed_warmup_sessions")
            ),
            "total_warmup_sessions": _optional_int(run.get("total_warmup_sessions")),
            "completed_research_sessions": _optional_int(
                run.get("completed_research_sessions")
            ),
            "total_research_sessions": _optional_int(
                run.get("total_research_sessions")
            ),
            "committed_chunk_count": _optional_int(run.get("committed_chunk_count")),
            "last_completed_warmup_session": _optional_date(
                run.get("last_completed_warmup_session")
            ),
            "last_completed_research_session": _optional_date(
                run.get("last_completed_research_session")
            ),
            "remaining_duration_estimate_seconds": _optional_int(
                run.get("remaining_duration_estimate_seconds")
            ),
            "updated_at": _optional_timestamp(run.get("progress_updated_at")),
        },
        "recovery": _recovery(
            run_status=str(run["run_status"]),
            latest=latest,
            diagnosed_at=diagnosed_at,
        ),
        "private_artifacts": {
            "checkpoint_present": bool(run["checkpoint_present"]),
            "result_bundle_present": result_bundle_present,
        },
        "publication": {
            "state": "published" if result_bundle_present else "unpublished",
            "result_bundle_present": result_bundle_present,
        },
        "attempts": attempt_values,
    }


def _attempt(
    row: Mapping[str, Any],
    *,
    diagnosed_at: datetime,
    current_phase: str | None,
) -> dict[str, object]:
    status = str(row["status"])
    checkpoint_phase = row.get("checkpoint_phase")
    return {
        "id": str(row["id"]),
        "ordinal": int(row["ordinal"]),
        "status": status,
        "phase": (
            current_phase
            if current_phase is not None
            else str(checkpoint_phase) if checkpoint_phase is not None else None
        ),
        "started_at": _timestamp(_required_datetime(row["started_at"])),
        "finished_at": _optional_timestamp(row.get("finished_at")),
        "heartbeat_at": _timestamp(_required_datetime(row["heartbeat_at"])),
        "lease_expires_at": _timestamp(_required_datetime(row["lease_expires_at"])),
        "lease_state": _lease_state(row, diagnosed_at=diagnosed_at),
        "retry_at": None,
        "failure_code": attempt_failure_code(row.get("failure_reason")),
    }


def _lease_state(row: Mapping[str, Any], *, diagnosed_at: datetime) -> str:
    lease_expires_at = _required_datetime(row["lease_expires_at"])
    return "current" if lease_expires_at > diagnosed_at else "expired"


def _recovery(
    *,
    run_status: str,
    latest: Mapping[str, Any] | None,
    diagnosed_at: datetime,
) -> dict[str, object]:
    latest_reason = None if latest is None else latest.get("failure_reason")
    retry_eligible = bool(
        run_status == "running"
        and latest is not None
        and latest["status"] == "failed"
        and attempt_retry_eligible(latest_reason, int(latest["ordinal"]))
    )
    if run_status == "queued" and latest is None:
        state = "awaiting_attempt"
    elif retry_eligible:
        state = "retry_pending"
    elif run_status == "cancelling":
        state = "cancellation_pending"
    elif latest is not None and latest["status"] in {"running", "cancelling"}:
        state = (
            "active"
            if _lease_state(latest, diagnosed_at=diagnosed_at) == "current"
            else "lease_expired"
        )
    elif run_status in {"succeeded", "failed", "cancelled"}:
        state = "not_applicable"
    else:
        state = "none"
    return {
        "state": state,
        "retry_eligible": retry_eligible,
        "retry_at": None,
        "failure_code": attempt_failure_code(latest_reason),
    }


def _required_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("ResearchRun diagnostic timestamp is invalid")
    return value


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _optional_timestamp(value: object) -> str | None:
    return None if value is None else _timestamp(_required_datetime(value))


def _optional_date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, date):
        raise ValueError("ResearchRun diagnostic date is invalid")
    return value.isoformat()


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


__all__ = ("ResearchRunDiagnosticNotFound", "ResearchRunDiagnostics")
