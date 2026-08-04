from __future__ import annotations

import hashlib
import json
from datetime import datetime

from psycopg.errors import UniqueViolation

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.fields import AUTHORABLE_FIELDS, AuthorableField
from thesistrace.data.models import (
    DataOverview,
    ReleaseHistory,
    ReleaseSummary,
    UpdateAcceptance,
)
from thesistrace.data.source import CollectionPlan, DataSource
from thesistrace.data.validation import validate_release_batch
from thesistrace.publication import JsonPayload, Publication, PublishedRef
from thesistrace.publication.serialization import canonical_json_bytes


class DataUpdateConflict(RuntimeError):
    pass


MAX_UPDATE_ATTEMPTS = 3


class DataService:
    def __init__(
        self,
        database: PostgresDatabase,
        publication: Publication,
        source: DataSource,
    ) -> None:
        self._database = database
        self._publication = publication
        self._source = source

    def authorable_fields(self) -> tuple[AuthorableField, ...]:
        """Expose Data-owned product field definitions without Kernel bindings."""
        return AUTHORABLE_FIELDS

    def latest_release(self) -> ReleaseSummary | None:
        """Return the current immutable Dataset Release product reference."""
        return self.overview().latest_release

    def overview(self) -> DataOverview:
        with self._database.transaction() as transaction:
            state = transaction.execute(
                """
                SELECT status, latest_update_outcome, latest_release_id
                FROM data.state
                WHERE singleton = 1
                """
            ).fetchone()
            latest_release = None
            if state is not None and state["latest_release_id"] is not None:
                latest_release = transaction.execute(
                    f"{_RELEASE_SELECT} WHERE id = %s",
                    (state["latest_release_id"],),
                ).fetchone()
        if state is None:
            raise RuntimeError("Data state is not initialized")
        if state["latest_release_id"] is not None and latest_release is None:
            raise RuntimeError("Latest Dataset Release is missing")
        return DataOverview(
            status=state["status"],
            latest_release=_release_summary(latest_release),
            latest_update_outcome=state["latest_update_outcome"],
        )

    def list_releases(self) -> ReleaseHistory:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                WITH RECURSIVE release_chain AS (
                    SELECT release.id, release.predecessor_id,
                           release.session_start, release.session_end,
                           release.session_count, release.created_at, 0 AS depth
                    FROM data.state AS state
                    JOIN data.releases AS release
                      ON release.id = state.latest_release_id
                    WHERE state.singleton = 1

                    UNION ALL

                    SELECT predecessor.id, predecessor.predecessor_id,
                           predecessor.session_start, predecessor.session_end,
                           predecessor.session_count, predecessor.created_at,
                           release_chain.depth + 1
                    FROM data.releases AS predecessor
                    JOIN release_chain
                      ON predecessor.id = release_chain.predecessor_id
                )
                SELECT id, predecessor_id, session_start, session_end,
                       session_count, created_at
                FROM release_chain
                ORDER BY depth
                """
            ).fetchall()
        return ReleaseHistory(
            items=[_release_summary(row) for row in rows if row is not None],
            next_cursor=None,
        )

    def get_release(self, release_id: str) -> ReleaseSummary | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                f"{_RELEASE_SELECT} WHERE id = %s",
                (release_id,),
            ).fetchone()
        return _release_summary(row)

    def update(self, request_id: str) -> UpdateAcceptance:
        normalized = request_id.strip()
        if not normalized:
            raise ValueError("Data Update request_id is required")
        fingerprint = hashlib.sha256(b"data.update/v1").hexdigest()
        try:
            with self._database.transaction() as transaction:
                existing = transaction.execute(
                    """
                    SELECT request_fingerprint, status
                    FROM data.update_receipts
                    WHERE request_id = %s
                    """,
                    (normalized,),
                ).fetchone()
                if existing is not None:
                    if existing["request_fingerprint"] != fingerprint:
                        raise DataUpdateConflict("Data Update request_id conflicts")
                    return _update_outcome(normalized, str(existing["status"]))
                transaction.execute(
                    """
                    INSERT INTO data.update_receipts (
                        request_id, request_fingerprint, status
                    ) VALUES (%s, %s, 'accepted')
                    """,
                    (normalized, fingerprint),
                )
                transaction.execute(
                    """
                    UPDATE data.state
                    SET status = 'updating', updated_at = now()
                    WHERE singleton = 1
                    """
                )
        except UniqueViolation as error:
            with self._database.transaction() as transaction:
                existing = transaction.execute(
                    """
                    SELECT request_fingerprint, status
                    FROM data.update_receipts
                    WHERE request_id = %s
                    """,
                    (normalized,),
                ).fetchone()
            if existing is not None and existing["request_fingerprint"] == fingerprint:
                return _update_outcome(normalized, str(existing["status"]))
            raise DataUpdateConflict("another Data Update is active") from error
        return UpdateAcceptance(request_id=normalized, outcome="accepted")

    def process_next_update(self) -> bool:
        with self._database.transaction() as transaction:
            receipt = transaction.execute(
                """
                SELECT request_id
                FROM data.update_receipts
                WHERE status = 'accepted'
                ORDER BY created_at, request_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if receipt is None:
                return False
            request_id = str(receipt["request_id"])
            transaction.execute(
                """
                UPDATE data.update_receipts
                SET status = 'running', updated_at = now()
                WHERE request_id = %s
                """,
                (request_id,),
            )
            attempt = transaction.execute(
                """
                INSERT INTO data.update_attempts (request_id, status)
                VALUES (%s, 'running')
                RETURNING id
                """,
                (request_id,),
            ).fetchone()
        assert attempt is not None
        try:
            self._publish_update(request_id, int(attempt["id"]))
        except Exception as error:
            self._record_attempt_failure(
                request_id,
                int(attempt["id"]),
                type(error).__name__,
            )
            raise
        return True

    def recover_abandoned_updates(self, *, stale_before: datetime) -> int:
        with self._database.transaction() as transaction:
            state = transaction.execute(
                "SELECT singleton FROM data.state WHERE singleton = 1 FOR UPDATE"
            ).fetchone()
            if state is None:
                raise RuntimeError("Data state is not initialized")
            rows = transaction.execute(
                """
                SELECT attempt.id, attempt.request_id,
                       (SELECT count(*)
                        FROM data.update_attempts AS counted
                        WHERE counted.request_id = attempt.request_id) AS attempt_count
                FROM data.update_attempts AS attempt
                JOIN data.update_receipts AS receipt
                  ON receipt.request_id = attempt.request_id
                WHERE attempt.status = 'running'
                  AND receipt.status = 'running'
                  AND attempt.started_at < %s
                FOR UPDATE OF attempt, receipt
                """,
                (stale_before,),
            ).fetchall()
            for row in rows:
                _transition_failed_attempt(
                    transaction,
                    request_id=str(row["request_id"]),
                    attempt_id=int(row["id"]),
                    attempt_count=int(row["attempt_count"]),
                    failure_reason="WorkerLost",
                )
        return len(rows)

    def load_canonical(self, release_id: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT manifest_sha256, source_name, collection_kind,
                       session_start, session_end, appended_session_start,
                       appended_session_end, predecessor_id, provenance_version
                FROM data.releases
                WHERE id = %s
                """,
                (release_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Dataset Release not found")
        provenance: dict[str, object] = {
            "canonical_contract": "canonical-eod-v1",
            "collection_kind": row["collection_kind"],
            "covered_session_range": {"start": row["session_start"], "end": row["session_end"]},
            "predecessor_id": row["predecessor_id"],
            "source_name": row["source_name"],
        }
        if int(row["provenance_version"]) == 2:
            provenance["appended_session_range"] = {
                "start": row["appended_session_start"],
                "end": row["appended_session_end"],
            }
            provenance["correction_change_set"] = []
        bundle = self._publication.read(
            PublishedRef(
                manifest_sha256=row["manifest_sha256"],
                kind="data.release",
                provenance=provenance,
            )
        )
        value = json.loads(bundle.payloads["canonical"].content)
        if not isinstance(value, dict):
            raise RuntimeError("Dataset Release canonical payload is invalid")
        return value

    def _publish_update(self, request_id: str, attempt_id: int) -> None:
        with self._database.transaction() as transaction:
            predecessor = transaction.execute(
                """
                SELECT release.id, release.session_end
                FROM data.state AS state
                LEFT JOIN data.releases AS release
                  ON release.id = state.latest_release_id
                WHERE state.singleton = 1
                """
            ).fetchone()
        if predecessor is None:
            raise RuntimeError("Data state is not initialized")
        has_predecessor = predecessor["id"] is not None
        plan = (
            CollectionPlan.bootstrap()
            if not has_predecessor
            else CollectionPlan.incremental(
                str(predecessor["session_end"]),
                self.load_canonical(str(predecessor["id"])),
            )
        )
        batch = self._source.collect(plan)
        calendar = batch.canonical.get("research_calendar")
        validate_release_batch(
            batch,
            predecessor_session=(
                None if not has_predecessor else str(predecessor["session_end"])
            ),
        )
        assert isinstance(calendar, list)
        predecessor_id = None if not has_predecessor else str(predecessor["id"])
        if has_predecessor and str(calendar[-1]) == str(predecessor["session_end"]):
            self._complete_no_change(request_id, attempt_id, predecessor_id)
            return
        appended_sessions = calendar
        if has_predecessor:
            predecessor_index = calendar.index(str(predecessor["session_end"]))
            appended_sessions = calendar[predecessor_index + 1 :]
        if not appended_sessions:
            raise RuntimeError("Dataset Release appended no Research Sessions")
        appended_session_start = str(appended_sessions[0])
        appended_session_end = str(appended_sessions[-1])
        provenance = {
            "canonical_contract": "canonical-eod-v1",
            "collection_kind": batch.collection_kind,
            "covered_session_range": {
                "start": batch.covered_session_range[0],
                "end": batch.covered_session_range[1],
            },
            "appended_session_range": {
                "start": appended_session_start,
                "end": appended_session_end,
            },
            "correction_change_set": [],
            "predecessor_id": predecessor_id,
            "source_name": batch.source_name,
        }
        prepared = self._publication.prepare(
            kind="data.release",
            payloads={
                "canonical": JsonPayload(batch.canonical),
                "collection_lineage": JsonPayload(batch.source_lineage),
            },
            provenance=provenance,
        )
        release_id = f"dsr_{prepared.manifest_sha256[:24]}"
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT latest_release_id
                FROM data.state
                WHERE singleton = 1
                FOR UPDATE
                """
            ).fetchone()
            if current is None:
                raise RuntimeError("Data state is not initialized")
            current_id = (
                None
                if current["latest_release_id"] is None
                else str(current["latest_release_id"])
            )
            if current_id != predecessor_id:
                raise DataUpdateConflict("latest Dataset Release changed during collection")
            _require_running_attempt(transaction, request_id, attempt_id)
            published = self._publication.record(transaction, prepared)
            transaction.execute(
                """
                INSERT INTO data.releases (
                    id, predecessor_id, manifest_sha256, source_name,
                    collection_kind, canonical_schema, session_start,
                    session_end, session_count, appended_session_start,
                    appended_session_end, provenance_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2)
                """,
                (
                    release_id,
                    predecessor_id,
                    published.manifest_sha256,
                    batch.source_name,
                    batch.collection_kind,
                    batch.canonical["schema_version"],
                    batch.covered_session_range[0],
                    batch.covered_session_range[1],
                    len(calendar),
                    appended_session_start,
                    appended_session_end,
                ),
            )
            for field in batch.canonical["field_catalog"]:
                field_id = str(field["field_id"])
                transaction.execute(
                    """
                    INSERT INTO data.fields (field_id, definition)
                    VALUES (%s, %s)
                    ON CONFLICT (field_id) DO NOTHING
                    """,
                    (field_id, canonical_json_bytes(field).decode()),
                )
                transaction.execute(
                    "INSERT INTO data.release_fields (release_id, field_id) VALUES (%s, %s)",
                    (release_id, field_id),
                )
            transaction.execute(
                """
                UPDATE data.update_attempts
                SET status = 'succeeded', finished_at = now()
                WHERE id = %s
                """,
                (attempt_id,),
            )
            transaction.execute(
                """
                UPDATE data.update_receipts
                SET status = 'published', release_id = %s, updated_at = now()
                WHERE request_id = %s
                """,
                (release_id, request_id),
            )
            transaction.execute(
                """
                UPDATE data.state
                SET status = 'idle', latest_update_outcome = 'published',
                    latest_release_id = %s, updated_at = now()
                WHERE singleton = 1
                """,
                (release_id,),
            )

    def _complete_no_change(
        self,
        request_id: str,
        attempt_id: int,
        predecessor_id: str,
    ) -> None:
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT latest_release_id
                FROM data.state
                WHERE singleton = 1
                FOR UPDATE
                """
            ).fetchone()
            if current is None:
                raise RuntimeError("Data state is not initialized")
            if current["latest_release_id"] != predecessor_id:
                raise DataUpdateConflict("latest Dataset Release changed during collection")
            _require_running_attempt(transaction, request_id, attempt_id)
            transaction.execute(
                """
                UPDATE data.update_attempts
                SET status = 'succeeded', finished_at = now()
                WHERE id = %s
                """,
                (attempt_id,),
            )
            transaction.execute(
                """
                UPDATE data.update_receipts
                SET status = 'no_change', release_id = NULL,
                    failure_reason = NULL, updated_at = now()
                WHERE request_id = %s
                """,
                (request_id,),
            )
            transaction.execute(
                """
                UPDATE data.state
                SET status = 'idle', latest_update_outcome = 'no_change',
                    updated_at = now()
                WHERE singleton = 1
                """
            )

    def _record_attempt_failure(
        self,
        request_id: str,
        attempt_id: int,
        failure_reason: str,
    ) -> None:
        with self._database.transaction() as transaction:
            state = transaction.execute(
                "SELECT singleton FROM data.state WHERE singleton = 1 FOR UPDATE"
            ).fetchone()
            if state is None:
                raise RuntimeError("Data state is not initialized")
            attempt = transaction.execute(
                """
                SELECT status,
                       (SELECT count(*)
                        FROM data.update_attempts AS counted
                        WHERE counted.request_id = %s) AS attempt_count
                FROM data.update_attempts
                WHERE id = %s AND request_id = %s
                FOR UPDATE
                """,
                (request_id, attempt_id, request_id),
            ).fetchone()
            if attempt is None:
                raise RuntimeError("Data Update Attempt is missing")
            if attempt["status"] != "running":
                return
            receipt = transaction.execute(
                """
                SELECT status
                FROM data.update_receipts
                WHERE request_id = %s
                FOR UPDATE
                """,
                (request_id,),
            ).fetchone()
            if receipt is None:
                raise RuntimeError("Data Update receipt is missing")
            if receipt["status"] != "running":
                return
            _transition_failed_attempt(
                transaction,
                request_id=request_id,
                attempt_id=attempt_id,
                attempt_count=int(attempt["attempt_count"]),
                failure_reason=failure_reason,
            )


_RELEASE_SELECT = """
    SELECT id, predecessor_id, session_start, session_end, session_count, created_at
    FROM data.releases
