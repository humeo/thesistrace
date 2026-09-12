"""Indicator-specific disclosure targets and reconciliation progress."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from thesistrace._postgres import PostgresDatabase, PostgresTransaction


class FinancialIndicatorProgressStore:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def require_report(
        self,
        instrument_id: str,
        *,
        report_period: str | None,
        announced_on: str,
    ) -> None:
        with self._database.transaction() as tx:
            require_indicator_report(
                tx, instrument_id, report_period=report_period, announced_on=announced_on
            )

    def record_reconciliation(
        self,
        instrument_id: str,
        *,
        checked_through: str,
        observed_reports: Sequence[tuple[str, str]],
        observation_sha256: str,
    ) -> None:
        """Record an exhausted, validated source query; absent targets remain pending.

        The collector supplies only unambiguous, valid announcement/report pairs
        from its retained observations. Statement collection never calls this.
        """
        checked = date.fromisoformat(checked_through)
        reports = [
            (date.fromisoformat(period), date.fromisoformat(announced))
            for period, announced in observed_reports
        ]
        if any(period > announced or announced > checked for period, announced in reports):
            raise ValueError("Invalid indicator reconciliation report dates")
        with self._database.transaction() as tx:
            tx.execute(
                """INSERT INTO data.financial_indicator_reconciliation
                          (instrument_id, checked_through, observation_sha256) VALUES (%s, %s, %s)
                          ON CONFLICT (instrument_id) DO UPDATE
                          SET checked_through=EXCLUDED.checked_through,
                              observation_sha256=EXCLUDED.observation_sha256
                          WHERE financial_indicator_reconciliation.checked_through
                                < EXCLUDED.checked_through""",
                (instrument_id, checked, observation_sha256),
            )
            tx.execute(
                """INSERT INTO data.financial_indicator_collections
                   (observation_sha256, instrument_id, checked_through) VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (observation_sha256, instrument_id, checked),
            )
            for period, announced in reports:
                tx.execute(
                    """UPDATE data.financial_indicator_report_targets
                              SET resolved_observation_sha256=%s
                              WHERE instrument_id=%s AND report_period=%s AND announced_on<=%s
                                AND resolved_observation_sha256 IS NULL""",
                    (observation_sha256, instrument_id, period, announced),
                )

    def pending(self, instrument_id: str) -> tuple[tuple[str | None, str], ...]:
        with self._database.transaction() as tx:
            rows = tx.execute(
                """SELECT report_period, announced_on
                                 FROM data.financial_indicator_report_targets
                                 WHERE instrument_id=%s AND resolved_observation_sha256 IS NULL
                                 ORDER BY report_period, announced_on""",
                (instrument_id,),
            ).fetchall()
        return tuple(
            (
                None if row["report_period"] is None else row["report_period"].isoformat(),
                row["announced_on"].isoformat(),
            )
            for row in rows
        )

    def reconciled_through(self, instrument_id: str) -> str | None:
        with self._database.transaction() as tx:
            row = tx.execute(
                """SELECT checked_through FROM data.financial_indicator_reconciliation
                                WHERE instrument_id=%s""",
                (instrument_id,),
            ).fetchone()
        return None if row is None else row["checked_through"].isoformat()


def require_indicator_report(
    transaction: PostgresTransaction,
    instrument_id: str,
    *,
    report_period: str | None,
    announced_on: str,
) -> None:
    """Persist a source-specific target alongside the discovery transaction."""
    period = None if report_period is None else date.fromisoformat(report_period)
    announcement = date.fromisoformat(announced_on)
    if period is not None and period > announcement:
        raise ValueError("Report cannot be announced before its period ends")
    transaction.execute(
        """INSERT INTO data.financial_indicator_report_targets
                  (instrument_id, report_period, announced_on) VALUES (%s, %s, %s)
                  ON CONFLICT DO NOTHING""",
        (instrument_id, period, announcement),
    )
