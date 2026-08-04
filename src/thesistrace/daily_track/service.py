from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.daily_track.cache import (
    MAX_PENDING_ALPHA_SESSIONS,
    MAX_ROLLING_FACTOR_ROWS,
    _DailyTrackWorkingCache,
)
from thesistrace.daily_track.models import (
    DailyTrackList,
    DailyTrackSummary,
    KernelStateCheckpoint,
    TrackingOrigin,
)
from thesistrace.data import NextRelease
from thesistrace.publication import (
    JsonPayload,
    PreparedPublication,
    Publication,
    PublicationNotFoundError,
    PublicationUnavailableError,
    PublicationVerificationError,
    PublishedRef,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel import (
    AdvanceInput,
    KernelRunError,
    KernelState,
    RunInput,
    advance,
    run,
)
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)

logger = logging.getLogger(__name__)

NextReleaseLookup = Callable[[PostgresTransaction, str], NextRelease | None]
CanonicalLoader = Callable[[str], dict[str, object]]
KernelAdvance = Callable[[AdvanceInput], KernelState]
Progress = Callable[[str, str, str], None]
ATTEMPT_LEASE_SECONDS = 15 * 60
ATTEMPT_HEARTBEAT_SECONDS = 30
WORKER_LOST_FAILURE = "WorkerLost"


class DailyTrackActivationConflict(RuntimeError):
    pass


class DailyTrackFenced(RuntimeError):
    pass


class DailyTrackProgressionFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class _ProgressionClaim:
    track_id: str
    attempt_id: str
    fence: int
    origin: TrackingOrigin
    current_release_id: str
    head_manifest_sha256: str | None
    head_provenance: dict[str, object] | None
    target: NextRelease


