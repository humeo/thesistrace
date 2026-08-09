from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Literal

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction


class SessionCoordinateConflict(ValueError):
    pass


@dataclass(frozen=True)
class SessionTrackRecord:
    track_id: str
    origin_session: date
    current_checkpoint_session: date
    current_checkpoint_manifest_sha256: str
    terminal_strategy_state: dict[str, object]


@dataclass(frozen=True)
class SessionProgressionRecord:
    id: str
    track_id: str
    predecessor_checkpoint_manifest_sha256: str
    predecessor_checkpoint_session: date
    target_sessions: tuple[date, ...]
    data_generation_id: str
    status: Literal["running", "succeeded", "blocked", "cancelled"]
    checkpoint_manifest_sha256: str | None
    provenance: dict[str, object]


@dataclass(frozen=True)
class SessionAttemptRecord:
    id: str
    progression_id: str
    ordinal: int
    fence: int
    generation_pin_id: str
    data_generation_id: str
    data_through_session: date
    status: Literal["running", "succeeded", "failed", "cancelled"]
    failure_reason: str | None


@dataclass(frozen=True)
class SessionCheckpointRecord:
    manifest_sha256: str
    progression_id: str | None
    predecessor_manifest_sha256: str | None
    boundary_session: date
    terminal_strategy_state: dict[str, object]
    data_generation_id: str
    provenance: dict[str, object]


@dataclass(frozen=True)
class SessionCoordinateSnapshot:
    track: SessionTrackRecord
    progressions: tuple[SessionProgressionRecord, ...]
    attempts: tuple[SessionAttemptRecord, ...]
    checkpoints: tuple[SessionCheckpointRecord, ...]


