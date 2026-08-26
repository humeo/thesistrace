from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from psycopg import OperationalError
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.daily_track.cache import _DailyTrackWorkingCache
from thesistrace.daily_track.calculation import (
    origin_calculation_start_index,
    origin_neutralization,
    origin_universe,
)
from thesistrace.daily_track.checkpoint import restore_tracking_checkpoint
from thesistrace.daily_track.execution import (
    ExecutionEvent,
    SupervisedTrackingExecution,
    SupervisedTrackingExecutor,
    TrackingExecutionCancelled,
    TrackingExecutionOwnershipLost,
    TrackingExecutionRequest,
    TrackingExecutionResult,
)
from thesistrace.daily_track.failure_policy import (
    tracking_attempt_failure_code,
    tracking_attempt_retry_eligible,
)
from thesistrace.daily_track.models import (
    DAILY_TRACK_RESULT_SECTIONS,
    DailyTrackDetail,
    DailyTrackList,
    DailyTrackPollingDetail,
    DailyTrackRetryOutcome,
    DailyTrackStopOutcome,
    DailyTrackSummary,
    KernelStateCheckpoint,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
    TrackingOrigin,
    daily_track_polling_retry_after_seconds,
)
from thesistrace.daily_track.planning import (
    DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES,
    MAX_CHUNK_SESSION_COUNT,
    plan_tracking_advance,
)
from thesistrace.daily_track.session_persistence import SessionCoordinateRepository
from thesistrace.data import (
    DatasetLifecycle,
    MountedGenerationStore,
)
from thesistrace.data.dependencies import DataDependencies, resolve_data_dependencies
from thesistrace.data.models import FinancialResearchReadiness
from thesistrace.operational_events import non_blocking_operational_event_sink
from thesistrace.publication import (
    JsonPayload,
    PreparedPublication,
    Publication,
    PublicationPreparationError,
    PublicationUnavailableError,
    PublishedRef,
    VerifiedBundle,
    lock_publication_mutation,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import (
    equivalence_bytes,
    first_divergence,
)
from thesistrace.research_series import (
    research_sessions,
    slice_research_sessions,
)

Progress = Callable[[str, str, str], None]
ResultBundleReader = Callable[[VerifiedBundle], dict[str, object]]
SeedResearchExists = Callable[[PostgresTransaction, str], bool]
ResearchReferencesResult = Callable[[PostgresTransaction, str], bool]
ATTEMPT_LEASE_SECONDS = 15 * 60
ATTEMPT_HEARTBEAT_SECONDS = 30
WORKER_LOST_FAILURE = "WorkerLost"
ACTIVE_DAILY_TRACK_LIMIT = 10
PUBLIC_BLOCKED_REASON = "DailyTrack could not process the current dataset."
CAPACITY_BLOCKED_REASON = "DailyTrack target exceeds Tracking Worker capacity."
FINANCIAL_COVERAGE_BLOCKED_REASON = "Financial Coverage ends before the next Research Session."
INDUSTRY_COVERAGE_BLOCKED_REASON = "Industry Coverage ends before the next Research Session."
INFRASTRUCTURE_EXHAUSTED_BLOCKED_REASON = (
    "DailyTrack exhausted its automatic infrastructure retries."
)
_TRACKING_ELIGIBILITY_SELECT = """
    SELECT track.id, track.origin, track.execution_fence,
           checkpoint.boundary_session,
           checkpoint.manifest_sha256,
           checkpoint.provenance
    FROM daily_tracks.tracks AS track
    JOIN daily_tracks.session_tracking_states AS state
      ON state.track_id = track.id
    JOIN daily_tracks.session_checkpoints AS checkpoint
      ON checkpoint.track_id = state.track_id
     AND checkpoint.manifest_sha256 = state.current_checkpoint_manifest_sha256
    LEFT JOIN daily_tracks.session_progressions AS pending
      ON pending.track_id = track.id AND pending.status = 'running'
    WHERE track.status = 'active'
      AND checkpoint.boundary_session < %s
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
      AND (
          pending.id IS NULL
          OR (
              pending.next_attempt_eligible_at <= now()
              AND pending.queue_position IS NOT NULL
          )
      )
"""


def _attempt_owner_lock(attempt_id: str) -> str:
    return f"daily-track-attempt-owner:{attempt_id}"


class DailyTrackFenced(RuntimeError):
    pass


class DailyTrackActivationLimitReached(RuntimeError):
    pass


class DailyTrackAlreadyExists(RuntimeError):
    pass


class DailyTrackProgressionFailed(RuntimeError):
    pass


class FinancialCoverageUnavailable(RuntimeError):
    pass


class IndustryCoverageUnavailable(RuntimeError):
    pass


class DailyTrackEquivalenceMismatch(RuntimeError):
    pass


class DailyTrackDetailUnavailable(RuntimeError):
    pass


class DailyTrackTemporarilyUnavailable(RuntimeError):
    pass


class DailyTrackInvalidCursor(ValueError):
    pass


class DailyTrackRetryConflict(RuntimeError):
    pass


class DailyTrackRetryUnavailable(RuntimeError):
    pass


class DailyTrackStopConflict(RuntimeError):
    pass


class DailyTrackStopUnavailable(RuntimeError):
    pass


class DailyTrackDeleteConflict(RuntimeError):
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
    cycle_ordinal: int
    cycle_attempt_ordinal: int
    fence: int
    generation_pin_id: str
    data_generation_id: str
    data_through_session: str
    origin: TrackingOrigin
    predecessor_manifest_sha256: str
    predecessor_provenance: dict[str, object]
    current_session: str
    target_sessions: tuple[str, ...]
    financial_research_readiness: FinancialResearchReadiness
    financial_coverage_unavailable: bool
    industry_coverage_unavailable: bool


@dataclass(frozen=True)
class _BlockedProgressionCreated:
    track_id: str
    progression_id: str


@dataclass(frozen=True)
class _TrackingFailure:
    track_id: str
    attempt_id: str
    attempt_number: int
    retry: bool
    failure_code: str
    attempt_level: str


@dataclass(frozen=True)
class _StoppedTrack:
    track_id: str
    attempt_id: str | None = None


class DailyTrackService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        publication: Publication | None = None,
        dataset_lifecycle: DatasetLifecycle | None = None,
        generation_store: MountedGenerationStore | None = None,
        read_result_bundle: ResultBundleReader,
        progress: Progress | None = None,
        lease_seconds: float = ATTEMPT_LEASE_SECONDS,
        heartbeat_seconds: float = ATTEMPT_HEARTBEAT_SECONDS,
        working_cache_root: Path | None = None,
        seed_research_exists: SeedResearchExists | None = None,
        research_references_result: ResearchReferencesResult | None = None,
        execution_memory_bytes: int = DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES,
        lifecycle_event: ExecutionEvent | None = None,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0 or execution_memory_bytes <= 0:
            raise ValueError("DailyTrack lease and heartbeat intervals must be positive")
        self._database = database
        self._publication = publication
        self._dataset_lifecycle = dataset_lifecycle
        self._generation_store = generation_store
        self._read_result_bundle = read_result_bundle
        self._session_coordinates = SessionCoordinateRepository(database)
        self._executor = (
            None
            if generation_store is None
            else SupervisedTrackingExecutor(
                generation_store.root,
                execution_memory_bytes=execution_memory_bytes,
            )
        )
        self._progress = progress or (lambda _stage, _track_id, _target_id: None)
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._working_cache = (
            None if working_cache_root is None else _DailyTrackWorkingCache(working_cache_root)
        )
        self._seed_research_exists = seed_research_exists
        self._research_references_result = research_references_result
        self._execution_memory_bytes = execution_memory_bytes
        self._lifecycle_event = non_blocking_operational_event_sink(
            lifecycle_event or (lambda _event: None),
            component="core_api",
        )
        self._child_watchdog_grace_seconds = min(
            5.0,
            (lease_seconds - heartbeat_seconds) / 2,
        )
        if self._child_watchdog_grace_seconds <= 0:
            raise ValueError("DailyTrack lease must exceed its heartbeat interval")

    @property
    def execution_memory_bytes(self) -> int:
        return self._execution_memory_bytes

    def references_result_manifest(
        self,
        transaction: PostgresTransaction,
        manifest_sha256: str,
    ) -> bool:
        return (
            transaction.execute(
                """
            SELECT 1
            FROM daily_tracks.tracks
            WHERE origin #>> '{verified_result,result_manifest_sha256}' = %s
            LIMIT 1
            """,
                (manifest_sha256,),
            ).fetchone()
            is not None
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
        if row is not None:
            raise DailyTrackAlreadyExists("ResearchRun already has a DailyTrack")
        capacity = transaction.execute(
            """
            SELECT count(*) AS count
            FROM daily_tracks.tracks
            WHERE status IN ('active', 'blocked', 'stopping')
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

    def process_next(
        self,
        *,
        on_claim: Callable[[str, str], None] | None = None,
        on_execution_event: ExecutionEvent | None = None,
    ) -> bool:
        emit = non_blocking_operational_event_sink(
            on_execution_event or (lambda _event: None),
            component="tracking_worker",
            worker_role="tracking",
        )
        recovered_stop = self._recover_stopping_attempt()
        if recovered_stop is not None:
            emit(_tracking_stopped_event(recovered_stop))
            return True
        recovered_failure = self._recover_expired_current()
        if recovered_failure is not None:
            _emit_tracking_failure(emit, recovered_failure)
            return True
        selected = self._claim_current(self._execution_memory_bytes)
        if isinstance(selected, _BlockedProgressionCreated):
            self._progress("blocked", selected.track_id, selected.progression_id)
            emit(
                _tracking_event(
                    "daily_track_blocked",
                    level="WARNING",
                    track_id=selected.track_id,
                    status="blocked",
                    failure_code="CAPACITY_EXCEEDED",
                )
            )
            return True
        current_claim = selected
        if current_claim is not None:
            with self._database.session_advisory_lock(
                _attempt_owner_lock(current_claim.attempt_id)
            ):
                if on_claim is not None:
                    try:
                        on_claim(current_claim.track_id, current_claim.attempt_id)
                    except Exception:
                        pass
                emit(
                    _tracking_event(
                        "tracking_attempt_started",
                        track_id=current_claim.track_id,
                        attempt_id=current_claim.attempt_id,
                        attempt_number=current_claim.cycle_attempt_ordinal,
                        status="running",
                    )
                )
                emit(
                    _tracking_event(
                        "tracking_advance_started",
                        track_id=current_claim.track_id,
                        attempt_id=current_claim.attempt_id,
                        status="running",
                    )
                )
                self._progress(
                    "claimed",
                    current_claim.track_id,
                    current_claim.data_generation_id,
                )

                def execution_event(event: dict[str, object]) -> None:
                    if event.get("event") == "tracking_execution_progress":
                        phase = str(event["phase"])
                        self._record_current_progress(
                            current_claim,
                            phase=phase,
                            current_session=str(event["current_session"]),
                        )
                        if phase == "result_ready":
                            emit(
                                _tracking_event(
                                    "tracking_phase_completed",
                                    track_id=current_claim.track_id,
                                    attempt_id=current_claim.attempt_id,
                                    phase="calculating",
                                )
                            )
                        emit(event)
                        return
                    emit(event)

                execution: SupervisedTrackingExecution | None = None
                failure: Exception | None = None
                stopping_pending = False
                stop_monitor: Thread | None = None
                stop_monitor_finished = Event()

                def observe_stop_pending() -> None:
                    nonlocal failure, stopping_pending
                    try:
                        stopping_pending = stopping_pending or self._stop_is_pending(current_claim)
                    except Exception as error:
                        if failure is None:
                            failure = error

                with self._maintain_current_claim(current_claim, emit) as authority_lost:
                    try:
                        execution = self._execute_current(
                            current_claim,
                            emit=execution_event,
                            authority_lost=authority_lost,
                            stop_requested=lambda: self._stop_is_pending(current_claim),
                        )
                        stop_monitor = Thread(
                            target=self._monitor_current_stop,
                            args=(current_claim, execution, stop_monitor_finished, emit),
                            name=f"daily-track-stop-monitor-{current_claim.track_id}",
                            daemon=True,
                        )
                        stop_monitor.start()
                        self._record_current_progress(
                            current_claim,
                            phase="staging",
                            current_session=current_claim.target_sessions[-1],
                        )
                        emit(
                            _tracking_event(
                                "tracking_phase_completed",
                                track_id=current_claim.track_id,
                                attempt_id=current_claim.attempt_id,
                                phase="result_ready",
                            )
                        )
                        prepared, provenance = self._prepare_current_result(
                            current_claim,
                            execution.result,
                        )
                        self._progress(
                            "prepared",
                            current_claim.track_id,
                            current_claim.data_generation_id,
                        )
                        execution.acknowledge(
                            stop_requested=lambda: self._stop_is_pending(current_claim)
                        )
                        published = self._publish_current(
                            current_claim,
                            prepared,
                            provenance,
                            execution.result.terminal_strategy_state,
                        )
                        emit(
                            _tracking_event(
                                "tracking_phase_completed",
                                track_id=current_claim.track_id,
                                attempt_id=current_claim.attempt_id,
                                phase="staging",
                            )
                        )
                        emit(
                            _tracking_event(
                                "tracking_checkpoint_published",
                                track_id=current_claim.track_id,
                                attempt_id=current_claim.attempt_id,
                                status="succeeded",
                            )
                        )
                        emit(
                            _tracking_event(
                                "tracking_head_advanced",
                                track_id=current_claim.track_id,
                                attempt_id=current_claim.attempt_id,
                                status="active",
                            )
                        )
                        self._store_current_working_cache(
                            current_claim,
                            published,
                            execution.result,
                            emit,
                        )
                        self._progress(
                            "published",
                            current_claim.track_id,
                            current_claim.data_generation_id,
                        )
                    except TrackingExecutionCancelled:
                        stopping_pending = True
                    except Exception as error:
                        failure = error
                    finally:
                        if execution is not None:
                            observe_stop_pending()
                            if stopping_pending:
                                execution.cancel()
                            else:
                                execution.close()
                        stop_monitor_finished.set()
                        if stop_monitor is not None:
                            stop_monitor.join(timeout=5)
                observe_stop_pending()
                if stopping_pending:
                    if self._confirm_stopped(current_claim):
                        emit(
                            _tracking_stopped_event(
                                _StoppedTrack(
                                    track_id=current_claim.track_id,
                                    attempt_id=current_claim.attempt_id,
                                )
                            )
                        )
                elif isinstance(failure, DailyTrackFenced):
                    emit(
                        _tracking_event(
                            "tracking_attempt_fenced",
                            track_id=current_claim.track_id,
                            attempt_id=current_claim.attempt_id,
                            outcome="fenced",
                        )
                    )
                elif isinstance(failure, FinancialCoverageUnavailable):
                    recorded = self._record_current_failure(
                        current_claim,
                        failure,
                        blocked_reason=FINANCIAL_COVERAGE_BLOCKED_REASON,
                    )
                    if recorded is None:
                        emit(
                            _tracking_event(
                                "tracking_attempt_fenced",
                                track_id=current_claim.track_id,
                                attempt_id=current_claim.attempt_id,
                                outcome="fenced",
                            )
                        )
                    else:
                        _emit_tracking_failure(emit, recorded)
                elif isinstance(failure, IndustryCoverageUnavailable):
                    recorded = self._record_current_failure(
                        current_claim,
                        failure,
                        blocked_reason=INDUSTRY_COVERAGE_BLOCKED_REASON,
                    )
                    if recorded is None:
                        emit(
                            _tracking_event(
                                "tracking_attempt_fenced",
                                track_id=current_claim.track_id,
                                attempt_id=current_claim.attempt_id,
                                outcome="fenced",
                            )
                        )
                    else:
                        _emit_tracking_failure(emit, recorded)
                elif failure is not None:
                    recorded = self._record_current_failure(current_claim, failure)
                    if recorded is not None:
                        _emit_tracking_failure(emit, recorded)
                        raise DailyTrackProgressionFailed(
                            "DailyTrack progression failed at its current target"
                        ) from failure
                    emit(
                        _tracking_event(
                            "tracking_attempt_fenced",
                            track_id=current_claim.track_id,
                            attempt_id=current_claim.attempt_id,
                            outcome="fenced",
                        )
                    )
                if not stopping_pending:
                    self._release_cancelled_pin(current_claim)
            return True
        return False

    def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> DailyTrackList:
        if limit < 1 or limit > 50:
            raise ValueError("DailyTrack list limit must be between 1 and 50")
        try:
            with self._database.transaction() as transaction:
                secret = _cursor_secret(transaction)
                cursor_created_at, cursor_id = _decode_cursor(cursor, secret=secret)
                rows = transaction.execute(
                    f"""
                    {_TRACK_SELECT}
                    WHERE (
                        %s::timestamptz IS NULL
                        OR track.created_at < %s::timestamptz
                        OR (
                            track.created_at = %s::timestamptz
                            AND track.id > %s::text
                        )
                    )
                    ORDER BY track.created_at DESC, track.id
                    LIMIT %s::integer
                    """,
                    (
                        cursor_created_at,
                        cursor_created_at,
                        cursor_created_at,
                        cursor_id,
                        limit + 1,
                    ),
                ).fetchall()
                summaries = [_summary(row) for row in rows[:limit]]
                next_cursor = (
                    _encode_cursor(rows[limit - 1], secret=secret) if len(rows) > limit else None
                )
            return DailyTrackList(items=summaries, next_cursor=next_cursor)
        except (OperationalError, PoolTimeout) as error:
            raise DailyTrackTemporarilyUnavailable(
                "DailyTrack listing is temporarily unavailable"
            ) from error

    def retry(
        self,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackSummary | None:
        outcome = self.retry_with_outcome(track_id, command)
        return None if outcome is None else outcome.track

    def retry_with_outcome(
        self,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackRetryOutcome | None:
        try:
            return self._retry_with_outcome(track_id, command)
        except (OperationalError, PoolTimeout) as error:
            raise DailyTrackTemporarilyUnavailable(
                "DailyTrack Retry is temporarily unavailable"
            ) from error

    def _retry_with_outcome(
        self,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DailyTrackRetryOutcome | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("DailyTrack Retry request_id is required")
        fingerprint = _retry_fingerprint(track_id)
        retry_scheduled = False
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
                track = DailyTrackSummary.model_validate(receipt["outcome"])
                return DailyTrackRetryOutcome(
                    track=track,
                    replayed=True,
                    retry_after_seconds=daily_track_polling_retry_after_seconds(
                        status=track.status,
                        phase="queued" if track.status == "active" else "blocked",
                    ),
                )

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
                SELECT id, target_sessions, current_cycle_ordinal
                FROM daily_tracks.session_progressions
                WHERE track_id = %s AND status = 'blocked'
                FOR UPDATE
                """,
                (track_id,),
            ).fetchone()
            if session_progression is None:
                raise DailyTrackRetryUnavailable("DailyTrack has no blocked session progression")
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
            target_fits = self._retry_target_fits(
                track,
                tuple(value.isoformat() for value in session_progression["target_sessions"]),
            )
            if target_fits:
                progression = transaction.execute(
                    """
                    UPDATE daily_tracks.session_progressions
                    SET status = 'running', finished_at = NULL,
                        current_cycle_ordinal =
                            COALESCE(current_cycle_ordinal, 0) + 1,
                        next_attempt_eligible_at = now(),
                        queue_position = nextval('daily_tracks.work_queue_sequence')
                    WHERE id = %s AND track_id = %s AND status = 'blocked'
                    """,
                    (progression_id, track_id),
                )
                activated = transaction.execute(
                    """
                    UPDATE daily_tracks.tracks
                    SET status = 'active', blocked_progression_id = NULL,
                        blocked_reason = NULL,
                        queue_position = nextval('daily_tracks.work_queue_sequence')
                    WHERE id = %s AND status = 'blocked'
                      AND blocked_progression_id = %s
                    """,
                    (track_id, progression_id),
                )
                if progression.rowcount != 1 or activated.rowcount != 1:
                    raise DailyTrackFenced
                retry_scheduled = True
            outcome = DailyTrackSummary(
                **{
                    **_summary(track).model_dump(mode="python"),
                    "status": "active" if target_fits else "blocked",
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
        if retry_scheduled:
            self._lifecycle_event(
                {
                    "event": "tracking_retry_scheduled",
                    "level": "WARNING",
                    "track_id": track_id,
                    "status": "active",
                }
            )
        return DailyTrackRetryOutcome(
            track=outcome,
            replayed=False,
            retry_after_seconds=daily_track_polling_retry_after_seconds(
                status=outcome.status,
                phase="queued" if outcome.status == "active" else "blocked",
            ),
        )

    def _retry_target_fits(
        self,
        track: Mapping[str, object],
        target_sessions: tuple[str, ...],
    ) -> bool:
        if self._dataset_lifecycle is None or self._generation_store is None:
            raise RuntimeError("current-data DailyTrack Retry is not configured")
        current = self._dataset_lifecycle.current_pointer()
        if current is None:
            return False
        admission = self._generation_store.open_admission(current.generation_manifest_sha256)
        origin = TrackingOrigin.model_validate(track["origin"])
        planning = _origin_planning_facts(origin)
        maximum_universe_cardinality = self._generation_store.maximum_universe_cardinality(
            admission.generation.manifest_sha256,
            universe=origin_universe(origin),
            start_session=target_sessions[0],
            end_session=target_sessions[-1],
        )
        plan = plan_tracking_advance(
            unpublished_sessions=tuple(_session_date(value) for value in target_sessions),
            formula_work=planning["formula_work"],
            node_count=planning["node_count"],
            field_count=planning["field_count"],
            maximum_universe_cardinality=maximum_universe_cardinality,
            effective_lookback=planning["effective_lookback"],
            execution_memory_bytes=self._execution_memory_bytes,
        )
        return not plan.capacity_blocked and len(plan.target_sessions) >= len(target_sessions)

    def stop(
        self,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackSummary | None:
        outcome = self.stop_with_outcome(track_id, command)
        return None if outcome is None else outcome.track

    def stop_with_outcome(
        self,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackStopOutcome | None:
        try:
            return self._stop_with_outcome(track_id, command)
        except (OperationalError, PoolTimeout) as error:
            raise DailyTrackTemporarilyUnavailable(
                "DailyTrack Stop is temporarily unavailable"
            ) from error

    def _stop_with_outcome(
        self,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DailyTrackStopOutcome | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("DailyTrack Stop request_id is required")
        fingerprint = _stop_fingerprint(track_id)
        stopped_after_commit = False
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
                replayed = True
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
                running_attempt = transaction.execute(
                    """
                    SELECT id, progression_id
                    FROM daily_tracks.session_progression_attempts
                    WHERE track_id = %s AND status = 'running'
                    FOR UPDATE
                    """,
                    (track_id,),
                ).fetchone()
                if running_attempt is None:
                    transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET status = 'cancelled', finished_at = now(),
                            next_attempt_eligible_at = NULL,
                            queue_position = NULL
                        WHERE track_id = %s AND status IN ('running', 'blocked')
                        """,
                        (track_id,),
                    )
                    updated = transaction.execute(
                        """
                        UPDATE daily_tracks.tracks
                        SET status = 'stopped', execution_fence = execution_fence + 1,
                            blocked_progression_id = NULL, blocked_reason = NULL
                        WHERE id = %s AND status IN ('active', 'blocked')
                        """,
                        (track_id,),
                    )
                    outcome_status = "stopped"
                    stopped_after_commit = True
                else:
                    attempt = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progression_attempts
                        SET status = 'stopping', heartbeat_at = now(),
                            failure_reason = 'UserStopped'
                        WHERE id = %s AND progression_id = %s
                          AND status = 'running'
                        """,
                        (running_attempt["id"], running_attempt["progression_id"]),
                    )
                    progression = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET status = 'stopping', next_attempt_eligible_at = NULL,
                            queue_position = NULL
                        WHERE id = %s AND track_id = %s AND status = 'running'
                        """,
                        (running_attempt["progression_id"], track_id),
                    )
                    updated = transaction.execute(
                        """
                        UPDATE daily_tracks.tracks
                        SET status = 'stopping', execution_fence = execution_fence + 1,
                            blocked_progression_id = NULL, blocked_reason = NULL
                        WHERE id = %s AND status = 'active'
                        """,
                        (track_id,),
                    )
                    if attempt.rowcount != 1 or progression.rowcount != 1:
                        raise DailyTrackFenced
                    outcome_status = "stopping"
                if updated.rowcount != 1:
                    raise DailyTrackFenced
                outcome = DailyTrackSummary(
                    **{
                        **_summary(track).model_dump(mode="python"),
                        "status": outcome_status,
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
                replayed = False
        if outcome.status == "stopped" and self._working_cache is not None:
            self._working_cache.delete(track_id)
        if stopped_after_commit:
            self._lifecycle_event(
                {
                    "event": "daily_track_stopped",
                    "track_id": track_id,
                    "status": "stopped",
                }
            )
        return DailyTrackStopOutcome(
            track=outcome,
            replayed=replayed,
            retry_after_seconds=daily_track_polling_retry_after_seconds(
                status=outcome.status,
                phase=outcome.status,
            ),
        )

    def delete(self, track_id: str) -> bool:
        if self._publication is None:
            raise RuntimeError("DailyTrack deletion is not configured")
        with self._database.transaction() as transaction:
            lock_publication_mutation(transaction)
            row = transaction.execute(
                """
                SELECT status, origin
                FROM daily_tracks.tracks
                WHERE id = %s
                FOR UPDATE
                """,
                (track_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] != "stopped":
                raise DailyTrackDeleteConflict("DailyTrack deletion requires stopped status")
            origin = TrackingOrigin.model_validate(row["origin"])
            checkpoint_rows = transaction.execute(
                """
                SELECT manifest_sha256
                FROM daily_tracks.session_checkpoints
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchall()
            deleted = transaction.execute(
                "DELETE FROM daily_tracks.tracks WHERE id = %s AND status = 'stopped'",
                (track_id,),
            )
            if deleted.rowcount != 1:
                raise DailyTrackDeleteConflict("DailyTrack deletion lost its stopped state")
            for manifest_sha256 in {
                str(checkpoint["manifest_sha256"]) for checkpoint in checkpoint_rows
            }:
                still_referenced = (
                    transaction.execute(
                        """
                    SELECT 1
                    FROM daily_tracks.session_checkpoints
                    WHERE manifest_sha256 = %s
                    LIMIT 1
                    """,
                        (manifest_sha256,),
                    ).fetchone()
                    is not None
                )
                self._publication.release_manifest_in_transaction(
                    transaction,
                    manifest_sha256,
                    still_referenced=still_referenced,
                )
            seed_manifest_sha256 = origin.verified_result.result_manifest_sha256
            seed_still_referenced = self.references_result_manifest(
                transaction,
                seed_manifest_sha256,
            ) or (
                self._research_references_result is not None
                and self._research_references_result(
                    transaction,
                    seed_manifest_sha256,
                )
            )
            self._publication.release_manifest_in_transaction(
                transaction,
                seed_manifest_sha256,
                still_referenced=seed_still_referenced,
            )
        if self._working_cache is not None:
            self._working_cache.delete(track_id)
        _collect_publication_deletions(
            self._publication,
            lifecycle_event=self._lifecycle_event,
            track_id=track_id,
        )
        return True

    def reconcile_working_cache(
        self,
        *,
        lifecycle_event: ExecutionEvent | None = None,
    ) -> int:
        if self._working_cache is None:
            return 0
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id
                FROM daily_tracks.tracks
                WHERE status IN ('active', 'blocked', 'stopping')
                """
            ).fetchall()
        removed, pending = self._working_cache.reconcile(str(row["id"]) for row in rows)
        if pending:
            (lifecycle_event or self._lifecycle_event)(
                {
                    "event": "tracking_cache_cleanup_deferred",
                    "level": "WARNING",
                    "failure_code": "WORKING_CACHE_CLEANUP_DEFERRED",
                }
            )
        return removed

    def get(self, track_id: str) -> DailyTrackDetail | None:
        return self._get_current(track_id)

    def get_polling_detail(self, track_id: str) -> DailyTrackPollingDetail | None:
        if self._dataset_lifecycle is None:
            raise RuntimeError("current-data DailyTrack polling is not configured")
        try:
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
                row["unresolved_progression"] = transaction.execute(
                    """
                    SELECT progression.status,
                           progression.target_start_session::text,
                           progression.target_end_session::text,
                           cardinality(progression.target_sessions) AS target_session_count,
                           progression.next_attempt_eligible_at::text,
                           progression.next_attempt_eligible_at > now() AS retry_wait,
                           progression.finished_at,
                           attempt.status AS attempt_status,
                           attempt.execution_phase,
                           attempt.current_session::text AS current_session,
                           attempt.started_at
                    FROM daily_tracks.session_progressions AS progression
                    LEFT JOIN LATERAL (
                        SELECT status, execution_phase, current_session, started_at
                        FROM daily_tracks.session_progression_attempts
                        WHERE progression_id = progression.id
                        ORDER BY ordinal DESC
                        LIMIT 1
                    ) AS attempt ON true
                    WHERE progression.track_id = %s
                      AND progression.status IN ('running', 'stopping', 'blocked')
                    """,
                    (track_id,),
                ).fetchone()
                row["observed_at"] = transaction.execute(
                    "SELECT CURRENT_TIMESTAMP AS observed_at"
                ).fetchone()["observed_at"]
            admission = self._dataset_lifecycle.current_admission()
            if admission is None:
                raise RuntimeError("Dataset Head is not ready")
            calendar = list(admission.research_calendar)
            current_session = str(row["current_strategy_session"])
            current_index = calendar.index(current_session)
            lag_sessions = len(calendar) - current_index - 1
            unresolved = row["unresolved_progression"]
            phase = _polling_phase(
                status=str(row["status"]),
                unresolved=unresolved,
                lag_sessions=lag_sessions,
            )
            origin = TrackingOrigin.model_validate(row["origin"])
            return DailyTrackPollingDetail.model_validate(
                {
                    "id": str(row["id"]),
                    "status": row["status"],
                    "origin": {
                        "research_run_id": origin.seed_run_id,
                        "origin_session": origin.initial_strategy_state.session,
                        "result_checksum_sha256": (origin.verified_result.result_checksum_sha256),
                    },
                    "progress": {
                        "head_session": current_session,
                        "data_through_session": admission.generation.data_through_session,
                        "lag_sessions": lag_sessions,
                        "phase": phase,
                        "target_start_session": (
                            None if unresolved is None else unresolved["target_start_session"]
                        ),
                        "target_end_session": (
                            None if unresolved is None else unresolved["target_end_session"]
                        ),
                        "target_session_count": (
                            0 if unresolved is None else unresolved["target_session_count"]
                        ),
                        "current_session": (
                            unresolved["current_session"]
                            if unresolved is not None and unresolved["attempt_status"] == "running"
                            else None
                        ),
                        "retry_wait": (
                            False if unresolved is None else bool(unresolved["retry_wait"])
                        ),
                        "next_retry_eligible_at": (
                            unresolved["next_attempt_eligible_at"]
                            if unresolved is not None and unresolved["retry_wait"]
                            else None
                        ),
                    },
                    "timing": {
                        "activated_at": row["created_at"],
                        "state_updated_at": row["state_updated_at"],
                        "current_action_started_at": (
                            None if unresolved is None else unresolved["started_at"]
                        ),
                        "current_action_finished_at": (
                            None if unresolved is None else unresolved["finished_at"]
                        ),
                        "observed_at": row["observed_at"],
                    },
                    "blocked_reason": row["blocked_reason"],
                    "action_eligibility": {
                        "retry": row["status"] == "blocked",
                        "stop": row["status"] in {"active", "blocked"},
                    },
                    "available_result_sections": list(DAILY_TRACK_RESULT_SECTIONS),
                    "retry_after_seconds": daily_track_polling_retry_after_seconds(
                        status=str(row["status"]),
                        phase=phase,
                    ),
                }
            )
        except (OperationalError, PoolTimeout) as error:
            raise DailyTrackTemporarilyUnavailable(
                "DailyTrack polling is temporarily unavailable"
            ) from error
        except DailyTrackTemporarilyUnavailable:
            raise

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
            if row is not None:
                persisted_origin = TrackingOrigin.model_validate(row["origin"])
                row["seed_research_available"] = (
                    self._seed_research_exists is not None
                    and self._seed_research_exists(
                        transaction,
                        persisted_origin.seed_run_id,
                    )
                )
                row["unresolved_progression"] = transaction.execute(
                    """
                    SELECT progression.status,
                           progression.target_start_session::text,
                           progression.target_end_session::text,
                           cardinality(progression.target_sessions) AS target_session_count,
                           progression.current_cycle_ordinal,
                           progression.next_attempt_eligible_at::text,
                           progression.next_attempt_eligible_at > now() AS retry_wait,
                           attempt.status AS attempt_status,
                           attempt.cycle_attempt_ordinal,
                           attempt.execution_phase,
                           attempt.current_session::text AS current_session
                    FROM daily_tracks.session_progressions AS progression
                    LEFT JOIN LATERAL (
                        SELECT status, execution_phase, current_session,
                               cycle_attempt_ordinal
                        FROM daily_tracks.session_progression_attempts
                        WHERE progression_id = progression.id
                        ORDER BY ordinal DESC
                        LIMIT 1
                    ) AS attempt ON true
                    WHERE progression.track_id = %s
                      AND progression.status IN ('running', 'stopping', 'blocked')
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
                        manifest_sha256=(origin.verified_result.result_manifest_sha256),
                        kind=origin.verified_result.kind,
                        provenance=_seed_result_provenance(origin),
                    )
                )
            )
            admission = self._dataset_lifecycle.current_admission()
            if admission is None:
                raise RuntimeError("Dataset Head is not ready")
            calendar = list(admission.research_calendar)
            current_session = snapshot.track.current_checkpoint_session.isoformat()
            current_index = calendar.index(current_session)
            lag_sessions = len(calendar) - current_index - 1
            unresolved = row["unresolved_progression"]
            if row["status"] == "stopping":
                progress_phase = "stopping"
            elif row["status"] == "stopped":
                progress_phase = "stopped"
            elif unresolved is None:
                progress_phase = "up_to_date" if lag_sessions == 0 else "waiting"
            elif unresolved["status"] == "blocked":
                progress_phase = "blocked"
            elif unresolved["attempt_status"] == "running":
                progress_phase = unresolved["execution_phase"]
            elif unresolved["retry_wait"]:
                progress_phase = "retry_wait"
            else:
                progress_phase = "queued"
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
                name: value for name, value in strategy_summary.items() if name != "benchmark"
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
                    observations_by_session[str(observation["session"])] = dict(observation)
            factor = _public_factor(factor_value)
            universe = origin_universe(origin)
            recent_strategy_sessions = sorted(observations_by_session)[-504:]
            return DailyTrackDetail.model_validate(
                {
                    "id": str(row["id"]),
                    "status": row["status"],
                    "origin": {
                        "seed_run_id": origin.seed_run_id,
                        "seed_research_available": row["seed_research_available"],
                        "result_checksum_sha256": (origin.verified_result.result_checksum_sha256),
                        "strategy_session": origin.initial_strategy_state.session,
                        "terminal_account": {
                            name: getattr(origin.initial_strategy_state, name)
                            for name in (
                                "session",
                                "gross_cash",
                                "net_cash",
                                "gross_nav",
                                "net_nav",
                                "benchmark_nav",
                                "cumulative_transaction_cost",
                                "positions",
                                "rebalance_phase",
                                "pending_signal",
                            )
                        },
                    },
                    "strategy_session": current_session,
                    "data_through_session": admission.generation.data_through_session,
                    "lag_sessions": lag_sessions,
                    "progress": {
                        "head_session": current_session,
                        "lag_sessions": lag_sessions,
                        "phase": progress_phase,
                        "target_start_session": (
                            None if unresolved is None else unresolved["target_start_session"]
                        ),
                        "target_end_session": (
                            None if unresolved is None else unresolved["target_end_session"]
                        ),
                        "target_session_count": (
                            0 if unresolved is None else unresolved["target_session_count"]
                        ),
                        "completed_target_sessions": 0,
                        "current_session": (
                            unresolved["current_session"]
                            if unresolved is not None and unresolved["attempt_status"] == "running"
                            else None
                        ),
                        "cycle_attempt": (
                            None if unresolved is None else unresolved["cycle_attempt_ordinal"]
                        ),
                        "cycle_attempt_limit": 3,
                        "retry_wait": (
                            False if unresolved is None else bool(unresolved["retry_wait"])
                        ),
                        "next_attempt_eligible_at": (
                            unresolved["next_attempt_eligible_at"]
                            if unresolved is not None and unresolved["retry_wait"]
                            else None
                        ),
                    },
                    "blocked_reason": row["blocked_reason"],
                    "factor": factor,
                    "strategy": {
                        "summary": projected_strategy_summary,
                        "benchmark": {
                            "universe": universe,
                            "methodology": "selected_universe_equal_weight",
                        },
                        "observations": [
                            observations_by_session[session] for session in recent_strategy_sessions
                        ],
                    },
                }
            )
        except Exception as error:
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
        head = self._dataset_lifecycle.current_admission()
        if head is None:
            raise RuntimeError("Dataset Head is not ready")
        calendar = list(head.research_calendar)
        calculation_start_index = origin_calculation_start_index(origin, calendar)
        calculation_calendar = calendar[calculation_start_index:]
        generation = self._generation_store.read_composite_slice(
            head.generation.manifest_sha256,
            sessions=calculation_calendar,
            universe_name=origin_universe(origin),
            neutralization=origin_neutralization(origin),
            field_bindings={
                str(key): str(value)
                for key, value in origin.immutable_input["field_bindings"].items()
            },
        )
        research_data = generation.research_data
        research_calendar = research_sessions(research_data)
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
            raise DailyTrackEquivalenceMismatch("EQUIVALENCE_MISMATCH at $.tracking_origin.session")

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
            target_sessions = tuple(session.isoformat() for session in progression.target_sessions)
            expected_start = calendar.index(predecessor_session) + 1
            expected_end = calendar.index(checkpoint.boundary_session.isoformat()) + 1
            if tuple(calendar[expected_start:expected_end]) != target_sessions:
                raise DailyTrackEquivalenceMismatch(
                    f"EQUIVALENCE_MISMATCH at {coordinate}.target_sessions"
                )
            if (
                checkpoint.predecessor_manifest_sha256 != predecessor_manifest
                or progression.predecessor_checkpoint_manifest_sha256 != predecessor_manifest
                or progression.checkpoint_manifest_sha256 != checkpoint.manifest_sha256
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
            boundary_index = research_calendar.index(checkpoint.boundary_session.isoformat())
            state = restore_tracking_checkpoint(
                value,
                research_data=slice_research_sessions(
                    research_data,
                    [research_calendar[boundary_index]],
                ),
            )
            _assert_equivalent(
                state.boundary_session,
                str(checkpoint.terminal_strategy_state["session"]),
                f"{coordinate}.terminal_strategy_state.session",
            )
            evidence_sha256s.append(hashlib.sha256(equivalence_bytes(value)).hexdigest())
            session_sequence.extend(target_sessions)
            predecessor_manifest = checkpoint.manifest_sha256
            predecessor_session = checkpoint.boundary_session.isoformat()

        head_session = snapshot.track.current_checkpoint_session.isoformat()
        if predecessor_manifest != snapshot.track.current_checkpoint_manifest_sha256:
            raise DailyTrackEquivalenceMismatch(
                "EQUIVALENCE_MISMATCH at $.tracking_head.checkpoint"
            )
        if predecessor_session != head_session:
            raise DailyTrackEquivalenceMismatch("EQUIVALENCE_MISMATCH at $.tracking_head.session")
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

    def _claim_current(
        self,
        execution_memory_bytes: int,
    ) -> _SessionProgressionClaim | _BlockedProgressionCreated | None:
        if self._dataset_lifecycle is None or self._generation_store is None:
            return None
        current_head = self._dataset_lifecycle.current_pointer()
        if current_head is None:
            return None
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                WITH eligible AS (
                    SELECT id
                    FROM daily_tracks.session_progressions
                    WHERE status = 'running'
                      AND queue_position IS NULL
                      AND next_attempt_eligible_at <= now()
                    ORDER BY next_attempt_eligible_at, created_at, id
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE daily_tracks.session_progressions AS progression
                SET queue_position = nextval('daily_tracks.work_queue_sequence')
                FROM eligible
                WHERE progression.id = eligible.id
                """
            )
            while True:
                row = transaction.execute(
                    _TRACKING_ELIGIBILITY_SELECT
                    + """
                        ORDER BY COALESCE(
                            pending.queue_position,
                            track.queue_position
                        ), track.id
                        FOR UPDATE OF track, state SKIP LOCKED
                        LIMIT 1
                    """,
                    (current_head.data_through_session,),
                ).fetchone()
                if row is None:
                    break
                row = transaction.execute(
                    _TRACKING_ELIGIBILITY_SELECT + " AND track.id = %s",
                    (current_head.data_through_session, row["id"]),
                ).fetchone()
                if row is None:
                    continue
                admission = self._generation_store.open_admission(
                    current_head.generation_manifest_sha256
                )
                generation = admission.generation
                calendar = list(admission.research_calendar)
                current_session = row["boundary_session"].isoformat()
                try:
                    current_index = calendar.index(current_session)
                except ValueError as error:
                    raise RuntimeError("DailyTrack Checkpoint is outside current data") from error
                target_sessions = tuple(calendar[current_index + 1 :])
                if not target_sessions:
                    continue
                origin = TrackingOrigin.model_validate(row["origin"])
                dependencies = _origin_dependencies(origin)
                financial_coverage_unavailable = False
                industry_coverage_unavailable = False
                coverage_limits = tuple(
                    coverage
                    for required, coverage in (
                        (
                            dependencies.financial,
                            admission.financial_observation_through_session,
                        ),
                        (
                            dependencies.industry,
                            admission.industry_observation_through_session,
                        ),
                    )
                    if required
                )
                if coverage_limits:
                    covered_targets = tuple(
                        session
                        for session in target_sessions
                        if all(
                            coverage is not None and session <= coverage
                            for coverage in coverage_limits
                        )
                    )
                    if covered_targets:
                        target_sessions = covered_targets
                    else:
                        target_sessions = (target_sessions[0],)
                        financial_coverage_unavailable = dependencies.financial and (
                            admission.financial_observation_through_session is None
                            or target_sessions[-1] > admission.financial_observation_through_session
                        )
                        industry_coverage_unavailable = dependencies.industry and (
                            admission.industry_observation_through_session is None
                            or target_sessions[-1] > admission.industry_observation_through_session
                        )
                existing = transaction.execute(
                    """
                    SELECT id,
                           predecessor_checkpoint_manifest_sha256,
                           target_sessions,
                           current_cycle_ordinal,
                           next_attempt_eligible_at,
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
                if existing is not None:
                    if existing["predecessor_checkpoint_manifest_sha256"] != row["manifest_sha256"]:
                        raise DailyTrackFenced
                    target_sessions = tuple(
                        value.isoformat() for value in existing["target_sessions"]
                    )
                    financial_coverage_unavailable = dependencies.financial and (
                        admission.financial_observation_through_session is None
                        or target_sessions[-1] > admission.financial_observation_through_session
                    )
                    industry_coverage_unavailable = dependencies.industry and (
                        admission.industry_observation_through_session is None
                        or target_sessions[-1] > admission.industry_observation_through_session
                    )
                planning_candidates = target_sessions[:MAX_CHUNK_SESSION_COUNT]
                planning = _origin_planning_facts(origin)
                maximum_universe_cardinality = self._generation_store.maximum_universe_cardinality(
                    generation.manifest_sha256,
                    universe=origin_universe(origin),
                    start_session=planning_candidates[0],
                    end_session=planning_candidates[-1],
                )
                plan = plan_tracking_advance(
                    unpublished_sessions=tuple(
                        _session_date(value) for value in planning_candidates
                    ),
                    formula_work=planning["formula_work"],
                    node_count=planning["node_count"],
                    field_count=planning["field_count"],
                    maximum_universe_cardinality=maximum_universe_cardinality,
                    effective_lookback=planning["effective_lookback"],
                    execution_memory_bytes=execution_memory_bytes,
                )
                planned_target_sessions = tuple(value.isoformat() for value in plan.target_sessions)
                if existing is None:
                    target_sessions = planned_target_sessions
                target_fits = not plan.capacity_blocked and len(planned_target_sessions) >= len(
                    target_sessions
                )
                progression_provenance: dict[str, object] = {
                    "schema_version": "daily-track-progression-v1",
                    "target_start_session": target_sessions[0],
                    "target_end_session": target_sessions[-1],
                    "planning_data_generation_id": generation.manifest_sha256,
                    "execution_memory_bytes": execution_memory_bytes,
                    "estimated_peak_bytes": plan.estimated_peak_bytes,
                    "estimated_target_work": plan.estimated_target_work,
                    "time_target_exceeded": plan.time_target_exceeded,
                    "financial_research_readiness": _generation_financial_readiness(generation),
                }
                if existing is None:
                    progression_id = f"track_progression_{uuid4().hex[:20]}"
                    ordinal = 1
                    cycle_ordinal = 1
                    cycle_attempt_ordinal = 1
                    self._session_coordinates.start_progression(
                        transaction,
                        progression_id=progression_id,
                        track_id=str(row["id"]),
                        expected_checkpoint_manifest_sha256=str(row["manifest_sha256"]),
                        generation_sessions=tuple(_session_date(value) for value in calendar),
                        target_sessions=tuple(_session_date(value) for value in target_sessions),
                        planning_data_generation_id=generation.manifest_sha256,
                        initial_cycle_ordinal=1 if target_fits else None,
                        provenance=progression_provenance,
                    )
                else:
                    progression_id = str(existing["id"])
                    ordinal = int(existing["latest_ordinal"]) + 1
                    if existing["current_cycle_ordinal"] is None:
                        raise DailyTrackFenced
                    cycle_ordinal = int(existing["current_cycle_ordinal"])
                    cycle_attempt_ordinal = transaction.execute(
                        """
                        SELECT count(*) + 1 AS ordinal
                        FROM daily_tracks.session_progression_attempts
                        WHERE progression_id = %s AND cycle_ordinal = %s
                        """,
                        (progression_id, cycle_ordinal),
                    ).fetchone()["ordinal"]
                if not target_fits:
                    progression = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET status = 'blocked', finished_at = now(),
                            queue_position = NULL
                        WHERE id = %s AND track_id = %s AND status = 'running'
                        """,
                        (progression_id, row["id"]),
                    )
                    track = transaction.execute(
                        """
                        UPDATE daily_tracks.tracks
                        SET status = 'blocked', blocked_progression_id = %s,
                            blocked_reason = %s
                        WHERE id = %s AND status = 'active'
                          AND execution_fence = %s
                        """,
                        (
                            progression_id,
                            CAPACITY_BLOCKED_REASON,
                            row["id"],
                            row["execution_fence"],
                        ),
                    )
                    if progression.rowcount != 1 or track.rowcount != 1:
                        raise DailyTrackFenced
                    return _BlockedProgressionCreated(
                        track_id=str(row["id"]),
                        progression_id=progression_id,
                    )
                attempt_id = f"track_attempt_{uuid4().hex[:20]}"
                pinned = self._dataset_lifecycle.pin_generation_in_transaction(
                    transaction,
                    generation_manifest_sha256=generation.manifest_sha256,
                    owner_kind="tracking_advance_attempt",
                    owner_id=attempt_id,
                    lease_seconds=self._lease_seconds,
                )
                pin = pinned.pin
                fence = int(row["execution_fence"]) + 1
                self._session_coordinates.start_attempt(
                    transaction,
                    attempt_id=attempt_id,
                    progression_id=progression_id,
                    ordinal=ordinal,
                    cycle_ordinal=cycle_ordinal,
                    cycle_attempt_ordinal=int(cycle_attempt_ordinal),
                    fence=fence,
                    generation_pin_id=pin.id,
                    data_generation_id=generation.manifest_sha256,
                    data_through_session=_session_date(generation.data_through_session),
                    lease_seconds=self._lease_seconds,
                )
                updated = transaction.execute(
                    """
                    UPDATE daily_tracks.tracks
                    SET execution_fence = %s,
                        queue_position = nextval('daily_tracks.work_queue_sequence')
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
                    cycle_ordinal=cycle_ordinal,
                    cycle_attempt_ordinal=int(cycle_attempt_ordinal),
                    fence=fence,
                    generation_pin_id=pin.id,
                    data_generation_id=generation.manifest_sha256,
                    data_through_session=generation.data_through_session,
                    origin=origin,
                    predecessor_manifest_sha256=str(row["manifest_sha256"]),
                    predecessor_provenance=dict(row["provenance"]),
                    current_session=current_session,
                    target_sessions=target_sessions,
                    financial_research_readiness=_generation_financial_readiness(generation),
                    financial_coverage_unavailable=financial_coverage_unavailable,
                    industry_coverage_unavailable=industry_coverage_unavailable,
                )
        return None

    def _recover_expired_current(self) -> _TrackingFailure | None:
        if self._dataset_lifecycle is None:
            return None
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT track.id AS track_id, track.execution_fence,
                       progression.id AS progression_id,
                       attempt.id AS attempt_id, attempt.fence,
                       attempt.generation_pin_id,
                       attempt.cycle_ordinal, attempt.cycle_attempt_ordinal
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
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        with self._database.try_session_advisory_lock(
            _attempt_owner_lock(str(row["attempt_id"]))
        ) as owner_is_dead:
            if not owner_is_dead:
                return None
            with self._database.transaction() as transaction:
                current = transaction.execute(
                    """
                    SELECT track.id AS track_id, track.execution_fence,
                           progression.id AS progression_id,
                           attempt.id AS attempt_id, attempt.fence,
                           attempt.generation_pin_id,
                           attempt.cycle_ordinal, attempt.cycle_attempt_ordinal
                    FROM daily_tracks.session_progression_attempts AS attempt
                    JOIN daily_tracks.session_progressions AS progression
                      ON progression.id = attempt.progression_id
                    JOIN daily_tracks.tracks AS track ON track.id = progression.track_id
                    WHERE attempt.id = %s
                      AND track.status = 'active'
                      AND track.execution_fence = attempt.fence
                      AND progression.status = 'running'
                      AND attempt.status = 'running'
                      AND attempt.lease_expires_at <= now()
                    FOR UPDATE OF track, progression, attempt
                    """,
                    (row["attempt_id"],),
                ).fetchone()
                if current is None:
                    return None
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
                        current["attempt_id"],
                        current["progression_id"],
                        current["fence"],
                    ),
                )
                attempt_number = int(current["cycle_attempt_ordinal"])
                retry = tracking_attempt_retry_eligible(
                    WORKER_LOST_FAILURE,
                    attempt_number,
                )
                if retry:
                    retry_delay = 5 if int(current["cycle_attempt_ordinal"]) == 1 else 30
                    progression = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET next_attempt_eligible_at =
                                now() + make_interval(secs => %s),
                            queue_position = NULL
                        WHERE id = %s AND track_id = %s AND status = 'running'
                          AND current_cycle_ordinal = %s
                        """,
                        (
                            retry_delay,
                            current["progression_id"],
                            current["track_id"],
                            current["cycle_ordinal"],
                        ),
                    )
                    if attempt.rowcount != 1 or progression.rowcount != 1:
                        raise DailyTrackFenced
                else:
                    progression = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET status = 'blocked', finished_at = now(),
                            next_attempt_eligible_at = NULL,
                            queue_position = NULL
                        WHERE id = %s AND track_id = %s AND status = 'running'
                        """,
                        (current["progression_id"], current["track_id"]),
                    )
                    track = transaction.execute(
                        """
                        UPDATE daily_tracks.tracks
                        SET status = 'blocked', blocked_progression_id = %s,
                            blocked_reason = %s
                        WHERE id = %s AND status = 'active'
                          AND execution_fence = %s
                        """,
                        (
                            current["progression_id"],
                            INFRASTRUCTURE_EXHAUSTED_BLOCKED_REASON,
                            current["track_id"],
                            current["fence"],
                        ),
                    )
                    if attempt.rowcount != 1 or progression.rowcount != 1 or track.rowcount != 1:
                        raise DailyTrackFenced
                self._dataset_lifecycle.release_pin_in_transaction(
                    transaction,
                    str(current["generation_pin_id"]),
                    owner_id=str(current["attempt_id"]),
                )
            return _TrackingFailure(
                track_id=str(current["track_id"]),
                attempt_id=str(current["attempt_id"]),
                attempt_number=attempt_number,
                retry=retry,
                failure_code="WORKER_LOST",
                attempt_level="WARNING" if retry else "ERROR",
            )

    def _release_cancelled_pin(self, claim: _SessionProgressionClaim) -> bool:
        if self._dataset_lifecycle is None:
            return False
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT attempt.id, attempt.generation_pin_id
                FROM daily_tracks.session_progression_attempts AS attempt
                WHERE attempt.id = %s AND attempt.status = 'cancelled'
                FOR UPDATE OF attempt
                """,
                (claim.attempt_id,),
            ).fetchone()
            if row is None:
                return False
            return self._dataset_lifecycle.release_pin_if_active_in_transaction(
                transaction,
                str(row["generation_pin_id"]),
                owner_id=str(row["id"]),
            )

    def _recover_stopping_attempt(self) -> _StoppedTrack | None:
        if self._dataset_lifecycle is None:
            return None
        for pin in self._dataset_lifecycle.active_pins():
            if pin.owner_kind != "tracking_advance_attempt":
                continue
            attempt_id = pin.owner_id
            with self._database.try_session_advisory_lock(
                _attempt_owner_lock(attempt_id)
            ) as owner_is_dead:
                if not owner_is_dead:
                    continue
                with self._database.transaction() as transaction:
                    current = transaction.execute(
                        """
                        SELECT attempt.id, attempt.track_id, attempt.progression_id,
                               attempt.generation_pin_id
                        FROM daily_tracks.session_progression_attempts AS attempt
                        JOIN daily_tracks.session_progressions AS progression
                          ON progression.id = attempt.progression_id
                        JOIN daily_tracks.tracks AS track ON track.id = attempt.track_id
                        WHERE attempt.id = %s AND attempt.status = 'stopping'
                          AND progression.status = 'stopping'
                          AND track.status = 'stopping'
                          AND attempt.lease_expires_at <= now()
                        FOR UPDATE OF track, progression, attempt
                        """,
                        (attempt_id,),
                    ).fetchone()
                    if current is None:
                        continue
                    attempt = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progression_attempts
                        SET status = 'cancelled', heartbeat_at = now(),
                            lease_expires_at = now(), finished_at = now()
                        WHERE id = %s AND status = 'stopping'
                        """,
                        (current["id"],),
                    )
                    progression = transaction.execute(
                        """
                        UPDATE daily_tracks.session_progressions
                        SET status = 'cancelled', finished_at = now(),
                            next_attempt_eligible_at = NULL, queue_position = NULL
                        WHERE id = %s AND status = 'stopping'
                        """,
                        (current["progression_id"],),
                    )
                    track = transaction.execute(
                        """
                        UPDATE daily_tracks.tracks
                        SET status = 'stopped', blocked_progression_id = NULL,
                            blocked_reason = NULL
                        WHERE id = %s AND status = 'stopping'
                        """,
                        (current["track_id"],),
                    )
                    if attempt.rowcount != 1 or progression.rowcount != 1 or track.rowcount != 1:
                        raise DailyTrackFenced
                    self._dataset_lifecycle.release_pin_if_active_in_transaction(
                        transaction,
                        str(current["generation_pin_id"]),
                        owner_id=str(current["id"]),
                    )
                if self._working_cache is not None:
                    self._working_cache.delete(str(current["track_id"]))
                return _StoppedTrack(
                    track_id=str(current["track_id"]),
                    attempt_id=str(current["id"]),
                )
        return None

    def _stop_is_pending(self, claim: _SessionProgressionClaim) -> bool:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT track.status AS track_status,
                       progression.status AS progression_status,
                       attempt.status AS attempt_status
                FROM daily_tracks.session_progression_attempts AS attempt
                JOIN daily_tracks.session_progressions AS progression
                  ON progression.id = attempt.progression_id
                JOIN daily_tracks.tracks AS track ON track.id = attempt.track_id
                WHERE attempt.id = %s AND progression.id = %s AND track.id = %s
                """,
                (claim.attempt_id, claim.progression_id, claim.track_id),
            ).fetchone()
        return row == {
            "track_status": "stopping",
            "progression_status": "stopping",
            "attempt_status": "stopping",
        }

    def _monitor_current_stop(
        self,
        claim: _SessionProgressionClaim,
        execution: SupervisedTrackingExecution,
        finished: Event,
        emit: ExecutionEvent,
    ) -> None:
        while not finished.wait(0.05):
            if not self._stop_is_pending(claim):
                continue
            try:
                execution.cancel()
                if self._confirm_stopped(claim):
                    emit(
                        _tracking_stopped_event(
                            _StoppedTrack(
                                track_id=claim.track_id,
                                attempt_id=claim.attempt_id,
                            )
                        )
                    )
            except Exception as error:
                emit(
                    _tracking_event(
                        "daily_track_stop_confirmation_failed",
                        level="WARNING",
                        track_id=claim.track_id,
                        attempt_id=claim.attempt_id,
                        failure_code="INFRASTRUCTURE_UNAVAILABLE",
                        exception_type=type(error).__name__,
                    )
                )
            return

    def _confirm_stopped(self, claim: _SessionProgressionClaim) -> bool:
        assert self._dataset_lifecycle is not None
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT attempt.generation_pin_id
                FROM daily_tracks.session_progression_attempts AS attempt
                JOIN daily_tracks.session_progressions AS progression
                  ON progression.id = attempt.progression_id
                JOIN daily_tracks.tracks AS track ON track.id = attempt.track_id
                WHERE attempt.id = %s AND attempt.progression_id = %s
                  AND attempt.status = 'stopping'
                  AND progression.status = 'stopping'
                  AND track.id = %s AND track.status = 'stopping'
                FOR UPDATE OF track, progression, attempt
                """,
                (claim.attempt_id, claim.progression_id, claim.track_id),
            ).fetchone()
            if current is None:
                return False
            attempt = transaction.execute(
                """
                UPDATE daily_tracks.session_progression_attempts
                SET status = 'cancelled', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now()
                WHERE id = %s AND status = 'stopping'
                """,
                (claim.attempt_id,),
            )
            progression = transaction.execute(
                """
                UPDATE daily_tracks.session_progressions
                SET status = 'cancelled', finished_at = now(),
                    next_attempt_eligible_at = NULL, queue_position = NULL
                WHERE id = %s AND status = 'stopping'
                """,
                (claim.progression_id,),
            )
            track = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET status = 'stopped', blocked_progression_id = NULL,
                    blocked_reason = NULL
                WHERE id = %s AND status = 'stopping'
                """,
                (claim.track_id,),
            )
            if attempt.rowcount != 1 or progression.rowcount != 1 or track.rowcount != 1:
                raise DailyTrackFenced
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                str(current["generation_pin_id"]),
                owner_id=claim.attempt_id,
            )
        if self._working_cache is not None:
            self._working_cache.delete(claim.track_id)
        return True

    @contextmanager
    def _maintain_current_claim(
        self,
        claim: _SessionProgressionClaim,
        emit: ExecutionEvent,
    ) -> Iterator[Event]:
        stopped = Event()
        authority_lost = Event()
        heartbeat = Thread(
            target=self._heartbeat_current_claim,
            args=(claim, stopped, authority_lost, emit),
            name=f"daily-track-session-heartbeat-{claim.track_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield authority_lost
        finally:
            stopped.set()
            heartbeat.join(timeout=5)

    def _record_current_progress(
        self,
        claim: _SessionProgressionClaim,
        *,
        phase: str,
        current_session: str,
    ) -> None:
        if phase not in {"calculating", "result_ready", "staging"}:
            raise ValueError("Tracking execution phase is invalid")
        if current_session not in claim.target_sessions:
            raise ValueError("Tracking execution session is outside its Target")
        with self._database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE daily_tracks.session_progression_attempts AS attempt
                SET execution_phase = %s, current_session = %s
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
                    phase,
                    _session_date(current_session),
                    claim.attempt_id,
                    claim.progression_id,
                    claim.fence,
                    claim.track_id,
                ),
            )
            if updated.rowcount != 1:
                raise DailyTrackFenced

    def _heartbeat_current_claim(
        self,
        claim: _SessionProgressionClaim,
        stopped: Event,
        authority_lost: Event,
        emit: ExecutionEvent,
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
                authority_lost.set()
                emit(
                    _tracking_event(
                        "tracking_attempt_heartbeat_failed",
                        level="WARNING",
                        track_id=claim.track_id,
                        attempt_id=claim.attempt_id,
                        failure_code="INFRASTRUCTURE_UNAVAILABLE",
                        exception_type=type(error).__name__,
                    )
                )
                return
            if renewed.rowcount != 1:
                authority_lost.set()
                return

    def _execute_current(
        self,
        claim: _SessionProgressionClaim,
        *,
        emit: ExecutionEvent,
        authority_lost: Event,
        stop_requested: Callable[[], bool],
    ) -> SupervisedTrackingExecution:
        assert self._publication is not None
        assert self._executor is not None
        if claim.financial_coverage_unavailable:
            raise FinancialCoverageUnavailable(
                "Financial Coverage does not include the next Research Session"
            )
        if claim.industry_coverage_unavailable:
            raise IndustryCoverageUnavailable(
                "Industry Coverage does not include the next Research Session"
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
        continuation = self._load_current_working_cache(claim, predecessor)
        return self._executor.execute(
            TrackingExecutionRequest(
                track_id=claim.track_id,
                attempt_id=claim.attempt_id,
                data_generation_id=claim.data_generation_id,
                data_through_session=claim.data_through_session,
                origin=claim.origin.model_dump(mode="json"),
                predecessor=predecessor,
                predecessor_manifest_sha256=claim.predecessor_manifest_sha256,
                continuation=continuation,
                current_session=claim.current_session,
                target_sessions=claim.target_sessions,
                watchdog_grace_seconds=self._child_watchdog_grace_seconds,
            ),
            emit=emit,
            authority_lost=authority_lost,
            stop_requested=stop_requested,
        )

    def _load_current_working_cache(
        self,
        claim: _SessionProgressionClaim,
        predecessor: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        if (
            self._working_cache is None
            or predecessor.get("schema_version") != "daily-track-checkpoint-v1"
        ):
            return None
        try:
            return self._working_cache.load(
                track_id=claim.track_id,
                head_manifest_sha256=claim.predecessor_manifest_sha256,
                fence=claim.fence - 1,
                continuation_sha256=str(predecessor["continuation_sha256"]),
                pending_alpha_sessions=int(predecessor["pending_alpha_sessions"]),
                rolling_factor_rows=int(predecessor["rolling_factor_rows"]),
            )
        except (KeyError, TypeError, ValueError):
            self._working_cache.delete(claim.track_id)
            return None

    def _prepare_current_result(
        self,
        claim: _SessionProgressionClaim,
        result: TrackingExecutionResult,
    ) -> tuple[PreparedPublication, dict[str, object]]:
        assert self._publication is not None
        checkpoint = KernelStateCheckpoint.model_validate(result.checkpoint)
        if checkpoint.boundary_session != claim.target_sessions[-1]:
            raise RuntimeError("Tracking child returned an invalid Target boundary")
        provenance = {
            "schema_version": "daily-track-checkpoint-v2",
            "daily_track_id": claim.track_id,
            "predecessor_manifest_sha256": claim.predecessor_manifest_sha256,
            "boundary_session": checkpoint.boundary_session,
            "data_generation_id": claim.data_generation_id,
            "data_through_session": claim.data_through_session,
            "financial_research_readiness": claim.financial_research_readiness,
            "calculation_contracts": claim.origin.calculation_contracts,
        }
        prepared = self._publication.prepare(
            kind="daily-track.checkpoint",
            payloads={"checkpoint": JsonPayload(checkpoint.model_dump(mode="json"))},
            provenance=provenance,
        )
        return prepared, provenance

    def _publish_current(
        self,
        claim: _SessionProgressionClaim,
        prepared: PreparedPublication,
        provenance: dict[str, object],
        published_state: Mapping[str, object],
    ) -> PublishedRef:
        assert self._publication is not None
        assert self._dataset_lifecycle is not None
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
                "current_checkpoint_manifest_sha256": (claim.predecessor_manifest_sha256),
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
        result: TrackingExecutionResult,
        emit: ExecutionEvent,
    ) -> None:
        if self._working_cache is None:
            return
        try:
            stored = self._working_cache.store(
                track_id=claim.track_id,
                head_manifest_sha256=published.manifest_sha256,
                fence=claim.fence,
                verified_continuation=result.continuation,
            )
        except Exception as error:
            emit(
                _tracking_event(
                    "tracking_working_cache_update_failed",
                    level="WARNING",
                    track_id=claim.track_id,
                    attempt_id=claim.attempt_id,
                    failure_code="WORKING_CACHE_UPDATE_FAILED",
                    exception_type=type(error).__name__,
                )
            )
            return
        if not stored:
            emit(
                _tracking_event(
                    "tracking_working_cache_update_failed",
                    level="WARNING",
                    track_id=claim.track_id,
                    attempt_id=claim.attempt_id,
                    failure_code="WORKING_CACHE_UNAVAILABLE",
                )
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
        *,
        blocked_reason: str = PUBLIC_BLOCKED_REASON,
    ) -> _TrackingFailure | None:
        assert self._dataset_lifecycle is not None
        retryable = _tracking_failure_is_retryable(error)
        failure_reason = "InfrastructureFailure" if retryable else type(error).__name__
        retry_wait = tracking_attempt_retry_eligible(
            failure_reason,
            claim.cycle_attempt_ordinal,
        )
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
                return None
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
            if retry_wait:
                retry_delay = 5 if claim.cycle_attempt_ordinal == 1 else 30
                progression = transaction.execute(
                    """
                    UPDATE daily_tracks.session_progressions
                    SET next_attempt_eligible_at =
                            now() + make_interval(secs => %s),
                        queue_position = NULL
                    WHERE id = %s AND track_id = %s AND status = 'running'
                      AND current_cycle_ordinal = %s
                    """,
                    (
                        retry_delay,
                        claim.progression_id,
                        claim.track_id,
                        claim.cycle_ordinal,
                    ),
                )
                if attempt.rowcount != 1 or progression.rowcount != 1:
                    raise DailyTrackFenced
            else:
                if retryable:
                    blocked_reason = INFRASTRUCTURE_EXHAUSTED_BLOCKED_REASON
                progression = transaction.execute(
                    """
                    UPDATE daily_tracks.session_progressions
                    SET status = 'blocked', finished_at = now(),
                        next_attempt_eligible_at = NULL,
                        queue_position = NULL
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
                        blocked_reason,
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
        return _TrackingFailure(
            track_id=claim.track_id,
            attempt_id=claim.attempt_id,
            attempt_number=claim.cycle_attempt_ordinal,
            retry=retry_wait,
            failure_code=(tracking_attempt_failure_code(failure_reason) or "UNCLASSIFIED_FAILURE"),
            attempt_level=(
                "WARNING"
                if retry_wait or isinstance(error, FinancialCoverageUnavailable)
                else "ERROR"
            ),
        )


