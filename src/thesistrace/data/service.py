from __future__ import annotations

import json
from dataclasses import dataclass

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.fields import AUTHORABLE_FIELDS, AuthorableField
from thesistrace.publication import Publication, PublishedRef


@dataclass(frozen=True)
class ReleaseReference:
    """Temporary private reference used by consumers not yet moved to Dataset Head."""

    id: str
    field_bindings: dict[str, str]


@dataclass(frozen=True)
class NextRelease:
    """Temporary private successor used by DailyTrack until its Head migration."""

    id: str
    predecessor_id: str
    appended_session_start: str
    appended_session_end: str


class DataService:
    """Read-only legacy consumer seam during the Release-to-Head cutover."""

    def __init__(self, database: PostgresDatabase, publication: Publication) -> None:
        self._database = database
        self._publication = publication

    def authorable_fields(self) -> tuple[AuthorableField, ...]:
        return AUTHORABLE_FIELDS

    def latest_release(self, transaction: PostgresTransaction) -> ReleaseReference | None:
        row = transaction.execute(
            """
            SELECT release.id
            FROM data.state AS state
            JOIN data.releases AS release ON release.id = state.latest_release_id
            WHERE state.singleton = 1
            """
        ).fetchone()
        if row is None:
            return None
        available_rows = transaction.execute(
            """
            SELECT field_id
            FROM data.release_fields
            WHERE release_id = %s
            ORDER BY field_id
            """,
            (row["id"],),
        ).fetchall()
        available = {str(item["field_id"]) for item in available_rows}
        return ReleaseReference(
            id=str(row["id"]),
            field_bindings={
                field.field_id: field.evaluation_name
                for field in AUTHORABLE_FIELDS
                if field.field_id in available
            },
        )

    def next_release(
        self,
        transaction: PostgresTransaction,
        current_release_id: str,
    ) -> NextRelease | None:
        rows = transaction.execute(
            """
            SELECT id, predecessor_id, appended_session_start, appended_session_end
            FROM data.releases
            WHERE predecessor_id = %s
            ORDER BY created_at, id
            LIMIT 2
            """,
            (current_release_id,),
        ).fetchall()
        if len(rows) > 1:
            raise RuntimeError("Dataset Release graph has multiple direct successors")
        if not rows:
            return None
        successor = rows[0]
        return NextRelease(
            id=str(successor["id"]),
            predecessor_id=str(successor["predecessor_id"]),
            appended_session_start=str(successor["appended_session_start"]),
            appended_session_end=str(successor["appended_session_end"]),
        )

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
            "covered_session_range": {
                "start": row["session_start"],
                "end": row["session_end"],
            },
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
                manifest_sha256=str(row["manifest_sha256"]),
                kind="data.release",
                provenance=provenance,
            )
        )
        value = json.loads(bundle.payloads["canonical"].content)
        if not isinstance(value, dict):
            raise RuntimeError("Dataset Release canonical payload is invalid")
        return value