class SessionCoordinateRepository:
    """Durable session-coordinate state below the DailyTrack product API."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def activate(
        self,
        transaction: PostgresTransaction,
        *,
        track_id: str,
        origin_session: date,
        checkpoint_manifest_sha256: str,
        terminal_strategy_state: dict[str, object],
        data_generation_id: str,
        provenance: dict[str, object],
    ) -> None:
        _require_state_boundary(terminal_strategy_state, origin_session)
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_checkpoints (
                manifest_sha256, track_id, progression_id,
                predecessor_manifest_sha256, boundary_session,
                terminal_strategy_state, data_generation_id, provenance
            ) VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s)
            """,
            (
                checkpoint_manifest_sha256,
                track_id,
                origin_session,
                Jsonb(terminal_strategy_state),
                data_generation_id,
                Jsonb(provenance),
            ),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_tracking_states (
                track_id, origin_session, current_checkpoint_session,
                current_checkpoint_manifest_sha256, terminal_strategy_state
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                track_id,
                origin_session,
                origin_session,
                checkpoint_manifest_sha256,
                Jsonb(terminal_strategy_state),
            ),
        )

    def start_progression(
        self,
        transaction: PostgresTransaction,
        *,
        progression_id: str,
        track_id: str,
        expected_checkpoint_manifest_sha256: str,
        generation_sessions: tuple[date, ...],
        target_sessions: tuple[date, ...],
        data_generation_id: str,
        provenance: dict[str, object],
    ) -> None:
        state = transaction.execute(
            """
            SELECT current_checkpoint_session,
                   current_checkpoint_manifest_sha256
            FROM daily_tracks.session_tracking_states
            WHERE track_id = %s
            FOR UPDATE
            """,
            (track_id,),
        ).fetchone()
        if state is None:
            raise SessionCoordinateConflict("Session Tracking State does not exist")
        current_session = state["current_checkpoint_session"]
        if state["current_checkpoint_manifest_sha256"] != (
            expected_checkpoint_manifest_sha256
        ):
            raise SessionCoordinateConflict("Current Checkpoint changed")
        _require_exact_target(
            current_session=current_session,
            generation_sessions=generation_sessions,
            target_sessions=target_sessions,
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_progressions (
                id, track_id, predecessor_checkpoint_manifest_sha256,
                predecessor_checkpoint_session, target_sessions,
                target_start_session, target_end_session,
                data_generation_id, status, provenance
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'running', %s)
            """,
            (
                progression_id,
                track_id,
                expected_checkpoint_manifest_sha256,
                current_session,
                list(target_sessions),
                target_sessions[0],
                target_sessions[-1],
                data_generation_id,
                Jsonb(provenance),
            ),
        )

    def start_attempt(
        self,
        transaction: PostgresTransaction,
        *,
        attempt_id: str,
        progression_id: str,
        ordinal: int,
        fence: int,
        generation_pin_id: str,
        data_generation_id: str,
        data_through_session: date,
        lease_seconds: float,
    ) -> None:
        progression = transaction.execute(
            """
            SELECT track_id, data_generation_id, target_end_session, status
            FROM daily_tracks.session_progressions
            WHERE id = %s
            FOR UPDATE
            """,
            (progression_id,),
        ).fetchone()
        if progression is None or progression["status"] != "running":
            raise SessionCoordinateConflict("Progression is not running")
        if progression["data_generation_id"] != data_generation_id:
            raise SessionCoordinateConflict("Attempt Generation changed")
        if data_through_session < progression["target_end_session"]:
            raise SessionCoordinateConflict("Attempt Generation does not reach target")
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_progression_attempts (
                id, progression_id, track_id, ordinal, fence,
                generation_pin_id, data_generation_id, data_through_session,
                status, lease_expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, 'running',
                now() + make_interval(secs => %s)
            )
            """,
            (
                attempt_id,
                progression_id,
                progression["track_id"],
                ordinal,
                fence,
                generation_pin_id,
                data_generation_id,
                data_through_session,
                lease_seconds,
            ),
        )

    def publish_checkpoint(
        self,
        transaction: PostgresTransaction,
        *,
        progression_id: str,
        attempt_id: str,
        fence: int,
        checkpoint_manifest_sha256: str,
        terminal_strategy_state: dict[str, object],
        provenance: dict[str, object],
    ) -> None:
        row = transaction.execute(
            """
            SELECT progression.track_id,
                   progression.predecessor_checkpoint_manifest_sha256,
                   progression.target_end_session,
                   progression.data_generation_id,
                   progression.status AS progression_status,
                   attempt.status AS attempt_status,
                   attempt.fence,
                   state.current_checkpoint_manifest_sha256
            FROM daily_tracks.session_progressions AS progression
            JOIN daily_tracks.session_progression_attempts AS attempt
              ON attempt.progression_id = progression.id
            JOIN daily_tracks.session_tracking_states AS state
              ON state.track_id = progression.track_id
            WHERE progression.id = %s AND attempt.id = %s
            FOR UPDATE OF progression, attempt, state
            """,
            (progression_id, attempt_id),
        ).fetchone()
        if row is None:
            raise SessionCoordinateConflict("Progression Attempt does not exist")
        if (
            row["progression_status"] != "running"
            or row["attempt_status"] != "running"
            or int(row["fence"]) != fence
            or row["current_checkpoint_manifest_sha256"]
            != row["predecessor_checkpoint_manifest_sha256"]
        ):
            raise SessionCoordinateConflict("Progression Attempt is fenced")
        boundary = row["target_end_session"]
        _require_state_boundary(terminal_strategy_state, boundary)
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_checkpoints (
                manifest_sha256, track_id, progression_id,
                predecessor_manifest_sha256, boundary_session,
                terminal_strategy_state, data_generation_id, provenance
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                checkpoint_manifest_sha256,
                row["track_id"],
                progression_id,
                row["predecessor_checkpoint_manifest_sha256"],
                boundary,
                Jsonb(terminal_strategy_state),
                row["data_generation_id"],
                Jsonb(provenance),
            ),
        )
        attempt = transaction.execute(
            """
            UPDATE daily_tracks.session_progression_attempts
            SET status = 'succeeded', heartbeat_at = now(), finished_at = now()
            WHERE id = %s AND progression_id = %s
              AND fence = %s AND status = 'running'
            """,
            (attempt_id, progression_id, fence),
        )
        progression = transaction.execute(
            """
            UPDATE daily_tracks.session_progressions
            SET status = 'succeeded', checkpoint_manifest_sha256 = %s,
                finished_at = now()
            WHERE id = %s AND status = 'running'
            """,
            (checkpoint_manifest_sha256, progression_id),
        )
        state = transaction.execute(
            """
            UPDATE daily_tracks.session_tracking_states
            SET current_checkpoint_session = %s,
                current_checkpoint_manifest_sha256 = %s,
                terminal_strategy_state = %s, updated_at = now()
            WHERE track_id = %s
              AND current_checkpoint_manifest_sha256 = %s
            """,
            (
                boundary,
                checkpoint_manifest_sha256,
                Jsonb(terminal_strategy_state),
                row["track_id"],
                row["predecessor_checkpoint_manifest_sha256"],
            ),
        )
        if attempt.rowcount != 1 or progression.rowcount != 1 or state.rowcount != 1:
            raise SessionCoordinateConflict("Checkpoint publication was fenced")

    def load(self, track_id: str) -> SessionCoordinateSnapshot:
        with self._database.transaction() as transaction:
            track = transaction.execute(
                """
                SELECT track_id, origin_session, current_checkpoint_session,
                       current_checkpoint_manifest_sha256,
                       terminal_strategy_state
                FROM daily_tracks.session_tracking_states
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchone()
            if track is None:
                raise SessionCoordinateConflict("Session Tracking State does not exist")
            progressions = transaction.execute(
                """
                SELECT id, track_id,
                       predecessor_checkpoint_manifest_sha256,
                       predecessor_checkpoint_session, target_sessions,
                       data_generation_id, status,
                       checkpoint_manifest_sha256, provenance
                FROM daily_tracks.session_progressions
                WHERE track_id = %s
                ORDER BY target_end_session, id
                """,
                (track_id,),
            ).fetchall()
            attempts = transaction.execute(
                """
                SELECT attempt.id, attempt.progression_id, attempt.ordinal,
                       attempt.fence, attempt.generation_pin_id,
                       attempt.data_generation_id,
                       attempt.data_through_session, attempt.status,
                       attempt.failure_reason
                FROM daily_tracks.session_progression_attempts AS attempt
                JOIN daily_tracks.session_progressions AS progression
                  ON progression.id = attempt.progression_id
                WHERE progression.track_id = %s
                ORDER BY progression.target_end_session, attempt.ordinal
                """,
                (track_id,),
            ).fetchall()
            checkpoints = transaction.execute(
                """
                SELECT manifest_sha256, progression_id,
                       predecessor_manifest_sha256, boundary_session,
                       terminal_strategy_state, data_generation_id, provenance
                FROM daily_tracks.session_checkpoints
                WHERE track_id = %s
                ORDER BY boundary_session, manifest_sha256
                """,
                (track_id,),
            ).fetchall()
        return SessionCoordinateSnapshot(
            track=SessionTrackRecord(**track),
            progressions=tuple(
                SessionProgressionRecord(
                    **{**row, "target_sessions": tuple(row["target_sessions"])}
                )
                for row in progressions
            ),
            attempts=tuple(SessionAttemptRecord(**row) for row in attempts),
            checkpoints=tuple(SessionCheckpointRecord(**row) for row in checkpoints),
        )


def _require_exact_target(
    *,
    current_session: date,
    generation_sessions: tuple[date, ...],
    target_sessions: tuple[date, ...],
) -> None:
    if not target_sessions or not _strictly_increasing(generation_sessions):
        raise SessionCoordinateConflict("Generation sessions are invalid")
    if not _strictly_increasing(target_sessions):
        raise SessionCoordinateConflict("Target sessions are reversed or duplicated")
    try:
        current_index = generation_sessions.index(current_session)
    except ValueError as error:
        raise SessionCoordinateConflict("Current Checkpoint is outside Generation") from error
    expected = generation_sessions[
        current_index + 1 : current_index + 1 + len(target_sessions)
    ]
    if target_sessions != expected:
        raise SessionCoordinateConflict("Target sessions do not form the next range")


def _strictly_increasing(sessions: tuple[date, ...]) -> bool:
    return all(left < right for left, right in pairwise(sessions))


def _require_state_boundary(state: dict[str, object], boundary: date) -> None:
    if state.get("session") != boundary.isoformat():
        raise SessionCoordinateConflict("Terminal Strategy State boundary does not match")
