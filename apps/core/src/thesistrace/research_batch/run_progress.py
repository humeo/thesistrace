from __future__ import annotations

from datetime import datetime
from uuid import UUID

from thesistrace._postgres import PostgresTransaction
from thesistrace.research_batch.service import _live_progress
from thesistrace.research_run.models import ResearchRunExecutionTiming, ResearchRunProgress


def project_batch_run_execution(
    transaction: PostgresTransaction,
    researcher_id: UUID,
    run_id: str,
    run_status: str,
    progress: ResearchRunProgress,
) -> tuple[ResearchRunProgress, ResearchRunExecutionTiming]:
    """Project Batch-owned work without making live slices recovery checkpoints."""
    item = transaction.execute(
        """
        SELECT item.batch_id, item.item_key, item.dependency_role, item.outcome,
               batch.status AS batch_status, timing.started_at, timing.finished_at,
               CURRENT_TIMESTAMP AS observed_at
        FROM research_batches.items AS item
        JOIN research_batches.batches AS batch ON batch.id = item.batch_id
        LEFT JOIN LATERAL (
            SELECT min(task.started_at) FILTER (
                       WHERE task.item_ordinal = item.ordinal
                          OR (item.dependency_role = 'strategy'
                              AND task.task_role = 'shared_alpha_factor')
                          OR (item.dependency_role = 'factor' AND task.task_role = 'factor')
                   ) AS started_at,
                   max(task.finished_at) FILTER (
                       WHERE task.item_ordinal = item.ordinal
                          OR (item.dependency_role = 'strategy'
                              AND task.task_role = 'shared_alpha_factor')
                   ) AS finished_at
            FROM research_batches.task_attempts AS task
            WHERE task.batch_id = item.batch_id
        ) AS timing ON true
        WHERE item.researcher_id = %s AND item.research_run_id = %s
          AND item.run_deleted_at IS NULL
        """,
        (researcher_id, run_id),
    ).fetchone()
    if item is None:
        raise RuntimeError("Batch-owned Run membership is missing")

    terminal = run_status in {"succeeded", "failed", "cancelled"}
    started_at = item["started_at"]
    finished_at = item["finished_at"] if terminal else None
    endpoint = finished_at if terminal else item["observed_at"]
    timing = ResearchRunExecutionTiming(
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=(
            max(0.0, (endpoint - started_at).total_seconds())
            if isinstance(started_at, datetime) and isinstance(endpoint, datetime)
            else None
        ),
        is_final=terminal,
    )
    if item["outcome"] == "succeeded":
        return progress.model_copy(update={
            "phase": "succeeded",
            "completed_warmup_sessions": progress.total_warmup_sessions,
            "completed_research_sessions": progress.total_research_sessions,
            "remaining_duration_estimate_seconds": None,
            "duration_is_estimate": False,
        }), timing
    if terminal or run_status == "queued":
        return progress, timing

    attempt = transaction.execute(
        """
        SELECT status, ordinal, lease_expires_at, current_task_role, current_item_key,
               current_phase, completed_research_sessions, total_research_sessions,
               task_started_at, live_progress_updated_at, CURRENT_TIMESTAMP AS observed_at
        FROM research_batches.attempts
        WHERE batch_id = %s
        ORDER BY ordinal DESC
        LIMIT 1
        """,
        (item["batch_id"],),
    ).fetchone()
    live = _live_progress(attempt, str(item["batch_status"]))
    phase = "recovering"
    completed = 0
    warmup_complete = False
    remaining = None
    if live is not None:
        if live.task_role == "preparation":
            phase = "preparing_data"
        elif live.task_role == "shared_alpha_factor":
            phase = "shared_alpha_factor"
            completed = live.completed_research_sessions or 0
            warmup_complete = completed > 0
            remaining = live.remaining_duration_estimate_seconds
        elif live.item_key == item["item_key"] or live.task_role == "factor":
            # Factor items advance together on shared slices. Strategies advance
            # individually after their shared Alpha-and-Factor prerequisite.
            phase = "strategy" if live.task_role == "strategy" else "research"
            completed = live.completed_research_sessions or 0
            if live.phase == "finalizing":
                phase = "finalizing"
                completed = progress.total_research_sessions
            warmup_complete = completed > 0 or live.task_role == "strategy"
            remaining = live.remaining_duration_estimate_seconds
        else:
            phase = "waiting_for_execution"
    projected = ResearchRunProgress.model_validate({
        **progress.model_dump(),
        "phase": phase,
        "completed_warmup_sessions": progress.total_warmup_sessions if warmup_complete else 0,
        "completed_research_sessions": completed,
        "remaining_duration_estimate_seconds": remaining,
    })
    return projected, timing
