"""Read-only Core quota totals; usage stays with the execution owner."""

from uuid import UUID

from thesistrace._postgres import PostgresDatabase
from thesistrace.researcher.quota import QuotaPolicy


def run_usage(database: PostgresDatabase, researcher_id: UUID, policy: QuotaPolicy) -> dict:
    with database.transaction() as tx:
        usage = tx.execute(
            """
            SELECT count(*) FILTER (WHERE quota_state='consumed') actual,
                   count(*) FILTER (WHERE quota_state='reserved') reserved,
                   (date_trunc('day',now() AT TIME ZONE %s)+interval '1 day')
                     AT TIME ZONE %s resets_at
            FROM research_runs.run_ownership WHERE researcher_id=%s
              AND created_at >= date_trunc('day',now() AT TIME ZONE %s) AT TIME ZONE %s
              AND created_at < (date_trunc('day',now() AT TIME ZONE %s)
                               +interval '1 day') AT TIME ZONE %s
            """,
            (
                policy.timezone,
                policy.timezone,
                researcher_id,
                policy.timezone,
                policy.timezone,
                policy.timezone,
                policy.timezone,
            ),
        ).fetchone()
    limit = policy.daily_run_limit
    return dict(
        timezone=policy.timezone,
        resets_at=usage["resets_at"].isoformat(),
        research=dict(
            actual=usage["actual"],
            reserved=usage["reserved"],
            limit=limit,
            remaining=None
            if limit is None
            else max(0, limit - usage["actual"] - usage["reserved"]),
        ),
    )
