from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.daily_track.cache import _DailyTrackWorkingCache
from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
    restore_tracking_origin,
    terminal_strategy_state,
)
from thesistrace.daily_track.models import (
    DailyTrackDetail,
    DailyTrackList,
    DailyTrackSummary,
    KernelStateCheckpoint,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
    TrackingOrigin,
)
from thesistrace.daily_track.session_persistence import SessionCoordinateRepository
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.publication import (
    JsonPayload,
    PreparedPublication,
    Publication,
    PublishedRef,
    VerifiedBundle,
    lock_publication_mutation,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import (
    AdvanceInput,
    KernelState,
    advance,
    advance_continuation,
    continuation_snapshot,
    empty_continuation,
    equivalence_bytes,
    first_divergence,
)
from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)

logger = logging.getLogger(__name__)

KernelAdvance = Callable[[AdvanceInput], KernelState]
Progress = Callable[[str, str, str], None]
ResultBundleReader = Callable[[VerifiedBundle], dict[str, object]]
ATTEMPT_LEASE_SECONDS = 15 * 60
ATTEMPT_HEARTBEAT_SECONDS = 30
WORKER_LOST_FAILURE = "WorkerLost"
MAX_AUTOMATIC_PROGRESSION_ATTEMPTS = 3
ACTIVE_DAILY_TRACK_LIMIT = 10
PUBLIC_BLOCKED_REASON = "DailyTrack could not process the current dataset."


class DailyTrackFenced(RuntimeError):
    pass


class DailyTrackActivationLimitReached(RuntimeError):
    pass


class DailyTrackProgressionFailed(RuntimeError):
    pass


class DailyTrackEquivalenceMismatch(RuntimeError):
    pass


class DailyTrackDetailUnavailable(RuntimeError):
    pass


class DailyTrackRetryConflict(RuntimeError):
    pass


class DailyTrackRetryUnavailable(RuntimeError):
    pass


class DailyTrackStopConflict(RuntimeError):
    pass


class DailyTrackStopUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyTrackEquivalenceEvidence:
    status: str
    track_id: str
    head_session: str
    session_sequence: tuple[str, ...]
    checkpoint_count: int
    checkpoint_evidence_sha256s: tuple[str, ...]
    final_evidence_sha256: str


@dataclass(frozen=True)
class _SessionProgressionClaim:
    track_id: str
    progression_id: str
    attempt_id: str
    fence: int
    generation_pin_id: str
    data_generation_id: str
    data_through_session: str
    origin: TrackingOrigin
    predecessor_manifest_sha256: str
    predecessor_provenance: dict[str, object]
    current_session: str
    target_sessions: tuple[str, ...]
    canonical: dict[str, object]