class DailyTrackService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        publication: Publication | None = None,
        next_release: NextReleaseLookup | None = None,
        load_canonical: CanonicalLoader | None = None,
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
        self._next_release = next_release
        self._load_canonical = load_canonical
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
        request_id: str,
    ) -> DailyTrackSummary:
        selected_request_id = request_id.strip()
        replay = self.resolve_activation(
            transaction,
            selected_request_id,
            origin.seed_run_id,
        )
        if replay is not None:
            return replay
        fingerprint = _activation_fingerprint(origin.seed_run_id)

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
            row = transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    id, status, seed_run_id, origin,
                    current_release_id, current_strategy_session
                ) VALUES (%s, 'active', %s, %s, %s, %s)
                RETURNING id, status, origin, current_release_id,
                          current_strategy_session
                """,
                (
                    f"track_{uuid4().hex[:20]}",
                    origin.seed_run_id,
                    Jsonb(origin.model_dump(mode="json")),
                    origin.seed_release_id,
                    origin.initial_strategy_state.session,
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

    def resolve_activation(
        self,
        transaction: PostgresTransaction,
        request_id: str,
        seed_run_id: str,
    ) -> DailyTrackSummary | None:
        selected_request_id = request_id.strip()
        if not selected_request_id:
            raise ValueError("Start Tracking request_id is required")
        fingerprint = _activation_fingerprint(seed_run_id)
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
        if receipt is None:
            return None
        if receipt["request_fingerprint"] != fingerprint:
            raise DailyTrackActivationConflict("Start Tracking request_id conflicts")
        return DailyTrackSummary.model_validate(receipt["outcome"])

    def process_next(self) -> bool:
        self._require_progression_dependencies()
        claim = self._claim_next()
        if claim is None:
            return False
        with self._maintain_claim(claim):
            self._progress("claimed", claim.track_id, claim.target.id)
            try:
                prepared, provenance, state = self._execute(claim)
                self._progress("prepared", claim.track_id, claim.target.id)
                published = self._publish_success(claim, prepared, provenance, state)
                self._store_working_cache(claim, published, state)
                self._progress("succeeded", claim.track_id, claim.target.id)
            except DailyTrackFenced:
                logger.info(
                    "DailyTrack Checkpoint rejected by execution fence",
                    extra={
                        "track_id": claim.track_id,
                        "target_release_id": claim.target.id,
                    },
                )
            except (
                KernelRunError,
                PublicationNotFoundError,
                PublicationUnavailableError,
                PublicationVerificationError,
            ) as error:
                raise DailyTrackProgressionFailed(
                    "DailyTrack progression failed at its current target"
                ) from error
        return True

    def list(self) -> DailyTrackList:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                f"""
                {_TRACK_SELECT}
                ORDER BY created_at DESC, id
                """
            ).fetchall()
        return DailyTrackList(items=[_summary(row) for row in rows], next_cursor=None)

    def get(self, track_id: str) -> DailyTrackSummary | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                f"""
                {_TRACK_SELECT}
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
        return None if row is None else _summary(row)

    def _claim_next(self) -> _ProgressionClaim | None:
        assert self._next_release is not None
        with self._database.transaction() as transaction:
            tracks = transaction.execute(
                """
                SELECT track.id, track.status, track.origin,
                       track.current_release_id, track.current_strategy_session,
                       track.head_manifest_sha256, track.execution_fence,
                    (SELECT provenance
                     FROM daily_tracks.checkpoints AS checkpoint
                     WHERE checkpoint.manifest_sha256 = track.head_manifest_sha256
                    ) AS head_provenance
                FROM daily_tracks.tracks AS track
                WHERE status = 'active'
                ORDER BY created_at, id
                FOR UPDATE OF track SKIP LOCKED
                """
            ).fetchall()
            for row in tracks:
                current_release_id = str(row["current_release_id"])
                target = self._next_release(transaction, current_release_id)
                if target is None:
                    continue
                if target.predecessor_id != current_release_id:
                    raise RuntimeError("Data returned a non-direct Dataset Release successor")
                progression = transaction.execute(
                    """
                    SELECT status, fence
                    FROM daily_tracks.progressions
                    WHERE track_id = %s AND target_release_id = %s
                    FOR UPDATE
                    """,
                    (row["id"], target.id),
                ).fetchone()
                latest_attempt = transaction.execute(
                    """
                    SELECT id, ordinal, status, lease_expires_at <= now() AS expired
                    FROM daily_tracks.progression_attempts
                    WHERE track_id = %s AND target_release_id = %s
                    ORDER BY ordinal DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (row["id"], target.id),
                ).fetchone()
                if progression is not None:
                    if progression["status"] == "succeeded":
                        raise RuntimeError("succeeded DailyTrack progression did not move its Head")
                    if latest_attempt is None:
                        raise RuntimeError("DailyTrack progression Attempt is missing")
                    if latest_attempt["status"] == "running" and not latest_attempt["expired"]:
                        continue
                    if latest_attempt["status"] == "running":
                        failed = transaction.execute(
                            """
                            UPDATE daily_tracks.progression_attempts
                            SET status = 'failed', heartbeat_at = now(),
                                lease_expires_at = now(), finished_at = now(),
                                failure_reason = %s
                            WHERE id = %s AND track_id = %s
                              AND target_release_id = %s AND status = 'running'
                              AND lease_expires_at <= now()
                            """,
                            (
                                WORKER_LOST_FAILURE,
                                latest_attempt["id"],
                                row["id"],
                                target.id,
                            ),
                        )
                        if failed.rowcount != 1:
                            continue
                fence = int(row["execution_fence"]) + 1
                if progression is None:
                    transaction.execute(
                        """
                        INSERT INTO daily_tracks.progressions (
                            track_id, target_release_id, predecessor_release_id,
                            fence, status
                        ) VALUES (%s, %s, %s, %s, 'running')
                        """,
                        (row["id"], target.id, target.predecessor_id, fence),
                    )
                    ordinal = 1
                else:
                    if int(progression["fence"]) != int(row["execution_fence"]):
                        raise RuntimeError("DailyTrack progression fence is inconsistent")
                    transaction.execute(
                        """
                        UPDATE daily_tracks.progressions
                        SET fence = %s
                        WHERE track_id = %s AND target_release_id = %s
                          AND status = 'running' AND fence = %s
                        """,
                        (fence, row["id"], target.id, progression["fence"]),
                    )
                    assert latest_attempt is not None
                    ordinal = int(latest_attempt["ordinal"]) + 1
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
                attempt_id = f"track_attempt_{uuid4().hex[:20]}"
                transaction.execute(
                    """
                    INSERT INTO daily_tracks.progression_attempts (
                        id, track_id, target_release_id, ordinal, fence,
                        status, lease_expires_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'running',
                        now() + make_interval(secs => %s)
                    )
                    """,
                    (
                        attempt_id,
                        row["id"],
                        target.id,
                        ordinal,
                        fence,
                        self._lease_seconds,
                    ),
                )
                head_provenance = row["head_provenance"]
                return _ProgressionClaim(
                    track_id=str(row["id"]),
                    attempt_id=attempt_id,
                    fence=fence,
                    origin=TrackingOrigin.model_validate(row["origin"]),
                    current_release_id=current_release_id,
                    head_manifest_sha256=(
                        None
                        if row["head_manifest_sha256"] is None
                        else str(row["head_manifest_sha256"])
                    ),
                    head_provenance=(None if head_provenance is None else dict(head_provenance)),
                    target=target,
                )
        return None

    @contextmanager
    def _maintain_claim(self, claim: _ProgressionClaim) -> Iterator[None]:
        stopped = Event()
        heartbeat = Thread(
            target=self._heartbeat_claim,
            args=(claim, stopped),
            name=f"daily-track-heartbeat-{claim.track_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat.join(timeout=5)

    def _heartbeat_claim(self, claim: _ProgressionClaim, stopped: Event) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    renewed = transaction.execute(
                        """
                        UPDATE daily_tracks.progression_attempts AS attempt
                        SET heartbeat_at = now(),
                            lease_expires_at = now() + make_interval(secs => %s)
                        WHERE attempt.id = %s AND attempt.track_id = %s
                          AND attempt.target_release_id = %s
                          AND attempt.fence = %s AND attempt.status = 'running'
                          AND EXISTS (
                              SELECT 1
                              FROM daily_tracks.tracks AS track
                              JOIN daily_tracks.progressions AS progression
                                ON progression.track_id = track.id
                               AND progression.target_release_id = %s
                              WHERE track.id = attempt.track_id
                                AND track.status = 'active'
                                AND track.execution_fence = attempt.fence
                                AND progression.status = 'running'
                                AND progression.fence = attempt.fence
                          )
                        """,
                        (
                            self._lease_seconds,
                            claim.attempt_id,
                            claim.track_id,
                            claim.target.id,
                            claim.fence,
                            claim.target.id,
                        ),
                    )
            except Exception as error:
                logger.error(
                    "DailyTrack claim heartbeat failed",
                    extra={
                        "track_id": claim.track_id,
                        "target_release_id": claim.target.id,
                        "error_type": type(error).__name__,
                    },
                )
                return
            if renewed.rowcount != 1:
                return

    def _execute(
        self,
        claim: _ProgressionClaim,
    ) -> tuple[PreparedPublication, dict[str, object], KernelState]:
        assert self._publication is not None
        assert self._load_canonical is not None
        prior = self._load_prior_state(claim)
        target_canonical = self._load_canonical(claim.target.id)
        target_sessions = canonical_sessions(target_canonical, "Dataset Release")
        appended_sessions = [
            session
            for session in target_sessions
            if claim.target.appended_session_start <= session <= claim.target.appended_session_end
        ]
        if not appended_sessions:
            raise RuntimeError("Dataset Release successor has no appended sessions")
        appended = slice_canonical_sessions(target_canonical, appended_sessions)
        state = self._advance_kernel(
            AdvanceInput(prior_state=prior, new_canonical_sessions=appended)
        )
        if state.boundary_session != appended_sessions[
            -1
        ] or state.session_count != prior.session_count + len(appended_sessions):
            raise RuntimeError("Kernel Advance returned an inconsistent target boundary")
        predecessor: dict[str, object]
        if claim.head_manifest_sha256 is None:
            predecessor = {
                "kind": "tracking.origin",
                "seed_release_id": claim.origin.seed_release_id,
                "seed_result_checksum_sha256": (
                    claim.origin.verified_result.result_checksum_sha256
                ),
            }
        else:
            predecessor = {
                "kind": "daily-track.checkpoint",
                "manifest_sha256": claim.head_manifest_sha256,
                "release_id": claim.current_release_id,
            }
        provenance = {
            "schema_version": "daily-track-checkpoint-v1",
            "daily_track_id": claim.track_id,
            "tracking_origin_sha256": hashlib.sha256(
                canonical_json_bytes(claim.origin.model_dump(mode="json"))
            ).hexdigest(),
            "predecessor": predecessor,
            "target_release_id": claim.target.id,
            "target_predecessor_id": claim.target.predecessor_id,
            "calculation_contracts": claim.origin.calculation_contracts,
        }
        prepared = self._publication.prepare(
            kind="daily-track.checkpoint",
            payloads={"checkpoint": JsonPayload(_state_payload(state))},
            provenance=provenance,
        )
        return prepared, provenance, state

    def _load_prior_state(self, claim: _ProgressionClaim) -> KernelState:
        assert self._publication is not None
        assert self._load_canonical is not None
        if claim.head_manifest_sha256 is None:
            seed = self._load_canonical(claim.origin.seed_release_id)
            sessions = canonical_sessions(seed, "Seed Dataset Release")
            if len(sessions) < 756:
                raise RuntimeError("Seed Dataset Release has fewer than 756 sessions")
            canonical = slice_canonical_sessions(seed, sessions[-756:])
            state = run(_kernel_input(claim.origin, canonical)).track_state
            if state.boundary_session != claim.origin.initial_strategy_state.session:
                raise RuntimeError("Tracking Origin Strategy boundary is inconsistent")
            return state
        if claim.head_provenance is None:
            raise RuntimeError("DailyTrack Head provenance is missing")
        bundle = self._publication.read(
            PublishedRef(
                manifest_sha256=claim.head_manifest_sha256,
                kind="daily-track.checkpoint",
                provenance=claim.head_provenance,
            )
        )
        payload = bundle.payloads.get("checkpoint")
        if payload is None or payload.media_type != "application/json":
            raise RuntimeError("DailyTrack Checkpoint payload is missing")
        value = json.loads(payload.content)
        if not isinstance(value, Mapping):
            raise RuntimeError("DailyTrack Checkpoint payload is invalid")
        if self._working_cache is None:
            return _state_from_payload(value)
        verified_continuation = _working_continuation(value)
        cached = self._working_cache.load(
            track_id=claim.track_id,
            release_id=claim.current_release_id,
            head_manifest_sha256=claim.head_manifest_sha256,
            fence=claim.fence - 1,
            verified_continuation=verified_continuation,
        )
        if cached is not None:
            return _state_from_payload(_with_working_continuation(value, cached))
        self._working_cache.store(
            track_id=claim.track_id,
            release_id=claim.current_release_id,
            head_manifest_sha256=claim.head_manifest_sha256,
            fence=claim.fence - 1,
            verified_continuation=verified_continuation,
        )
        return _state_from_payload(value)

    def _publish_success(
        self,
        claim: _ProgressionClaim,
        prepared: PreparedPublication,
        provenance: dict[str, object],
        state: KernelState,
    ) -> PublishedRef:
        assert self._publication is not None
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT status, current_release_id, head_manifest_sha256,
                       execution_fence
                FROM daily_tracks.tracks
                WHERE id = %s
                FOR UPDATE
                """,
                (claim.track_id,),
            ).fetchone()
            if current != {
                "status": "active",
                "current_release_id": claim.current_release_id,
                "head_manifest_sha256": claim.head_manifest_sha256,
                "execution_fence": claim.fence,
            }:
                raise DailyTrackFenced
            progression = transaction.execute(
                """
                SELECT status, fence, predecessor_release_id
                FROM daily_tracks.progressions
                WHERE track_id = %s AND target_release_id = %s
                FOR UPDATE
                """,
                (claim.track_id, claim.target.id),
            ).fetchone()
            if progression != {
                "status": "running",
                "fence": claim.fence,
                "predecessor_release_id": claim.current_release_id,
            }:
                raise DailyTrackFenced
            attempt = transaction.execute(
                """
                SELECT status, fence
                FROM daily_tracks.progression_attempts
                WHERE id = %s AND track_id = %s AND target_release_id = %s
                FOR UPDATE
                """,
                (claim.attempt_id, claim.track_id, claim.target.id),
            ).fetchone()
            if attempt != {"status": "running", "fence": claim.fence}:
                raise DailyTrackFenced
            published = self._publication.record(transaction, prepared)
            transaction.execute(
                """
                INSERT INTO daily_tracks.checkpoints (
                    track_id, target_release_id, predecessor_release_id,
                    manifest_sha256, provenance, strategy_session
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    claim.track_id,
                    claim.target.id,
                    claim.current_release_id,
                    published.manifest_sha256,
                    Jsonb(provenance),
                    state.boundary_session,
                ),
            )
            moved = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET current_release_id = %s,
                    current_strategy_session = %s,
                    head_manifest_sha256 = %s
                WHERE id = %s AND current_release_id = %s
                  AND execution_fence = %s
                """,
                (
                    claim.target.id,
                    state.boundary_session,
                    published.manifest_sha256,
                    claim.track_id,
                    claim.current_release_id,
                    claim.fence,
                ),
            )
            if moved.rowcount != 1:
                raise DailyTrackFenced
            completed = transaction.execute(
                """
                UPDATE daily_tracks.progressions
                SET status = 'succeeded', manifest_sha256 = %s,
                    provenance = %s, finished_at = now()
                WHERE track_id = %s AND target_release_id = %s
                  AND status = 'running' AND fence = %s
                """,
                (
                    published.manifest_sha256,
                    Jsonb(provenance),
                    claim.track_id,
                    claim.target.id,
                    claim.fence,
                ),
            )
            if completed.rowcount != 1:
                raise DailyTrackFenced
            completed_attempt = transaction.execute(
                """
                UPDATE daily_tracks.progression_attempts
                SET status = 'succeeded', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now()
                WHERE id = %s AND track_id = %s AND target_release_id = %s
                  AND status = 'running' AND fence = %s
                """,
                (
                    claim.attempt_id,
                    claim.track_id,
                    claim.target.id,
                    claim.fence,
                ),
            )
            if completed_attempt.rowcount != 1:
                raise DailyTrackFenced
        return published

    def _store_working_cache(
        self,
        claim: _ProgressionClaim,
        published: PublishedRef,
        state: KernelState,
    ) -> None:
        if self._working_cache is None:
            return
        try:
            stored = self._working_cache.store(
                track_id=claim.track_id,
                release_id=claim.target.id,
                head_manifest_sha256=published.manifest_sha256,
                fence=claim.fence,
                verified_continuation=_working_continuation(_state_payload(state)),
            )
        except Exception:
            logger.warning(
                "DailyTrack Working Cache update failed",
                extra={
                    "track_id": claim.track_id,
                    "target_release_id": claim.target.id,
                },
                exc_info=True,
            )
            return
        if not stored:
            logger.info(
                "DailyTrack Working Cache entry exceeded its bound or was unavailable",
                extra={
                    "track_id": claim.track_id,
                    "target_release_id": claim.target.id,
                },
            )

    def _require_progression_dependencies(self) -> None:
        if self._publication is None or self._next_release is None or self._load_canonical is None:
            raise RuntimeError("DailyTrack progression dependencies are not configured")