def _tracking_event(
    event: str,
    *,
    level: str = "INFO",
    **context: object,
) -> dict[str, object]:
    return {
        "event": event,
        "level": level,
        **context,
    }


def _tracking_stopped_event(stopped: _StoppedTrack) -> dict[str, object]:
    context: dict[str, object] = {
        "track_id": stopped.track_id,
        "status": "stopped",
    }
    if stopped.attempt_id is not None:
        context["attempt_id"] = stopped.attempt_id
    return _tracking_event("daily_track_stopped", **context)


def _emit_tracking_failure(
    emit: ExecutionEvent,
    failure: _TrackingFailure,
) -> None:
    emit(
        _tracking_event(
            "tracking_attempt_failed",
            level=failure.attempt_level,
            track_id=failure.track_id,
            attempt_id=failure.attempt_id,
            attempt_number=failure.attempt_number,
            status="failed",
            failure_code=failure.failure_code,
        )
    )
    if failure.retry:
        emit(
            _tracking_event(
                "tracking_retry_scheduled",
                level="WARNING",
                track_id=failure.track_id,
                attempt_id=failure.attempt_id,
                attempt_number=failure.attempt_number,
                status="active",
                failure_code=failure.failure_code,
            )
        )
        return
    emit(
        _tracking_event(
            "daily_track_blocked",
            level="WARNING",
            track_id=failure.track_id,
            attempt_id=failure.attempt_id,
            attempt_number=failure.attempt_number,
            status="blocked",
            failure_code=failure.failure_code,
        )
    )


