from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Literal

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.research_kernel.terminal_state_schema import TerminalStrategyStateValue


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
    planning_data_generation_id: str
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
        validated_state = _validated_state(terminal_strategy_state, origin_session)
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
                Jsonb(validated_state),
                data_generation_id,
                Jsonb(provenance),
            ),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_tracking_states (
                track_id, origin_session, origin_checkpoint_manifest_sha256,
                current_checkpoint_manifest_sha256
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                track_id,
                origin_session,
                checkpoint_manifest_sha256,
                checkpoint_manifest_sha256,
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
        planning_data_generation_id: str,
        provenance: dict[str, object],
    ) -> None:
        state = transaction.execute(
            """
            SELECT checkpoint.boundary_session AS current_checkpoint_session,
                   state.current_checkpoint_manifest_sha256
            FROM daily_tracks.session_tracking_states AS state
            JOIN daily_tracks.session_checkpoints AS checkpoint
              ON checkpoint.track_id = state.track_id
             AND checkpoint.manifest_sha256 =
                    state.current_checkpoint_manifest_sha256
            WHERE state.track_id = %s
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
        try:
            transaction.execute(
                """
                INSERT INTO daily_tracks.session_progressions (
                    id, track_id, predecessor_checkpoint_manifest_sha256,
                    target_sessions, target_start_session, target_end_session,
                    planning_data_generation_id, status, provenance
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'running', %s)
                """,
                (
                    progression_id,
                    track_id,
                    expected_checkpoint_manifest_sha256,
                    list(target_sessions),
                    target_sessions[0],
                    target_sessions[-1],
                    planning_data_generation_id,
                    Jsonb(provenance),
                ),
            )
        except UniqueViolation as error:
            raise SessionCoordinateConflict(
                "Track already has an unresolved Progression"
            ) from error

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
            SELECT track_id, target_end_session, status
            FROM daily_tracks.session_progressions
            WHERE id = %s
            FOR UPDATE
            """,
            (progression_id,),
        ).fetchone()
        if progression is None or progression["status"] != "running":
            raise SessionCoordinateConflict("Progression is not running")
        if data_through_session < progression["target_end_session"]:
            raise SessionCoordinateConflict("Attempt Generation does not reach target")
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_progression_attempts (
                id, progression_id, track_id, ordinal, fence,
                generation_pin_id, data_generation_id, data_through_session,
                status, execution_phase, lease_expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, 'running', 'starting',
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
                   attempt.data_generation_id,
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
        validated_state = _validated_state(terminal_strategy_state, boundary)
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
                Jsonb(validated_state),
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
            SET current_checkpoint_manifest_sha256 = %s,
                updated_at = now()
            WHERE track_id = %s
              AND current_checkpoint_manifest_sha256 = %s
            """,
            (
                checkpoint_manifest_sha256,
                row["track_id"],
                row["predecessor_checkpoint_manifest_sha256"],
            ),
        )
        if attempt.rowcount != 1 or progression.rowcount != 1 or state.rowcount != 1:
            raise SessionCoordinateConflict("Checkpoint publication was fenced")

    def load(self, track_id: str) -> SessionCoordinateSnapshot:
        with self._database.transaction() as transaction:
            snapshot = transaction.execute(
                """
                SELECT state.track_id, state.origin_session,
                       checkpoint.boundary_session AS current_checkpoint_session,
                       state.current_checkpoint_manifest_sha256,
                       checkpoint.terminal_strategy_state,
                       COALESCE((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'id', progression.id,
                                   'track_id', progression.track_id,
                                   'predecessor_checkpoint_manifest_sha256',
                                       progression.predecessor_checkpoint_manifest_sha256,
                                   'predecessor_checkpoint_session',
                                       predecessor.boundary_session,
                                   'target_sessions', progression.target_sessions,
                                   'planning_data_generation_id',
                                       progression.planning_data_generation_id,
                                   'status', progression.status,
                                   'checkpoint_manifest_sha256',
                                       progression.checkpoint_manifest_sha256,
                                   'provenance', progression.provenance
                               ) ORDER BY progression.target_end_session, progression.id
                           )
                           FROM daily_tracks.session_progressions AS progression
                           JOIN daily_tracks.session_checkpoints AS predecessor
                             ON predecessor.track_id = progression.track_id
                            AND predecessor.manifest_sha256 =
                                   progression.predecessor_checkpoint_manifest_sha256
                           WHERE progression.track_id = state.track_id
                       ), '[]'::jsonb) AS progressions,
                       COALESCE((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'id', attempt.id,
                                   'progression_id', attempt.progression_id,
                                   'ordinal', attempt.ordinal,
                                   'fence', attempt.fence,
                                   'generation_pin_id', attempt.generation_pin_id,
                                   'data_generation_id', attempt.data_generation_id,
                                   'data_through_session', attempt.data_through_session,
                                   'status', attempt.status,
                                   'failure_reason', attempt.failure_reason
                               ) ORDER BY progression.target_end_session, attempt.ordinal
                           )
                           FROM daily_tracks.session_progression_attempts AS attempt
                           JOIN daily_tracks.session_progressions AS progression
                             ON progression.id = attempt.progression_id
                           WHERE progression.track_id = state.track_id
                       ), '[]'::jsonb) AS attempts,
                       COALESCE((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'manifest_sha256', item.manifest_sha256,
                                   'progression_id', item.progression_id,
                                   'predecessor_manifest_sha256',
                                       item.predecessor_manifest_sha256,
                                   'boundary_session', item.boundary_session,
                                   'terminal_strategy_state',
                                       item.terminal_strategy_state,
                                   'data_generation_id', item.data_generation_id,
                                   'provenance', item.provenance
                               ) ORDER BY item.boundary_session, item.manifest_sha256
                           )
                           FROM daily_tracks.session_checkpoints AS item
                           WHERE item.track_id = state.track_id
                       ), '[]'::jsonb) AS checkpoints
                FROM daily_tracks.session_tracking_states AS state
                JOIN daily_tracks.session_checkpoints AS checkpoint
                  ON checkpoint.track_id = state.track_id
                 AND checkpoint.manifest_sha256 =
                        state.current_checkpoint_manifest_sha256
                WHERE state.track_id = %s
                """,
                (track_id,),
            ).fetchone()
        if snapshot is None:
            raise SessionCoordinateConflict("Session Tracking State does not exist")
        progressions = snapshot.pop("progressions")
        attempts = snapshot.pop("attempts")
        checkpoints = snapshot.pop("checkpoints")
        return SessionCoordinateSnapshot(
            track=SessionTrackRecord(
                **{
                    **snapshot,
                    "terminal_strategy_state": _validated_state(
                        snapshot["terminal_strategy_state"],
                        snapshot["current_checkpoint_session"],
                    ),
                }
            ),
            progressions=tuple(
                SessionProgressionRecord(
                    **{
                        **row,
                        "predecessor_checkpoint_session": date.fromisoformat(
                            row["predecessor_checkpoint_session"]
                        ),
                        "target_sessions": tuple(
                            date.fromisoformat(value) for value in row["target_sessions"]
                        ),
                    }
                )
                for row in progressions
            ),
            attempts=tuple(
                SessionAttemptRecord(
                    **{
                        **row,
                        "data_through_session": date.fromisoformat(
                            row["data_through_session"]
                        ),
                    }
                )
                for row in attempts
            ),
            checkpoints=tuple(
                SessionCheckpointRecord(
                    **{
                        **row,
                        "boundary_session": date.fromisoformat(
                            row["boundary_session"]
                        ),
                        "terminal_strategy_state": _validated_state(
                            row["terminal_strategy_state"],
                            date.fromisoformat(row["boundary_session"]),
                        ),
                    }
                )
                for row in checkpoints
            ),
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


def _validated_state(state: object, boundary: date) -> dict[str, object]:
    try:
        validated = TerminalStrategyStateValue.model_validate(state)
    except ValidationError as error:
        raise SessionCoordinateConflict("Terminal Strategy State is invalid") from error
    if validated.session != boundary.isoformat():
        raise SessionCoordinateConflict("Terminal Strategy State boundary does not match")
    return validated.model_dump(mode="json", exclude_unset=True)
