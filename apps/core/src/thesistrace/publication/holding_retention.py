"""Seven-day idle retention for immutable Daily Holding Observation units."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TypeVar
from uuid import UUID

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.publication.service import PreparedPublication, Publication, PublishedRef

T = TypeVar("T")
HOLDING_KIND = "daily-holding.observations"


class HoldingRetention:
    def __init__(self, database: PostgresDatabase, publication: Publication) -> None:
        self._database = database
        self._publication = publication

    def record(
        self, transaction: PostgresTransaction, *, unit_id: str, researcher_id: UUID,
        source_kind: str, source_id: str, sessions: list[str], prepared: PreparedPublication,
    ) -> dict:
        if (not sessions or sessions != sorted(set(sessions))
                or source_kind not in {"research_run", "daily_track"}):
            raise ValueError("Holding retention source or coverage is invalid")
        first, last = date.fromisoformat(sessions[0]), date.fromisoformat(sessions[-1])
        reference = self._publication.record(transaction, prepared)
        if (reference.kind != HOLDING_KIND
                or reference.provenance.get("holding_unit_id") != unit_id):
            raise ValueError("Holding publication identity is invalid")
        return transaction.execute(
            "INSERT INTO publication.holding_units "
            "(id, researcher_id, source_kind, source_id, first_session, last_session, "
            "manifest_sha256, provenance, published_at, expires_at) "
            "SELECT %s, %s, %s, %s, %s, %s, %s, %s, observed_at, "
            "observed_at + interval '7 days' FROM (SELECT clock_timestamp() AS observed_at) t "
            "RETURNING *",
            (unit_id, researcher_id, source_kind, source_id, first, last,
             reference.manifest_sha256, Jsonb(reference.provenance)),
        ).fetchone()

    def inspect(self, researcher_id: UUID, unit_id: str) -> dict | None:
        """Metadata inspection never renews access or reads payload bodies."""
        with self._database.transaction() as transaction:
            row = self._unit(transaction, researcher_id, unit_id, lock=False)
            return self._metadata(row) if row is not None else None

    def list_units(
        self, researcher_id: UUID, *, sources: list[tuple[str, str]], boundary: str,
        start_session: str | None = None, end_session: str | None = None,
        after: tuple[str, str] | None = None, limit: int = 20,
    ) -> tuple[list[dict], tuple[str, str] | None, bool]:
        """List source-owned metadata through a caller-authorized fixed publication boundary."""
        if not 1 <= len(sources) <= 2 or not 1 <= limit <= 50:
            raise ValueError("Holding metadata source/page bound is invalid")
        clauses = ["researcher_id = %s", "last_session <= %s"]
        parameters = [researcher_id, date.fromisoformat(boundary)]
        clauses.append("(" + " OR ".join(
            "(source_kind = %s AND source_id = %s)" for _ in sources
        ) + ")")
        for kind, source_id in sources:
            if kind not in {"research_run", "daily_track"} or not source_id:
                raise ValueError("Holding metadata source is invalid")
            parameters.extend((kind, source_id))
        source_clauses, source_parameters = list(clauses), tuple(parameters)
        if start_session is not None:
            clauses.append("last_session >= %s")
            parameters.append(date.fromisoformat(start_session))
        if end_session is not None:
            clauses.append("first_session <= %s")
            parameters.append(date.fromisoformat(end_session))
        if after is not None:
            clauses.append("(first_session, id) > (%s, %s)")
            parameters.extend((date.fromisoformat(after[0]), after[1]))
        parameters.append(limit + 1)
        with self._database.transaction() as transaction:
            recorded = transaction.execute(
                "SELECT 1 FROM publication.holding_units WHERE "
                + " AND ".join(source_clauses) + " LIMIT 1", source_parameters,
            ).fetchone() is not None
            rows = transaction.execute(
                "SELECT *, clock_timestamp() AS observed_at FROM publication.holding_units WHERE "
                + " AND ".join(clauses) + " ORDER BY first_session, id LIMIT %s",
                tuple(parameters),
            ).fetchall()
        next_after = ((rows[limit - 1]["first_session"].isoformat(), rows[limit - 1]["id"])
                      if len(rows) > limit else None)
        return [self._metadata(row) for row in rows[:limit]], next_after, recorded

    def read_detail(
        self, researcher_id: UUID, unit_id: str,
        read: Callable[[PostgresTransaction, PublishedRef], T],
    ) -> tuple[dict, T | None] | None:
        """Lock admission through verified bounded I/O; failed reads cannot renew."""
        with self._database.transaction() as transaction:
            row = self._unit(transaction, researcher_id, unit_id, lock=True)
            if row is None:
                return None
            metadata = self._metadata(row)
            if metadata["status"] == "expired":
                return metadata, None
            value = read(transaction, PublishedRef(
                kind=HOLDING_KIND, manifest_sha256=row["manifest_sha256"],
                provenance=row["provenance"],
            ))
            row = transaction.execute(
                "UPDATE publication.holding_units SET last_read_at = t.observed_at, "
                "expires_at = greatest(published_at, t.observed_at) + interval '7 days' "
                "FROM (SELECT clock_timestamp() AS observed_at) t WHERE id = %s "
                "RETURNING holding_units.*, t.observed_at",
                (unit_id,),
            ).fetchone()
            return self._metadata(row), value

    def expire_once(self, *, limit: int = 10) -> int:
        """Revoke bounded due references; existing Publication GC deletes bytes later."""
        if not 1 <= limit <= 10:
            raise ValueError("Holding expiry batch must contain at most ten units")
        count = 0
        for _ in range(limit):
            with self._database.transaction() as transaction:
                if not self.expire_one_in_transaction(transaction):
                    break
                count += 1
        return count

    def expire_one_in_transaction(self, transaction: PostgresTransaction) -> bool:
        row = transaction.execute(
            "SELECT id, manifest_sha256 FROM publication.holding_units "
            "WHERE expired_at IS NULL AND expires_at <= clock_timestamp() "
            "ORDER BY expires_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"
        ).fetchone()
        if row is None:
            return False
        transaction.execute(
            "UPDATE publication.holding_units SET expired_at = clock_timestamp(), "
            "manifest_sha256 = NULL WHERE id = %s", (row["id"],),
        )
        referenced = transaction.execute(
            "SELECT 1 FROM publication.holding_units WHERE manifest_sha256 = %s LIMIT 1",
            (row["manifest_sha256"],),
        ).fetchone() is not None
        self._publication.release_manifest_in_transaction(
            transaction, row["manifest_sha256"], still_referenced=referenced,
        )
        return True

    @staticmethod
    def _unit(transaction, researcher_id, unit_id, *, lock):
        # Take server time after the row lock is acquired: a waited reader must not use stale time.
        row = transaction.execute(
            "SELECT * FROM publication.holding_units WHERE researcher_id = %s AND id = %s"
            + (" FOR UPDATE" if lock else ""), (researcher_id, unit_id),
        ).fetchone()
        if row is not None:
            row["observed_at"] = transaction.execute(
                "SELECT clock_timestamp() AS observed_at"
            ).fetchone()["observed_at"]
        return row

    @staticmethod
    def _metadata(row: dict) -> dict:
        return {
            "unit_id": row["id"], "source_kind": row["source_kind"],
            "source_id": row["source_id"],
            "first_session": row["first_session"].isoformat(),
            "last_session": row["last_session"].isoformat(),
            "published_at": row["published_at"], "last_read_at": row["last_read_at"],
            "expires_at": row["expires_at"],
            "status": "expired" if row["expired_at"] is not None
            or row["expires_at"] <= row["observed_at"] else "available",
        }