_TRACK_SELECT = """
SELECT track.id, track.status, track.origin, track.current_release_id,
       track.current_strategy_session
FROM daily_tracks.tracks AS track
"""


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
        current_release_id=str(row["current_release_id"]),
        definition_id=origin.definition_id,
        definition_revision=origin.definition_revision,
        result_checksum_sha256=verified_result.result_checksum_sha256,
        strategy_session=str(row["current_strategy_session"]),
    )


def _kernel_input(origin: TrackingOrigin, canonical: dict[str, object]) -> RunInput:
    immutable_input = origin.immutable_input
    definition = immutable_input.get("definition")
    if not isinstance(definition, Mapping):
        raise RuntimeError("Tracking Origin Definition is invalid")
    content = definition.get("content")
    if not isinstance(content, Mapping):
        raise RuntimeError("Tracking Origin Definition content is invalid")
    alpha = content.get("alpha")
    strategy = immutable_input.get("strategy")
    costs = immutable_input.get("costs")
    field_bindings = immutable_input.get("field_bindings")
    if not all(isinstance(value, Mapping) for value in (alpha, strategy, costs, field_bindings)):
        raise RuntimeError("Tracking Origin calculation input is invalid")
    return RunInput(
        canonical_data=canonical,
        alpha_expression=dict(alpha),
        field_bindings={str(key): str(value) for key, value in field_bindings.items()},
        universe=str(content["universe"]),
        neutralization=str(content["neutralization"]),
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_every_sessions"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
    )


