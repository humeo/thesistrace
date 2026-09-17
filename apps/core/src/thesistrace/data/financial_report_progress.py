"""Persist expected report periods independently of report publication timestamps."""

from datetime import date


def require_report(tx, instrument_id, endpoint, report_period, actual_date):
    period, actual = date.fromisoformat(report_period), date.fromisoformat(actual_date)
    if period > actual:
        raise ValueError("Report cannot be disclosed before its period ends")
    tx.execute(
        """INSERT INTO data.financial_report_targets
           (instrument_id, endpoint, report_period, actual_date) VALUES (%s, %s, %s, %s)
           ON CONFLICT (instrument_id, endpoint, report_period) DO UPDATE
           SET actual_date=LEAST(financial_report_targets.actual_date, EXCLUDED.actual_date)""",
        (instrument_id, endpoint, period, actual),
    )


def resolve_reports(tx, instrument_id, endpoint, periods, evidence):
    tx.execute(
        """UPDATE data.financial_report_targets SET resolved_evidence_sha256=%s
           WHERE instrument_id=%s AND endpoint=%s AND report_period=ANY(%s::date[])""",
        (evidence, instrument_id, endpoint, sorted(set(periods))),
    )


def record_recheck(tx, instrument_id, endpoint, failure_code=None):
    tx.execute(
        """INSERT INTO data.financial_report_rechecks
           (instrument_id, endpoint, checked_at, failure_code)
           VALUES (%s, %s, clock_timestamp(), %s)
           ON CONFLICT (instrument_id, endpoint) DO UPDATE
           SET checked_at=EXCLUDED.checked_at, failure_code=EXCLUDED.failure_code""",
        (instrument_id, endpoint, failure_code),
    )


def reconciliation_ids(tx, identities, endpoint, *, limit=64, exclude=frozenset()):
    """Oldest successfully or unsuccessfully checked first; no session-index starvation."""
    rows = tx.execute(
        """SELECT ids.instrument_id, progress.failure_code
           FROM unnest(%s::text[]) AS ids(instrument_id)
           LEFT JOIN data.financial_report_rechecks progress
             ON progress.instrument_id=ids.instrument_id AND progress.endpoint=%s
           ORDER BY progress.checked_at ASC NULLS FIRST, ids.instrument_id""",
        (list(identities), endpoint),
    ).fetchall()
    return tuple(
        dict.fromkeys(
            [
                *(str(row["instrument_id"]) for row in rows if row["failure_code"] is not None),
                *(
                    str(row["instrument_id"])
                    for row in [row for row in rows if row["instrument_id"] not in exclude][:limit]
                ),
            ]
        )
    )