"""


def _release_summary(row: dict[str, object] | None) -> ReleaseSummary | None:
    if row is None:
        return None
    return ReleaseSummary(
        id=str(row["id"]),
        predecessor_id=(str(row["predecessor_id"]) if row["predecessor_id"] is not None else None),
        session_count=int(row["session_count"]),
        covered_session_range={"start": str(row["session_start"]), "end": str(row["session_end"])},
    )


def _update_outcome(request_id: str, status: str) -> UpdateAcceptance:
    if status in {"accepted", "running"}:
        outcome = "accepted"
    elif status in {"published", "no_change", "failed"}:
        outcome = status
    else:
        raise RuntimeError("Data Update receipt status is invalid")
    return UpdateAcceptance(request_id=request_id, outcome=outcome)


def _require_running_attempt(
    transaction: PostgresTransaction,
    request_id: str,
    attempt_id: int,
) -> None:
    fence = transaction.execute(
        """
        SELECT receipt.status AS receipt_status,
               attempt.status AS attempt_status
        FROM data.update_receipts AS receipt
        JOIN data.update_attempts AS attempt
          ON attempt.request_id = receipt.request_id
        WHERE receipt.request_id = %s AND attempt.id = %s
        FOR UPDATE OF receipt, attempt
        """,
        (request_id, attempt_id),
    ).fetchone()
    if fence is None or fence != {
        "receipt_status": "running",
        "attempt_status": "running",
    }:
        raise DataUpdateConflict("Data Update Attempt lost its publication fence")


def _transition_failed_attempt(
    transaction: PostgresTransaction,
    *,
    request_id: str,
    attempt_id: int,
    attempt_count: int,
    failure_reason: str,
) -> None:
    retry = attempt_count < MAX_UPDATE_ATTEMPTS
    transaction.execute(
        """
        UPDATE data.update_attempts
        SET status = 'failed', failure_reason = %s, finished_at = now()
        WHERE id = %s
        """,
        (failure_reason, attempt_id),
    )
    transaction.execute(
        """
        UPDATE data.update_receipts
        SET status = %s, failure_reason = %s, updated_at = now()
        WHERE request_id = %s
        """,
        (
            "accepted" if retry else "failed",
            None if retry else failure_reason,
            request_id,
        ),
    )
    if retry:
        transaction.execute(
            """
            UPDATE data.state
            SET status = 'updating', updated_at = now()
            WHERE singleton = 1
            """
        )
    else:
        transaction.execute(
            """
            UPDATE data.state
            SET status = 'failed', latest_update_outcome = 'failed',
                updated_at = now()
            WHERE singleton = 1
            """
        )