def _state_payload(state: KernelState) -> dict[str, object]:
    run_input = state.run_input_with_canonical(state.canonical_snapshot())
    return KernelStateCheckpoint(
        schema_version="daily-track-kernel-state-v1",
        origin_session=state.origin_session,
        canonical=state.canonical_snapshot(),
        output=state.output_snapshot(),
        strategy_resume=state.strategy_resume_snapshot(),
        run_input={
            "alpha_expression": run_input.alpha_expression_snapshot(),
            "field_bindings": run_input.field_bindings_snapshot(),
            "universe": run_input.universe,
            "neutralization": run_input.neutralization,
            "holdings_count": run_input.holdings_count,
            "rebalance_interval": run_input.rebalance_interval,
            "initial_cash_cny": run_input.initial_cash_cny,
            "commission_rate_all_in": run_input.commission_rate_all_in,
            "commission_min_cny": run_input.commission_min_cny,
            "stamp_duty_sell_rate": run_input.stamp_duty_sell_rate,
            "transfer_fee_rate": run_input.transfer_fee_rate,
        },
    ).model_dump(mode="json")


def _state_from_payload(value: Mapping[str, object]) -> KernelState:
    checkpoint = KernelStateCheckpoint.model_validate(value)
    contract = checkpoint.run_input
    run_input = RunInput(
        canonical_data=checkpoint.canonical,
        alpha_expression=contract.alpha_expression,
        field_bindings=contract.field_bindings,
        universe=contract.universe,
        neutralization=contract.neutralization,
        holdings_count=contract.holdings_count,
        rebalance_interval=contract.rebalance_interval,
        initial_cash_cny=contract.initial_cash_cny,
        commission_rate_all_in=contract.commission_rate_all_in,
        commission_min_cny=contract.commission_min_cny,
        stamp_duty_sell_rate=contract.stamp_duty_sell_rate,
        transfer_fee_rate=contract.transfer_fee_rate,
    )
    return KernelState(
        run_input=run_input,
        output=checkpoint.output,
        strategy_resume=checkpoint.strategy_resume,
        origin_session=checkpoint.origin_session,
    )