class DailyTrackService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        publication: Publication | None = None,
        dataset_lifecycle: DatasetLifecycle | None = None,
        generation_store: MountedGenerationStore | None = None,
        read_result_bundle: ResultBundleReader,
        advance_kernel: KernelAdvance = advance,
        progress: Progress | None = None,
        lease_seconds: float = ATTEMPT_LEASE_SECONDS,
        heartbeat_seconds: float = ATTEMPT_HEARTBEAT_SECONDS,
        working_cache_root: Path | None = None,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0:
            raise ValueError("DailyTrack lease and heartbeat intervals must be positive")
        self._database = database
        self._publication = publication
        self._dataset_lifecycle = dataset_lifecycle
        self._generation_store = generation_store
        self._read_result_bundle = read_result_bundle
        self._session_coordinates = SessionCoordinateRepository(database)
        self._advance_kernel = advance_kernel
        self._progress = progress or (lambda _stage, _track_id, _target_id: None)
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._working_cache = (
            None if working_cache_root is None else _DailyTrackWorkingCache(working_cache_root)
        )

    def activate(
        self,
        transaction: PostgresTransaction,
        origin: TrackingOrigin,
    ) -> DailyTrackSummary:
        lock_publication_mutation(transaction)
        transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("daily_tracks.activation.capacity",),
        ).fetchone()
        transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"daily_tracks.activation.seed:{origin.seed_run_id}",),
        ).fetchone()
        row = transaction.execute(
            f"""
            {_TRACK_SELECT}
            WHERE seed_run_id = %s
            """,
            (origin.seed_run_id,),
        ).fetchone()
        if row is None:
            capacity = transaction.execute(
                """
                SELECT count(*) AS count
                FROM daily_tracks.tracks
                WHERE status IN ('active', 'blocked')
                """
            ).fetchone()
            assert capacity is not None
            if int(capacity["count"]) >= ACTIVE_DAILY_TRACK_LIMIT:
                raise DailyTrackActivationLimitReached("Active DailyTrack limit of 10 reached")
            row = self._activate_current(transaction, origin)
            assert row is not None
        return _summary(row)

    def _activate_current(
        self,
        transaction: PostgresTransaction,
        origin: TrackingOrigin,
    ) -> dict[str, object]:
        if self._publication is None:
            raise RuntimeError("current-data DailyTrack activation is not configured")
        track_id = f"track_{uuid4().hex[:20]}"
        boundary = origin.initial_strategy_state.session
        provenance = {
            "schema_version": "daily-track-activation-checkpoint-v1",
            "daily_track_id": track_id,
            "seed_run_id": origin.seed_run_id,
            "boundary_session": boundary,
            "calculation_contracts": origin.calculation_contracts,
        }
        prepared = self._publication.prepare(
            kind="daily-track.checkpoint",
            payloads={
                "checkpoint": JsonPayload(
                    {
                        "schema_version": "daily-track-activation-checkpoint-v1",
                        "terminal_strategy_state": (
                            origin.initial_strategy_state.model_dump(mode="json")
                        ),
                    }
                )
            },
            provenance=provenance,
        )
        published = self._publication.record(transaction, prepared)
        row = transaction.execute(
            """
            INSERT INTO daily_tracks.tracks (
                id, status, seed_run_id, origin
            ) VALUES (%s, 'active', %s, %s)
            RETURNING id, status, origin
            """,
            (
                track_id,
                origin.seed_run_id,
                Jsonb(origin.model_dump(mode="json")),
            ),
        ).fetchone()
        assert row is not None
        self._session_coordinates.activate(
            transaction,
            track_id=track_id,
            origin_session=_session_date(boundary),
            checkpoint_manifest_sha256=published.manifest_sha256,
            terminal_strategy_state=origin.initial_strategy_state.model_dump(mode="json"),
            data_generation_id=origin.seed_data_generation_id,
            provenance=provenance,
        )
        return {**row, "current_strategy_session": boundary}

    def process_next(self) -> bool:
        if self._recover_expired_current():
            return True
        current_claim = self._claim_current()
        if current_claim is not None:
            self._progress(
                "claimed",
                current_claim.track_id,
                current_claim.data_generation_id,
            )
            with self._maintain_current_claim(current_claim):
                try:
                    prepared, provenance, state = self._execute_current(current_claim)
                    self._progress(
                        "prepared",
                        current_claim.track_id,
                        current_claim.data_generation_id,
                    )
                    published = self._publish_current(
                        current_claim,
                        prepared,
                        provenance,
                        state,
                    )
                    self._store_current_working_cache(
                        current_claim,
                        published,
                        state,
                    )
                    self._progress(
                        "published",
                        current_claim.track_id,
                        current_claim.data_generation_id,
                    )
                except DailyTrackFenced:
                    logger.info(
                        "DailyTrack session progression rejected by execution fence",
                        extra={"track_id": current_claim.track_id},
                    )
                except Exception as error:
                    if self._record_current_failure(current_claim, error):
                        raise DailyTrackProgressionFailed(
                            "DailyTrack progression failed at its current target"
                        ) from error
                    logger.info(
                        "DailyTrack session failure rejected by execution fence",
                        extra={"track_id": current_claim.track_id},
                    )
            return True
        return False

    def list(self) -> DailyTrackList:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                f"""
                {_TRACK_SELECT}
                ORDER BY track.created_at DESC, track.id
                """
            ).fetchall()
        return DailyTrackList(items=[_summary(row) for row in rows], next_cursor=None)

    def retry(
        self,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackSummary | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("DailyTrack Retry request_id is required")
        fingerprint = _retry_fingerprint(track_id)
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"daily_tracks.retry:{request_id}",),
            ).fetchone()
            receipt = transaction.execute(
                """
                SELECT request_fingerprint, outcome
                FROM daily_tracks.retry_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise DailyTrackRetryConflict("DailyTrack Retry request_id conflicts")
                return DailyTrackSummary.model_validate(receipt["outcome"])

            track = transaction.execute(
                f"""
                {_TRACK_SELECT}
                WHERE track.id = %s
                FOR UPDATE OF track
                """,
                (track_id,),
            ).fetchone()
            if track is None:
                return None
            if track["status"] != "blocked":
                raise DailyTrackRetryUnavailable("DailyTrack Retry requires blocked status")
            session_progression = transaction.execute(
                """
                SELECT id
                FROM daily_tracks.session_progressions
                WHERE track_id = %s AND status = 'blocked'
                FOR UPDATE
                """,
                (track_id,),
            ).fetchone()
            if session_progression is None:
                raise DailyTrackRetryUnavailable(
                    "DailyTrack has no blocked session progression"
                )
            progression_id = str(session_progression["id"])
            blocked = transaction.execute(
                """
                SELECT blocked_progression_id
                FROM daily_tracks.tracks
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
            assert blocked is not None
            if str(blocked["blocked_progression_id"]) != progression_id:
                raise DailyTrackFenced
            progression = transaction.execute(
                """
                UPDATE daily_tracks.session_progressions
                SET status = 'running', finished_at = NULL
                WHERE id = %s AND track_id = %s AND status = 'blocked'
                """,
                (progression_id, track_id),
            )
            activated = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET status = 'active', blocked_progression_id = NULL,
                    blocked_reason = NULL
                WHERE id = %s AND status = 'blocked'
                  AND blocked_progression_id = %s
                """,
                (track_id, progression_id),
            )
            if progression.rowcount != 1 or activated.rowcount != 1:
                raise DailyTrackFenced
            outcome = DailyTrackSummary(
                **{
                    **_summary(track).model_dump(mode="python"),
                    "status": "active",
                }
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.retry_receipts (
                    request_id, request_fingerprint, track_id,
                    progression_id, outcome
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    request_id,
                    fingerprint,
                    track_id,
                    progression_id,
                    Jsonb(outcome.model_dump(mode="json")),
                ),
            )
        return outcome

    def stop(
        self,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackSummary | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("DailyTrack Stop request_id is required")
        fingerprint = _stop_fingerprint(track_id)
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"daily_tracks.stop:{request_id}",),
            ).fetchone()
            receipt = transaction.execute(
                """
                SELECT request_fingerprint, outcome
                FROM daily_tracks.stop_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise DailyTrackStopConflict("DailyTrack Stop request_id conflicts")
                outcome = DailyTrackSummary.model_validate(receipt["outcome"])
            else:
                track = transaction.execute(
                    f"""
                    {_TRACK_SELECT}
                    WHERE track.id = %s
                    FOR UPDATE OF track
                    """,
                    (track_id,),
                ).fetchone()
                if track is None:
                    return None
                if track["status"] not in {"active", "blocked"}:
                    raise DailyTrackStopUnavailable(
                        "DailyTrack Stop requires active or blocked status"
                    )
                current_attempts = transaction.execute(
                    """
                    SELECT id, generation_pin_id
                    FROM daily_tracks.session_progression_attempts
                    WHERE track_id = %s AND status = 'running'
                    FOR UPDATE
                    """,
                    (track_id,),
                ).fetchall()
                transaction.execute(
                    """
                    UPDATE daily_tracks.session_progression_attempts
                    SET status = 'cancelled', heartbeat_at = now(),
                        lease_expires_at = now(), finished_at = now(),
                        failure_reason = 'UserStopped'
                    WHERE track_id = %s AND status = 'running'
                    """,
                    (track_id,),
                )
                transaction.execute(
                    """
                    UPDATE daily_tracks.session_progressions
                    SET status = 'cancelled', finished_at = now()
                    WHERE track_id = %s AND status IN ('running', 'blocked')
                    """,
                    (track_id,),
                )
                if current_attempts and self._dataset_lifecycle is None:
                    raise RuntimeError(
                        "current-data DailyTrack stop is not configured"
                    )
                for attempt in current_attempts:
                    assert self._dataset_lifecycle is not None
                    self._dataset_lifecycle.release_pin_in_transaction(
                        transaction,
                        str(attempt["generation_pin_id"]),
                        owner_id=str(attempt["id"]),
                    )
                stopped = transaction.execute(
                    """
                    UPDATE daily_tracks.tracks
                    SET status = 'stopped', execution_fence = execution_fence + 1,
                        blocked_progression_id = NULL, blocked_reason = NULL
                    WHERE id = %s AND status IN ('active', 'blocked')
                    """,
                    (track_id,),
                )
                if stopped.rowcount != 1:
                    raise DailyTrackFenced
                outcome = DailyTrackSummary(
                    **{
                        **_summary(track).model_dump(mode="python"),
                        "status": "stopped",
                    }
                )
                transaction.execute(
                    """
                    INSERT INTO daily_tracks.stop_receipts (
                        request_id, request_fingerprint, track_id, outcome
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        request_id,
                        fingerprint,
                        track_id,
                        Jsonb(outcome.model_dump(mode="json")),
                    ),
                )
        if self._working_cache is not None:
            self._working_cache.delete(track_id)
        return outcome

    def reconcile_stopped_working_cache(self) -> int:
        if self._working_cache is None:
            return 0
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                "SELECT id FROM daily_tracks.tracks WHERE status = 'stopped'"
            ).fetchall()
        removed = 0
        for row in rows:
            track_id = str(row["id"])
            path = self._working_cache.path(track_id)
            if not path.exists():
                continue
            self._working_cache.delete(track_id)
            if path.exists():
                logger.warning(
                    "Stopped DailyTrack Working Cache cleanup remains pending",
                    extra={"track_id": track_id},
                )
                continue
            removed += 1
        return removed

    def get(self, track_id: str) -> DailyTrackDetail | None:
        return self._get_current(track_id)

    def _get_current(self, track_id: str) -> DailyTrackDetail | None:
        if self._publication is None or self._dataset_lifecycle is None:
            raise RuntimeError("current-data DailyTrack detail is not configured")
        with self._database.transaction() as transaction:
            row = transaction.execute(
                f"""
                {_TRACK_SELECT}
                WHERE track.id = %s
                """,
                (track_id,),
            ).fetchone()
        if row is None:
            return None
        origin = TrackingOrigin.model_validate(row["origin"])
        try:
            snapshot = self._session_coordinates.load(track_id)
            seed_result = self._read_result_bundle(
                self._publication.read(
                    PublishedRef(
                        manifest_sha256=(
                            origin.verified_result.result_manifest_sha256
                        ),
                        kind=origin.verified_result.kind,
                        provenance=_seed_result_provenance(origin),
                    )
                )
            )
            head = self._dataset_lifecycle.current_head()
            if head is None:
                raise RuntimeError("Dataset Head is not ready")
            calendar = canonical_sessions(head.generation.canonical, "Dataset Head")
            current_session = snapshot.track.current_checkpoint_session.isoformat()
            current_index = calendar.index(current_session)
            factor_value = _mapping_value(
                seed_result.get("factor_summary"),
                "Factor Summary",
            )
            strategy_summary = _mapping_value(
                seed_result.get("strategy_summary"),
                "Strategy Summary",
            )
            seed_observations = _mapping_rows(
                seed_result.get("strategy_daily_observations"),
                "Strategy observations",
            )
            observations_by_session = {
                str(item["session"]): dict(item) for item in seed_observations
            }
            projected_strategy_summary: Mapping[str, object] = {
                name: value
                for name, value in strategy_summary.items()
                if name != "benchmark"
            }
            for checkpoint in snapshot.checkpoints[1:]:
                value = _read_publication_json(
                    self._publication,
                    PublishedRef(
                        manifest_sha256=checkpoint.manifest_sha256,
                        kind="daily-track.checkpoint",
                        provenance=checkpoint.provenance,
                    ),
                    payload_name="checkpoint",
                )
                factor_value = _mapping_value(
                    value.get("factor_summary"),
                    "Checkpoint Factor Summary",
                )
                strategy_state = _mapping_value(
                    value.get("strategy_state"),
                    "Checkpoint Strategy State",
                )
                projected_strategy_summary = {
                    "metrics": dict(
                        _mapping_value(
                            strategy_state.get("summary"),
                            "Checkpoint Strategy Summary",
                        )
                    )
                }
                for observation in _mapping_rows(
                    strategy_state.get("retained_delta"),
                    "Checkpoint Strategy observations",
                ):
                    observations_by_session[str(observation["session"])] = dict(
                        observation
                    )
            factor = _public_factor(factor_value)
            universe = _origin_universe(origin)
            recent_strategy_sessions = sorted(observations_by_session)[-504:]
            return DailyTrackDetail.model_validate(
                {
                    "id": str(row["id"]),
                    "status": row["status"],
                    "origin": {
                        "seed_run_id": origin.seed_run_id,
                        "definition_id": origin.definition_id,
                        "definition_revision": origin.definition_revision,
                        "result_checksum_sha256": (
                            origin.verified_result.result_checksum_sha256
                        ),
                        "strategy_session": origin.initial_strategy_state.session,
                    },
                    "strategy_session": current_session,
                    "data_through_session": head.data_through_session,
                    "lag_sessions": len(calendar) - current_index - 1,
                    "blocked_reason": row["blocked_reason"],
                    "factor": factor,
                    "strategy": {
                        "summary": projected_strategy_summary,
                        "benchmark": {
                            "universe": universe,
                            "methodology": "selected_universe_equal_weight",
                        },
                        "observations": [
                            observations_by_session[session]
                            for session in recent_strategy_sessions
                        ],
                    },
                }
            )
        except Exception as error:
            logger.error(
                "current-data DailyTrack detail read failed",
                extra={"track_id": track_id, "error_type": type(error).__name__},
            )
            raise DailyTrackDetailUnavailable("DailyTrack detail is unavailable") from error

    def verify_persisted_equivalence(
        self,
        track_id: str,
    ) -> DailyTrackEquivalenceEvidence:
        """Verify the authoritative session-coordinate Checkpoint chain read-only."""
        if self._publication is None or self._dataset_lifecycle is None:
            raise RuntimeError("DailyTrack equivalence dependencies are not configured")
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT track.origin
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                WHERE track.id = %s
                """,
                (track_id,),
            ).fetchone()
        if row is None:
            raise KeyError(track_id)
        origin = TrackingOrigin.model_validate(row["origin"])
        snapshot = self._session_coordinates.load(track_id)
        head = self._dataset_lifecycle.current_head()
        if head is None:
            raise RuntimeError("Dataset Head is not ready")
        canonical = head.generation.canonical
        calendar = canonical_sessions(canonical, "Dataset Head")
        checkpoints = snapshot.checkpoints
        if not checkpoints or checkpoints[0].progression_id is not None:
            raise DailyTrackEquivalenceMismatch(
                "EQUIVALENCE_MISMATCH at $.tracking_origin.checkpoint"
            )
        activation = _read_publication_json(
            self._publication,
            PublishedRef(
                manifest_sha256=checkpoints[0].manifest_sha256,
                kind="daily-track.checkpoint",
                provenance=checkpoints[0].provenance,
            ),
            payload_name="checkpoint",
        )
        terminal = _mapping_value(
            activation.get("terminal_strategy_state"),
            "Activation Terminal Strategy State",
        )
        _assert_equivalent(
            terminal,
            origin.initial_strategy_state.model_dump(mode="json"),
            "$.tracking_origin.terminal_strategy_state",
        )
        origin_session = snapshot.track.origin_session.isoformat()
        if origin_session not in calendar:
            raise DailyTrackEquivalenceMismatch(
                "EQUIVALENCE_MISMATCH at $.tracking_origin.session"
            )

        progressions = {
            progression.id: progression
            for progression in snapshot.progressions
            if progression.status == "succeeded"
        }
        evidence_sha256s: list[str] = []
        session_sequence = [origin_session]
        predecessor_manifest = checkpoints[0].manifest_sha256
        predecessor_session = origin_session
        for index, checkpoint in enumerate(checkpoints[1:], start=1):
            progression = progressions.get(str(checkpoint.progression_id))
            coordinate = f"$.checkpoints.{index}"
            if progression is None:
                raise DailyTrackEquivalenceMismatch(
                    f"EQUIVALENCE_MISMATCH at {coordinate}.progression"
                )
            target_sessions = tuple(
                session.isoformat() for session in progression.target_sessions
            )
            expected_start = calendar.index(predecessor_session) + 1
            expected_end = calendar.index(checkpoint.boundary_session.isoformat()) + 1
            if tuple(calendar[expected_start:expected_end]) != target_sessions:
                raise DailyTrackEquivalenceMismatch(
                    f"EQUIVALENCE_MISMATCH at {coordinate}.target_sessions"
                )
            if (
                checkpoint.predecessor_manifest_sha256 != predecessor_manifest
                or progression.predecessor_checkpoint_manifest_sha256
                != predecessor_manifest
                or progression.checkpoint_manifest_sha256
                != checkpoint.manifest_sha256
            ):
                raise DailyTrackEquivalenceMismatch(
                    f"EQUIVALENCE_MISMATCH at {coordinate}.predecessor"
                )
            value = _read_publication_json(
                self._publication,
                PublishedRef(
                    manifest_sha256=checkpoint.manifest_sha256,
                    kind="daily-track.checkpoint",
                    provenance=checkpoint.provenance,
                ),
                payload_name="checkpoint",
            )
            boundary_index = calendar.index(checkpoint.boundary_session.isoformat())
            state = restore_tracking_checkpoint(
                value,
                canonical=slice_canonical_sessions(
                    canonical,
                    calendar[: boundary_index + 1],
                ),
            )
            _assert_equivalent(
                state.boundary_session,
                str(checkpoint.terminal_strategy_state["session"]),
                f"{coordinate}.terminal_strategy_state.session",
            )
            evidence_sha256s.append(
                hashlib.sha256(equivalence_bytes(value)).hexdigest()
            )
            session_sequence.extend(target_sessions)
            predecessor_manifest = checkpoint.manifest_sha256
            predecessor_session = checkpoint.boundary_session.isoformat()

        head_session = snapshot.track.current_checkpoint_session.isoformat()
        if predecessor_manifest != snapshot.track.current_checkpoint_manifest_sha256:
            raise DailyTrackEquivalenceMismatch(
                "EQUIVALENCE_MISMATCH at $.tracking_head.checkpoint"
            )
        if predecessor_session != head_session:
            raise DailyTrackEquivalenceMismatch(
                "EQUIVALENCE_MISMATCH at $.tracking_head.session"
            )
        final_evidence = (
            evidence_sha256s[-1]
            if evidence_sha256s
            else hashlib.sha256(equivalence_bytes(terminal)).hexdigest()
        )
        return DailyTrackEquivalenceEvidence(
            status="equivalent",
            track_id=track_id,
            head_session=head_session,
            session_sequence=tuple(session_sequence),
            checkpoint_count=len(checkpoints) - 1,
            checkpoint_evidence_sha256s=tuple(evidence_sha256s),
            final_evidence_sha256=final_evidence,
        )

    def _claim_current(self) -> _SessionProgressionClaim | None:
        if self._dataset_lifecycle is None or self._generation_store is None:
            return None
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT track.id, track.origin, track.execution_fence,
                       checkpoint.boundary_session,
                       checkpoint.manifest_sha256,
                       checkpoint.provenance
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                JOIN daily_tracks.session_checkpoints AS checkpoint
                  ON checkpoint.track_id = state.track_id
                 AND checkpoint.manifest_sha256 =
                        state.current_checkpoint_manifest_sha256
                WHERE track.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM daily_tracks.session_progressions AS progression
                      WHERE progression.track_id = track.id
                        AND progression.status = 'blocked'
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM daily_tracks.session_progression_attempts AS attempt
                      WHERE attempt.track_id = track.id
                        AND attempt.status = 'running'
                  )
                ORDER BY track.created_at, track.id
                FOR UPDATE OF track, state SKIP LOCKED
                """
            ).fetchall()
            for row in rows:
                attempt_id = f"track_attempt_{uuid4().hex[:20]}"
                pin = self._dataset_lifecycle.pin_current_in_transaction(
                    transaction,
                    owner_kind="tracking_advance_attempt",
                    owner_id=attempt_id,
                    lease_seconds=self._lease_seconds,
                )
                generation = self._generation_store.open_generation(
                    pin.generation_manifest_sha256
                )
                calendar = canonical_sessions(generation.canonical, "Data Generation")
                current_session = row["boundary_session"].isoformat()
                try:
                    current_index = calendar.index(current_session)
                except ValueError as error:
                    raise RuntimeError(
                        "DailyTrack Checkpoint is outside current data"
                    ) from error
                target_sessions = tuple(calendar[current_index + 1 :])
                if not target_sessions:
                    self._dataset_lifecycle.release_pin_in_transaction(
                        transaction,
                        pin.id,
                        owner_id=attempt_id,
                    )
                    continue
                fence = int(row["execution_fence"]) + 1
                progression_provenance: dict[str, object] = {
                    "schema_version": "daily-track-progression-v1",
                    "target_start_session": target_sessions[0],
                    "target_end_session": target_sessions[-1],
                }
                existing = transaction.execute(
                    """
                    SELECT id,
                           predecessor_checkpoint_manifest_sha256,
                           COALESCE((
                               SELECT max(ordinal)
                               FROM daily_tracks.session_progression_attempts
                               WHERE progression_id = progression.id
                           ), 0) AS latest_ordinal
                    FROM daily_tracks.session_progressions AS progression
                    WHERE track_id = %s AND status = 'running'
                    FOR UPDATE
                    """,
                    (row["id"],),
                ).fetchone()
                if existing is None:
                    progression_id = f"track_progression_{uuid4().hex[:20]}"
                    ordinal = 1
                    self._session_coordinates.start_progression(
                        transaction,
                        progression_id=progression_id,
                        track_id=str(row["id"]),
                        expected_checkpoint_manifest_sha256=str(
                            row["manifest_sha256"]
                        ),
                        generation_sessions=tuple(
                            _session_date(value) for value in calendar
                        ),
                        target_sessions=tuple(
                            _session_date(value) for value in target_sessions
                        ),
                        data_generation_id=pin.generation_manifest_sha256,
                        provenance=progression_provenance,
                    )
                else:
                    if existing["predecessor_checkpoint_manifest_sha256"] != row[
                        "manifest_sha256"
                    ]:
                        raise DailyTrackFenced
                    progression_id = str(existing["id"])
                    ordinal = int(existing["latest_ordinal"]) + 1
                    updated_progression = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET target_sessions = %s, target_start_session = %s,
                            target_end_session = %s, data_generation_id = %s,
                            provenance = %s, finished_at = NULL
                        WHERE id = %s AND track_id = %s AND status = 'running'
                          AND predecessor_checkpoint_manifest_sha256 = %s
                        """,
                        (
                            [_session_date(value) for value in target_sessions],
                            _session_date(target_sessions[0]),
                            _session_date(target_sessions[-1]),
                            pin.generation_manifest_sha256,
                            Jsonb(progression_provenance),
                            progression_id,
                            row["id"],
                            row["manifest_sha256"],
                        ),
                    )
                    if updated_progression.rowcount != 1:
                        raise DailyTrackFenced
                self._session_coordinates.start_attempt(
                    transaction,
                    attempt_id=attempt_id,
                    progression_id=progression_id,
                    ordinal=ordinal,
                    fence=fence,
                    generation_pin_id=pin.id,
                    data_generation_id=pin.generation_manifest_sha256,
                    data_through_session=_session_date(generation.data_through_session),
                    lease_seconds=self._lease_seconds,
                )
                updated = transaction.execute(
                    """
                    UPDATE daily_tracks.tracks
                    SET execution_fence = %s
                    WHERE id = %s AND execution_fence = %s
                    """,
                    (fence, row["id"], fence - 1),
                )
                if updated.rowcount != 1:
                    raise DailyTrackFenced
                return _SessionProgressionClaim(
                    track_id=str(row["id"]),
                    progression_id=progression_id,
                    attempt_id=attempt_id,
                    fence=fence,
                    generation_pin_id=pin.id,
                    data_generation_id=pin.generation_manifest_sha256,
                    data_through_session=generation.data_through_session,
                    origin=TrackingOrigin.model_validate(row["origin"]),
                    predecessor_manifest_sha256=str(row["manifest_sha256"]),
                    predecessor_provenance=dict(row["provenance"]),
                    current_session=current_session,
                    target_sessions=target_sessions,
                    canonical=generation.canonical,
                )
        return None

    def _recover_expired_current(self) -> bool:
        if self._dataset_lifecycle is None:
            return False
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT track.id AS track_id, track.execution_fence,
                       progression.id AS progression_id,
                       attempt.id AS attempt_id, attempt.fence,
                       attempt.generation_pin_id
                FROM daily_tracks.session_progression_attempts AS attempt
                JOIN daily_tracks.session_progressions AS progression
                  ON progression.id = attempt.progression_id
                JOIN daily_tracks.tracks AS track ON track.id = progression.track_id
                WHERE track.status = 'active'
                  AND track.execution_fence = attempt.fence
                  AND progression.status = 'running'
                  AND attempt.status = 'running'
                  AND attempt.lease_expires_at <= now()
                ORDER BY attempt.lease_expires_at, attempt.id
                FOR UPDATE OF track, progression, attempt SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return False
            attempt = transaction.execute(
                """
                UPDATE daily_tracks.session_progression_attempts
                SET status = 'failed', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now(),
                    failure_reason = %s
                WHERE id = %s AND progression_id = %s
                  AND status = 'running' AND fence = %s
                  AND lease_expires_at <= now()
                """,
                (
                    WORKER_LOST_FAILURE,
                    row["attempt_id"],
                    row["progression_id"],
                    row["fence"],
                ),
            )
            progression = transaction.execute(
                """
                UPDATE daily_tracks.session_progressions
                SET status = 'blocked', finished_at = now()
                WHERE id = %s AND track_id = %s AND status = 'running'
                """,
                (row["progression_id"], row["track_id"]),
            )
            track = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET status = 'blocked', blocked_progression_id = %s,
                    blocked_reason = %s
                WHERE id = %s AND status = 'active' AND execution_fence = %s
                """,
                (
                    row["progression_id"],
                    PUBLIC_BLOCKED_REASON,
                    row["track_id"],
                    row["fence"],
                ),
            )
            if attempt.rowcount != 1 or progression.rowcount != 1 or track.rowcount != 1:
                raise DailyTrackFenced
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                str(row["generation_pin_id"]),
                owner_id=str(row["attempt_id"]),
            )
        return True

    @contextmanager
    def _maintain_current_claim(
        self,
        claim: _SessionProgressionClaim,
    ) -> Iterator[None]:
        stopped = Event()
        heartbeat = Thread(
            target=self._heartbeat_current_claim,
            args=(claim, stopped),
            name=f"daily-track-session-heartbeat-{claim.track_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat.join(timeout=5)

    def _heartbeat_current_claim(
        self,
        claim: _SessionProgressionClaim,
        stopped: Event,
    ) -> None:
        assert self._dataset_lifecycle is not None
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    renewed = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progression_attempts AS attempt
                        SET heartbeat_at = now(),
                            lease_expires_at = now() + make_interval(secs => %s)
                        WHERE attempt.id = %s AND attempt.progression_id = %s
                          AND attempt.fence = %s AND attempt.status = 'running'
                          AND EXISTS (
                              SELECT 1
                              FROM daily_tracks.tracks AS track
                              JOIN daily_tracks.session_progressions AS progression
                                ON progression.track_id = track.id
                               AND progression.id = attempt.progression_id
                              WHERE track.id = %s AND track.status = 'active'
                                AND track.execution_fence = attempt.fence
                                AND progression.status = 'running'
                          )
                        """,
                        (
                            self._lease_seconds,
                            claim.attempt_id,
                            claim.progression_id,
                            claim.fence,
                            claim.track_id,
                        ),
                    )
                    if renewed.rowcount == 1:
                        self._dataset_lifecycle.heartbeat_pin_in_transaction(
                            transaction,
                            claim.generation_pin_id,
                            owner_id=claim.attempt_id,
                            lease_seconds=self._lease_seconds,
                        )
            except Exception as error:
                logger.error(
                    "DailyTrack session claim heartbeat failed",
                    extra={
                        "track_id": claim.track_id,
                        "error_type": type(error).__name__,
                    },
                )
                return
            if renewed.rowcount != 1:
                return

    def _execute_current(
        self,
        claim: _SessionProgressionClaim,
    ) -> tuple[PreparedPublication, dict[str, object], KernelState]:
        assert self._publication is not None
        calendar = canonical_sessions(claim.canonical, "Data Generation")
        current_index = calendar.index(claim.current_session)
        prior_canonical = slice_canonical_sessions(
            claim.canonical,
            calendar[: current_index + 1],
        )
        predecessor = _read_publication_json(
            self._publication,
            PublishedRef(
                manifest_sha256=claim.predecessor_manifest_sha256,
                kind="daily-track.checkpoint",
                provenance=claim.predecessor_provenance,
            ),
            payload_name="checkpoint",
        )
        if predecessor.get("schema_version") == (
            "daily-track-activation-checkpoint-v1"
        ):
            terminal = _mapping_value(
                predecessor.get("terminal_strategy_state"),
                "Activation Terminal Strategy State",
            )
            prior = restore_tracking_origin(claim.origin, terminal, prior_canonical)
        else:
            prior = _state_from_payload(predecessor, prior_canonical)
        continuation = self._current_continuation(
            claim,
            predecessor,
            prior,
            prior_canonical,
        )
        state = self._advance_kernel(
            AdvanceInput(
                prior_state=prior,
                target_canonical_release=claim.canonical,
                appended_sessions=list(claim.target_sessions),
                continuation=continuation,
                calculation_scope="forward_tracking",
            )
        )
        if state.boundary_session != claim.target_sessions[-1]:
            raise RuntimeError("DailyTrack Advance returned an invalid boundary")
        provenance = {
            "schema_version": "daily-track-checkpoint-v2",
            "daily_track_id": claim.track_id,
            "predecessor_manifest_sha256": claim.predecessor_manifest_sha256,
            "boundary_session": state.boundary_session,
            "data_generation_id": claim.data_generation_id,
            "data_through_session": claim.data_through_session,
            "calculation_contracts": claim.origin.calculation_contracts,
        }
        prepared = self._publication.prepare(
            kind="daily-track.checkpoint",
            payloads={
                "checkpoint": JsonPayload(
                    _state_payload(
                        state,
                        retained_strategy_sessions=[
                            claim.current_session,
                            *claim.target_sessions,
                        ],
                    )
                )
            },
            provenance=provenance,
        )
        return prepared, provenance, state

    def _current_continuation(
        self,
        claim: _SessionProgressionClaim,
        predecessor: Mapping[str, object],
        prior: KernelState,
        prior_canonical: dict[str, object],
    ) -> Mapping[str, object]:
        if self._working_cache is not None and predecessor.get(
            "schema_version"
        ) != "daily-track-activation-checkpoint-v1":
            checkpoint = KernelStateCheckpoint.model_validate(predecessor)
            cached = self._working_cache.load(
                track_id=claim.track_id,
                basis_sha256=_continuation_basis_sha256(prior, prior_canonical),
                head_manifest_sha256=claim.predecessor_manifest_sha256,
                fence=claim.fence - 1,
                continuation_sha256=checkpoint.continuation_sha256,
                pending_alpha_sessions=checkpoint.pending_alpha_sessions,
                rolling_factor_rows=checkpoint.rolling_factor_rows,
            )
            if cached is not None:
                return cached
        elif self._working_cache is not None:
            self._working_cache.delete(claim.track_id)
        rebuild_sessions = canonical_sessions(
            prior_canonical,
            "Tracking prior data",
        )[-504:]
        return advance_continuation(
            run_input=prior.run_input_with_canonical(prior_canonical),
            prior_continuation=empty_continuation(),
            target_canonical=prior_canonical,
            appended_sessions=rebuild_sessions,
        )

    def _publish_current(
        self,
        claim: _SessionProgressionClaim,
        prepared: PreparedPublication,
        provenance: dict[str, object],
        state: KernelState,
    ) -> PublishedRef:
        assert self._publication is not None
        assert self._dataset_lifecycle is not None
        published_state = terminal_strategy_state(state)
        with self._database.transaction() as transaction:
            lock_publication_mutation(transaction)
            track = transaction.execute(
                """
                SELECT track.status, track.execution_fence,
                       state.current_checkpoint_manifest_sha256
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                WHERE track.id = %s
                FOR UPDATE OF track, state
                """,
                (claim.track_id,),
            ).fetchone()
            if track != {
                "status": "active",
                "execution_fence": claim.fence,
                "current_checkpoint_manifest_sha256": (
                    claim.predecessor_manifest_sha256
                ),
            }:
                raise DailyTrackFenced
            published = self._publication.record(transaction, prepared)
            self._session_coordinates.publish_checkpoint(
                transaction,
                progression_id=claim.progression_id,
                attempt_id=claim.attempt_id,
                fence=claim.fence,
                checkpoint_manifest_sha256=published.manifest_sha256,
                terminal_strategy_state=published_state,
                provenance=provenance,
            )
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )
        return published

    def _store_current_working_cache(
        self,
        claim: _SessionProgressionClaim,
        published: PublishedRef,
        state: KernelState,
    ) -> None:
        if self._working_cache is None:
            return
        try:
            stored = self._working_cache.store(
                track_id=claim.track_id,
                basis_sha256=_continuation_basis_sha256(
                    state,
                    state.canonical_snapshot(),
                ),
                head_manifest_sha256=published.manifest_sha256,
                fence=claim.fence,
                verified_continuation=continuation_snapshot(state),
            )
        except Exception:
            logger.warning(
                "DailyTrack session Working Cache update failed",
                extra={"track_id": claim.track_id},
                exc_info=True,
            )
            return
        if not stored:
            logger.info(
                "DailyTrack session Working Cache exceeded its bound or was unavailable",
                extra={"track_id": claim.track_id},
            )
            return
        with self._database.transaction() as transaction:
            basis = transaction.execute(
                """
                SELECT track.status, track.execution_fence,
                       state.current_checkpoint_manifest_sha256
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_tracking_states AS state
                  ON state.track_id = track.id
                WHERE track.id = %s
                """,
                (claim.track_id,),
            ).fetchone()
        if basis != {
            "status": "active",
            "execution_fence": claim.fence,
            "current_checkpoint_manifest_sha256": published.manifest_sha256,
        }:
            self._working_cache.delete(claim.track_id)

    def _record_current_failure(
        self,
        claim: _SessionProgressionClaim,
        error: Exception,
    ) -> bool:
        assert self._dataset_lifecycle is not None
        failure_reason = type(error).__name__
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT track.status, track.execution_fence,
                       progression.status AS progression_status,
                       attempt.status AS attempt_status, attempt.fence
                FROM daily_tracks.tracks AS track
                JOIN daily_tracks.session_progressions AS progression
                  ON progression.track_id = track.id
                JOIN daily_tracks.session_progression_attempts AS attempt
                  ON attempt.progression_id = progression.id
                WHERE track.id = %s AND progression.id = %s AND attempt.id = %s
                FOR UPDATE OF track, progression, attempt
                """,
                (claim.track_id, claim.progression_id, claim.attempt_id),
            ).fetchone()
            if row != {
                "status": "active",
                "execution_fence": claim.fence,
                "progression_status": "running",
                "attempt_status": "running",
                "fence": claim.fence,
            }:
                return False
            attempt = transaction.execute(
                """
                UPDATE daily_tracks.session_progression_attempts
                SET status = 'failed', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now(),
                    failure_reason = %s
                WHERE id = %s AND progression_id = %s
                  AND status = 'running' AND fence = %s
                """,
                (
                    failure_reason,
                    claim.attempt_id,
                    claim.progression_id,
                    claim.fence,
                ),
            )
            progression = transaction.execute(
                """
                UPDATE daily_tracks.session_progressions
                SET status = 'blocked', finished_at = now()
                WHERE id = %s AND track_id = %s AND status = 'running'
                """,
                (claim.progression_id, claim.track_id),
            )
            track = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET status = 'blocked', blocked_progression_id = %s,
                    blocked_reason = %s
                WHERE id = %s AND status = 'active' AND execution_fence = %s
                """,
                (
                    claim.progression_id,
                    PUBLIC_BLOCKED_REASON,
                    claim.track_id,
                    claim.fence,
                ),
            )
            if attempt.rowcount != 1 or progression.rowcount != 1 or track.rowcount != 1:
                raise DailyTrackFenced
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )
        return True


