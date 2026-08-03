from __future__ import annotations

import hashlib
import json

from psycopg.errors import UniqueViolation

from thesistrace._postgres import PostgresDatabase
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

    def overview(self) -> DataOverview:
        with self._database.transaction() as transaction:
            state = transaction.execute(
                "SELECT status, latest_update_outcome FROM data.state WHERE singleton = 1"
            ).fetchone()
            latest_release = transaction.execute(
                f"{_RELEASE_SELECT} ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if state is None:
            raise RuntimeError("Data state is not initialized")
        return DataOverview(
            status=state["status"],
            latest_release=_release_summary(latest_release),
            latest_update_outcome=state["latest_update_outcome"],
        )

    def list_releases(self) -> ReleaseHistory:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                f"{_RELEASE_SELECT} ORDER BY created_at DESC, id DESC"
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
                    return UpdateAcceptance(request_id=normalized, outcome="accepted")
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
            with self._database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.update_attempts
                    SET status = 'failed', finished_at = now()
                    WHERE id = %s
                    """,
                    (attempt["id"],),
                )
                transaction.execute(
                    """
                    UPDATE data.update_receipts
                    SET status = 'failed', failure_reason = %s, updated_at = now()
                    WHERE request_id = %s
                    """,
                    (type(error).__name__, request_id),
                )
                transaction.execute(
                    """
                    UPDATE data.state
                    SET status = 'failed', latest_update_outcome = 'failed', updated_at = now()
                    WHERE singleton = 1
                    """
                )
            raise
        return True

    def load_canonical(self, release_id: str) -> dict[str, object]:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT manifest_sha256, source_name, collection_kind,
                       session_start, session_end, predecessor_id
                FROM data.releases
                WHERE id = %s
                """,
                (release_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Dataset Release not found")
        provenance = {
            "canonical_contract": "canonical-eod-v1",
            "collection_kind": row["collection_kind"],
            "covered_session_range": {"start": row["session_start"], "end": row["session_end"]},
            "predecessor_id": row["predecessor_id"],
            "source_name": row["source_name"],
        }
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
                SELECT id, session_end
                FROM data.releases
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        plan = (
            CollectionPlan.bootstrap()
            if predecessor is None
            else CollectionPlan.incremental(str(predecessor["session_end"]))
        )
        batch = self._source.collect(plan)
        calendar = batch.canonical.get("research_calendar")
        validate_release_batch(
            batch,
            predecessor_session=(
                None if predecessor is None else str(predecessor["session_end"])
            ),
        )
        assert isinstance(calendar, list)
        predecessor_id = None if predecessor is None else str(predecessor["id"])
        provenance = {
            "canonical_contract": "canonical-eod-v1",
            "collection_kind": batch.collection_kind,
            "covered_session_range": {
                "start": batch.covered_session_range[0],
                "end": batch.covered_session_range[1],
            },
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
            transaction.execute(
                "SELECT singleton FROM data.state WHERE singleton = 1 FOR UPDATE"
            )
            current = transaction.execute(
                """
                SELECT id
                FROM data.releases
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            current_id = None if current is None else str(current["id"])
            if current_id != predecessor_id:
                raise DataUpdateConflict("latest Dataset Release changed during collection")
            published = self._publication.record(transaction, prepared)
            transaction.execute(
                """
                INSERT INTO data.releases (
                    id, predecessor_id, manifest_sha256, source_name,
                    collection_kind, canonical_schema, session_start,
                    session_end, session_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                SET status = 'idle', latest_update_outcome = 'published', updated_at = now()
                WHERE singleton = 1
                """
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