def _working_continuation(value: Mapping[str, object]) -> dict[str, object]:
    checkpoint = KernelStateCheckpoint.model_validate(value)
    alpha = checkpoint.output.get("alpha_matrix")
    factor = checkpoint.output.get("factor_evaluation")
    if not isinstance(alpha, Mapping) or not isinstance(factor, Mapping):
        raise RuntimeError("DailyTrack continuation output is missing")
    alpha_sessions = alpha.get("sessions")
    horizons = factor.get("horizons")
    if not isinstance(alpha_sessions, list) or not isinstance(horizons, Mapping):
        raise RuntimeError("DailyTrack continuation output is invalid")
    selected_alpha = alpha_sessions[-MAX_PENDING_ALPHA_SESSIONS:]
    if any(not isinstance(item, Mapping) for item in selected_alpha):
        raise RuntimeError("DailyTrack Pending Alpha continuation is invalid")
    pending_alpha = [dict(item) for item in selected_alpha if isinstance(item, Mapping)]
    rolling_factor: list[dict[str, object]] = []
    for horizon in sorted(horizons, key=int):
        horizon_value = horizons[horizon]
        if not isinstance(horizon_value, Mapping):
            raise RuntimeError("DailyTrack Factor continuation is invalid")
        daily = horizon_value.get("daily")
        if not isinstance(daily, list):
            raise RuntimeError("DailyTrack Factor continuation is invalid")
        selected_daily = daily[-(MAX_ROLLING_FACTOR_ROWS // 3) :]
        if any(not isinstance(item, Mapping) for item in selected_daily):
            raise RuntimeError("DailyTrack Factor continuation is invalid")
        rolling_factor.extend(
            {"horizon": int(horizon), **dict(item)}
            for item in selected_daily
            if isinstance(item, Mapping)
        )
    return {
        "schema_version": "daily-track-working-state-v1",
        "pending_alpha": pending_alpha,
        "rolling_factor": rolling_factor,
    }


def _with_working_continuation(
    value: Mapping[str, object],
    continuation: Mapping[str, object],
) -> dict[str, object]:
    restored = json.loads(canonical_json_bytes(value))
    KernelStateCheckpoint.model_validate(restored)
    expected = _working_continuation(restored)
    if continuation != expected:
        raise RuntimeError("DailyTrack Working Cache does not match verified continuation")
    pending = continuation["pending_alpha"]
    rolling = continuation["rolling_factor"]
    assert isinstance(pending, list) and isinstance(rolling, list)
    output = restored["output"]
    assert isinstance(output, dict)
    alpha = output["alpha_matrix"]
    factor = output["factor_evaluation"]
    assert isinstance(alpha, dict) and isinstance(factor, dict)
    alpha_sessions = alpha["sessions"]
    horizons = factor["horizons"]
    assert isinstance(alpha_sessions, list) and isinstance(horizons, dict)
    if pending:
        alpha_sessions[-len(pending) :] = pending
    by_horizon: dict[int, list[dict[str, object]]] = {}
    for row in rolling:
        assert isinstance(row, dict)
        horizon = int(row["horizon"])
        by_horizon.setdefault(horizon, []).append(
            {key: item for key, item in row.items() if key != "horizon"}
        )
    for horizon, rows in by_horizon.items():
        daily = horizons[str(horizon)]["daily"]
        assert isinstance(daily, list)
        if rows:
            daily[-len(rows) :] = rows
    return restored