_TRACK_SELECT = """
SELECT track.id, track.status, track.origin, track.blocked_reason,
       checkpoint.boundary_session::text AS current_strategy_session
FROM daily_tracks.tracks AS track
JOIN daily_tracks.session_tracking_states AS state
  ON state.track_id = track.id
JOIN daily_tracks.session_checkpoints AS checkpoint
  ON checkpoint.track_id = state.track_id
 AND checkpoint.manifest_sha256 = state.current_checkpoint_manifest_sha256
"""


def _retry_fingerprint(track_id: str) -> str:
    value = {
        "action": "daily-tracks.retry/v1",
        "track_id": track_id,
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _stop_fingerprint(track_id: str) -> str:
    value = {
        "action": "daily-tracks.stop/v1",
        "track_id": track_id,
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _session_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise RuntimeError("DailyTrack session is invalid") from error


def _summary(row: object) -> DailyTrackSummary:
    assert isinstance(row, dict)
    origin = TrackingOrigin.model_validate(row["origin"])
    verified_result = origin.verified_result
    return DailyTrackSummary(
        id=str(row["id"]),
        status=row["status"],
        seed_run_id=origin.seed_run_id,
        definition_id=origin.definition_id,
        definition_revision=origin.definition_revision,
        result_checksum_sha256=verified_result.result_checksum_sha256,
        origin_session=origin.initial_strategy_state.session,
        strategy_session=str(row["current_strategy_session"]),
    )


def _seed_result_provenance(origin: TrackingOrigin) -> dict[str, object]:
    semantic_versions = _mapping_value(
        origin.immutable_input.get("semantic_versions"),
        "Tracking semantic versions",
    )
    return {
        "schema_version": origin.verified_result.schema_version,
        "research_run_id": origin.seed_run_id,
        "immutable_input_sha256": hashlib.sha256(
            canonical_json_bytes(origin.immutable_input)
        ).hexdigest(),
        "data_generation_id": origin.seed_data_generation_id,
        "data_through_session": origin.seed_data_through_session,
        "calculation_contracts": origin.calculation_contracts,
        "semantic_versions": dict(semantic_versions),
    }


def _origin_universe(origin: TrackingOrigin) -> str:
    definition = _mapping_value(
        origin.immutable_input.get("definition"),
        "Tracking Definition",
    )
    content = _mapping_value(definition.get("content"), "Tracking Definition content")
    universe = content.get("universe")
    if not isinstance(universe, str) or not universe:
        raise RuntimeError("Tracking Universe is invalid")
    return universe


def _public_factor(value: Mapping[str, object]) -> dict[str, object]:
    horizons = _mapping_value(value.get("horizons"), "Factor horizons")
    if set(horizons) != {"1", "5", "20"}:
        raise RuntimeError("Factor horizons are invalid")
    return {
        "horizons": {
            name: {
                "horizon": _mapping_value(horizons[name], "Factor horizon").get("horizon"),
                "summary": _mapping_value(
                    _mapping_value(horizons[name], "Factor horizon").get("summary"),
                    "Factor summary",
                ),
                "coverage": _mapping_value(
                    _mapping_value(horizons[name], "Factor horizon").get("coverage"),
                    "Factor coverage",
                ),
            }
            for name in ("1", "5", "20")
        }
    }


def _read_publication_json(
    publication: Publication,
    published_ref: PublishedRef,
    *,
    payload_name: str,
) -> Mapping[str, object]:
    bundle = publication.read(published_ref)
    payload = bundle.payloads.get(payload_name)
    if payload is None or payload.media_type != "application/json":
        raise RuntimeError("DailyTrack product payload is missing")
    value = json.loads(payload.content)
    return _mapping_value(value, "DailyTrack product payload")


def _mapping_value(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{name} is invalid")
    return value


def _mapping_rows(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise RuntimeError(f"{name} is invalid")
    return value


def _assert_equivalent(actual: object, expected: object, coordinate: str) -> None:
    divergence = first_divergence(actual, expected)
    if not divergence:
        return
    suffix = divergence[1:] if divergence.startswith("$") else divergence
    raise DailyTrackEquivalenceMismatch(f"EQUIVALENCE_MISMATCH at {coordinate}{suffix}")


def _continuation_basis_sha256(
    state: KernelState,
    canonical: dict[str, object],
) -> str:
    run_input = state.run_input_with_canonical(canonical)
    expression = validate_normalized_alpha(
        run_input.alpha_expression_snapshot(),
        field_bindings=run_input.field_bindings_snapshot(),
    )
    sessions = canonical_sessions(canonical, "Working Cache canonical basis")
    dependency_sessions = sessions[-(504 + expression.effective_lookback) :]
    dependency = slice_canonical_sessions(canonical, dependency_sessions)
    return hashlib.sha256(canonical_json_bytes(dependency)).hexdigest()


def _state_payload(
    state: KernelState,
    *,
    retained_strategy_sessions: list[str],
) -> dict[str, object]:
    return KernelStateCheckpoint.model_validate(
        project_tracking_checkpoint(
            state,
            retained_strategy_sessions=retained_strategy_sessions,
        )
    ).model_dump(mode="json")


def _state_from_payload(
    value: Mapping[str, object],
    canonical: dict[str, object],
) -> KernelState:
    checkpoint = KernelStateCheckpoint.model_validate(value)
    return restore_tracking_checkpoint(
        checkpoint.model_dump(mode="json"),
        canonical=canonical,
    )
