from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.daily_track.models import (
    DailyTrackList,
    DailyTrackSummary,
    TrackingOrigin,
)


class DailyTrackActivationConflict(RuntimeError):
    pass


class DailyTrackService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def activate(
        self,
        transaction: PostgresTransaction,
        origin: TrackingOrigin,
        request_id: str,
    ) -> DailyTrackSummary:
        selected_request_id = request_id.strip()
        if not selected_request_id:
            raise ValueError("Start Tracking request_id is required")
        fingerprint = _activation_fingerprint(origin.seed_run_id)
        transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"daily_tracks.activation.request:{selected_request_id}",),
        ).fetchone()
        receipt = transaction.execute(
            """
            SELECT request_fingerprint, outcome
            FROM daily_tracks.activation_receipts
            WHERE request_id = %s
            """,
            (selected_request_id,),
        ).fetchone()
        if receipt is not None:
            if receipt["request_fingerprint"] != fingerprint:
                raise DailyTrackActivationConflict(
                    "Start Tracking request_id conflicts"
                )
            return DailyTrackSummary.model_validate(receipt["outcome"])

        transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"daily_tracks.activation.seed:{origin.seed_run_id}",),
        ).fetchone()
        row = transaction.execute(
            """
            SELECT id, status, origin
            FROM daily_tracks.tracks
            WHERE seed_run_id = %s
            """,
            (origin.seed_run_id,),
        ).fetchone()
        if row is None:
            row = transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    id, status, seed_run_id, origin
                ) VALUES (%s, 'active', %s, %s)
                RETURNING id, status, origin
                """,
                (
                    f"track_{uuid4().hex[:20]}",
                    origin.seed_run_id,
                    Jsonb(origin.model_dump(mode="json")),
                ),
            ).fetchone()
            assert row is not None
        outcome = _summary(row)
        transaction.execute(
            """
            INSERT INTO daily_tracks.activation_receipts (
                request_id, request_fingerprint, track_id, outcome
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                selected_request_id,
                fingerprint,
                outcome.id,
                Jsonb(outcome.model_dump(mode="json")),
            ),
        )
        return outcome

    def list(self) -> DailyTrackList:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, status, origin
                FROM daily_tracks.tracks
                ORDER BY created_at DESC, id
                """
            ).fetchall()
        return DailyTrackList(items=[_summary(row) for row in rows], next_cursor=None)

    def get(self, track_id: str) -> DailyTrackSummary | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, status, origin
                FROM daily_tracks.tracks
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
        return None if row is None else _summary(row)


def _activation_fingerprint(seed_run_id: str) -> str:
    value = {
        "action": "research-runs.start-tracking/v1",
        "seed_run_id": seed_run_id,
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _summary(row: object) -> DailyTrackSummary:
    assert isinstance(row, dict)
    origin = TrackingOrigin.model_validate(row["origin"])
    verified_result = origin.verified_result
    return DailyTrackSummary(
        id=str(row["id"]),
        status="active",
        seed_run_id=origin.seed_run_id,
        seed_release_id=origin.seed_release_id,
        definition_id=origin.definition_id,
        definition_revision=origin.definition_revision,
        result_checksum_sha256=verified_result.result_checksum_sha256,
        strategy_session=origin.initial_strategy_state.session,
    )
