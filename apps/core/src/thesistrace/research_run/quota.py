"""Count durable ResearchRun admissions, including retained deleted ownership."""

from uuid import UUID

from thesistrace._postgres import PostgresTransaction


def daily_run_count(transaction: PostgresTransaction, researcher_id: UUID, timezone: str) -> int:
    # All admissions, including Batch children, acquire this lock before insertion.
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"researcher.daily_run_quota:{researcher_id}",),
    ).fetchone()
    row = transaction.execute(
        """
        SELECT count(*) AS count FROM research_runs.run_ownership
        WHERE researcher_id = %s
          AND created_at >= date_trunc('day', now() AT TIME ZONE %s)
                            AT TIME ZONE %s
          AND created_at < (date_trunc('day', now() AT TIME ZONE %s)
                            + interval '1 day') AT TIME ZONE %s
        """,
        (researcher_id, timezone, timezone, timezone, timezone),
    ).fetchone()
    assert row is not None
    return int(row["count"])