def _tracking_failure_is_retryable(error: Exception) -> bool:
    return isinstance(
        error,
        (
            PublicationUnavailableError,
            TrackingExecutionOwnershipLost,
            OperationalError,
            PoolTimeout,
            TimeoutError,
        ),
    )


def _origin_dependencies(origin: TrackingOrigin) -> DataDependencies:
    field_bindings = origin.immutable_input.get("field_bindings")
    if not isinstance(field_bindings, Mapping):
        raise RuntimeError("DailyTrack field bindings are invalid")
    return resolve_data_dependencies(
        field_ids=set(field_bindings),
        neutralization=origin_neutralization(origin),
    )


def _origin_planning_facts(origin: TrackingOrigin) -> dict[str, int]:
    admission = origin.immutable_input.get("alpha_admission")
    field_bindings = origin.immutable_input.get("field_bindings")
    if not isinstance(admission, Mapping) or not isinstance(field_bindings, Mapping):
        raise RuntimeError("DailyTrack frozen planning input is invalid")
    try:
        facts = {
            "formula_work": int(admission["formula_work"]),
            "node_count": int(admission["node_count"]),
            "field_count": len(field_bindings),
            "effective_lookback": int(admission["effective_lookback"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("DailyTrack frozen planning input is invalid") from error
    if any(value <= 0 for key, value in facts.items() if key != "effective_lookback"):
        raise RuntimeError("DailyTrack frozen planning input is invalid")
    if facts["effective_lookback"] < 0:
        raise RuntimeError("DailyTrack frozen planning input is invalid")
    return facts


_TRACK_SELECT = """
SELECT track.id, track.status, track.origin, track.blocked_reason,
       track.created_at, state.updated_at AS state_updated_at,
       checkpoint.boundary_session::text AS current_strategy_session
FROM daily_tracks.tracks AS track
JOIN daily_tracks.session_tracking_states AS state
  ON state.track_id = track.id
JOIN daily_tracks.session_checkpoints AS checkpoint
  ON checkpoint.track_id = state.track_id
 AND checkpoint.manifest_sha256 = state.current_checkpoint_manifest_sha256
"""


def _cursor_secret(transaction: PostgresTransaction) -> bytes:
    row = transaction.execute(
        "SELECT secret FROM daily_tracks.cursor_secrets WHERE singleton = 1"
    ).fetchone()
    if row is None or not isinstance(row.get("secret"), str):
        raise RuntimeError("DailyTrack cursor secret is unavailable")
    try:
        secret = bytes.fromhex(str(row["secret"]))
    except ValueError as error:
        raise RuntimeError("DailyTrack cursor secret is invalid") from error
    if len(secret) != 32:
        raise RuntimeError("DailyTrack cursor secret is invalid")
    return secret


def _cursor_fernet(secret: bytes) -> Fernet:
    return Fernet(urlsafe_b64encode(secret))


def _encode_cursor(row: Mapping[str, object], *, secret: bytes) -> str:
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise TypeError("DailyTrack created_at must be a datetime")
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": row["id"]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _cursor_fernet(secret).encrypt(payload).decode("ascii")


def _decode_cursor(
    cursor: str | None,
    *,
    secret: bytes,
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        plaintext = _cursor_fernet(secret).decrypt(cursor.encode("ascii"))
        decoded: object = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict) or set(decoded) != {"created_at", "id"}:
            raise ValueError
        created_at = datetime.fromisoformat(str(decoded["created_at"]))
        track_id = decoded["id"]
        if created_at.tzinfo is None or not isinstance(track_id, str) or not track_id:
            raise ValueError
    except (InvalidToken, ValueError, UnicodeDecodeError, UnicodeEncodeError) as error:
        raise DailyTrackInvalidCursor("DailyTrack cursor is invalid") from error
    return created_at, track_id


def _polling_phase(
    *,
    status: str,
    unresolved: Mapping[str, object] | None,
    lag_sessions: int,
) -> str:
    if status == "stopping":
        return "stopping"
    if status == "stopped":
        return "stopped"
    if unresolved is None:
        return "up_to_date" if lag_sessions == 0 else "waiting"
    if unresolved["status"] == "blocked":
        return "blocked"
    if unresolved["attempt_status"] == "running":
        return str(unresolved["execution_phase"])
    if unresolved["retry_wait"]:
        return "retry_wait"
    return "queued"


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
        result_checksum_sha256=verified_result.result_checksum_sha256,
        origin_session=origin.initial_strategy_state.session,
        strategy_session=str(row["current_strategy_session"]),
    )


def _seed_result_provenance(origin: TrackingOrigin) -> dict[str, object]:
    semantic_versions = _mapping_value(
        origin.immutable_input.get("semantic_versions"),
        "Tracking semantic versions",
    )
    data_admission = _mapping_value(
        origin.immutable_input.get("data_admission"),
        "Tracking data admission",
    )
    financial_readiness = data_admission.get("financial_research_readiness")
    if financial_readiness not in {
        "ready",
        "ready_with_pending",
        "ready_with_gaps",
        "not_ready",
    }:
        raise RuntimeError("Tracking Financial Research Readiness is invalid")
    return {
        "schema_version": origin.verified_result.schema_version,
        "research_run_id": origin.seed_run_id,
        "research_kind": "strategy_backtest",
        "immutable_input_sha256": hashlib.sha256(
            canonical_json_bytes(origin.immutable_input)
        ).hexdigest(),
        "data_generation_id": origin.seed_data_generation_id,
        "data_through_session": origin.seed_data_through_session,
        "financial_research_readiness": financial_readiness,
        "calculation_contracts": origin.calculation_contracts,
        "semantic_versions": dict(semantic_versions),
    }


def _generation_financial_readiness(generation: object) -> FinancialResearchReadiness:
    declaration = getattr(generation, "financial_research_readiness", None)
    if declaration is None:
        return "not_ready"
    if not isinstance(declaration, Mapping):
        raise RuntimeError("Data Generation Financial Readiness is invalid")
    status = declaration.get("status")
    if status not in {"ready", "ready_with_pending", "ready_with_gaps"}:
        raise RuntimeError("Data Generation Financial Readiness is invalid")
    return status


def _collect_publication_deletions(
    publication: Publication,
    *,
    lifecycle_event: Callable[[dict[str, object]], None],
    track_id: str,
) -> None:
    try:
        while publication.collect_one_pending_deletion():
            pass
    except (PublicationPreparationError, PublicationUnavailableError):
        lifecycle_event(
            {
                "event": "tracking_publication_cleanup_deferred",
                "level": "WARNING",
                "track_id": track_id,
                "failure_code": "PUBLICATION_UNAVAILABLE",
            }
        )


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
