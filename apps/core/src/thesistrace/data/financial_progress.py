from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from thesistrace._postgres import PostgresTransaction


class FinancialDiscoveryGapStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["年报", "半年报", "一季报", "三季报", "补充更正"]
    start_date: date
    end_date: date
    failure_code: Literal["CNINFO_DISCOVERY_UNAVAILABLE", "CNINFO_DISCOVERY_INVALID"]


class FinancialRefreshProgress(BaseModel):
    """Diagnostic projection, never a publication or recovery authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: Literal["queued", "preparing", "discovery", "collection", "publication", "finished"]
    elapsed_seconds: int | None = Field(ge=0)
    last_progress_at: datetime | None
    discovered_announcement_count: int | None = Field(ge=0)
    processed_company_count: int | None = Field(ge=0)
    updated_company_count: int | None = Field(ge=0)
    unchanged_company_count: int | None = Field(ge=0)
    failed_company_count: int | None = Field(ge=0)
    discovery_gaps: tuple[FinancialDiscoveryGapStatus, ...] | None = Field(max_length=5)


def read_financial_progress(
    transaction: PostgresTransaction,
    operations: Sequence[dict[str, object]],
) -> dict[str, FinancialRefreshProgress]:
    """Aggregate only the requested receipts; never load raw statements or checkpoints.

    Use operation-scoped immutable discovery evidence, not the mutable global gap
    or trigger tables. Later refreshes must not rewrite a historical receipt.
    A missing private operation means unknown telemetry, not zero companies.
    """
    financial = {
        str(row["idempotency_key"]): row for row in operations if row["kind"] == "financial"
    }
    if not financial:
        return {}
    rows = transaction.execute(
        """
        SELECT requested.key, statement_timestamp() AS observed_at,
               f.idempotency_key IS NOT NULL AS available,
               f.discovery_evidence IS NOT NULL AS discovered,
               f.candidate_manifest_sha256 IS NOT NULL AS candidate_ready,
               greatest(f.updated_at, a.last_checkpoint_at) AS last_progress_at,
               jsonb_array_length(f.discovery_evidence->'announcements') AS announcements,
               f.discovery_evidence->'gaps' AS gaps,
               a.processed, a.changed, a.unchanged, a.failed
        FROM unnest(%s::text[]) AS requested(key)
        LEFT JOIN data.financial_daily_refresh_operations AS f
          ON f.idempotency_key = requested.key
        LEFT JOIN LATERAL (
            SELECT count(*) AS processed,
                   count(*) FILTER (WHERE status = 'accepted'
                       AND jsonb_array_length(matched_announcement_ids) > 0) AS changed,
                   count(*) FILTER (WHERE status = 'accepted'
                       AND jsonb_array_length(matched_announcement_ids) = 0) AS unchanged,
                   count(*) FILTER (WHERE status = 'failed') AS failed,
                   max(attempted_at) AS last_checkpoint_at
            FROM data.financial_refresh_instrument_attempts
            WHERE idempotency_key = requested.key
        ) AS a ON true
        """,
        (list(financial),),
    ).fetchall()
    progress: dict[str, FinancialRefreshProgress] = {}
    for row in rows:
        operation = financial[str(row["key"])]
        status = operation["status"]
        terminal = status in {"succeeded", "failed", "cancelled"}
        started = operation["started_at"]
        finished = operation["finished_at"]
        observed = finished if terminal else row["observed_at"]
        elapsed = (
            max(0, int((observed - started).total_seconds()))
            if isinstance(started, datetime) and isinstance(observed, datetime)
            else None
        )
        phase = (
            "finished"
            if terminal
            else "queued"
            if status == "accepted"
            else "preparing"
            if not row["available"]
            else "discovery"
            if not row["discovered"]
            else "publication"
            if row["candidate_ready"]
            else "collection"
        )
        progress[str(row["key"])] = FinancialRefreshProgress(
            phase=phase,
            elapsed_seconds=elapsed,
            last_progress_at=finished if terminal else row["last_progress_at"],
            discovered_announcement_count=row["announcements"],
            processed_company_count=row["processed"] if row["available"] else None,
            updated_company_count=row["changed"] if row["available"] else None,
            unchanged_company_count=row["unchanged"] if row["available"] else None,
            failed_company_count=row["failed"] if row["available"] else None,
            discovery_gaps=(
                tuple(FinancialDiscoveryGapStatus.model_validate(gap) for gap in row["gaps"])
                if row["gaps"] is not None
                else None
            ),
        )
    return progress
