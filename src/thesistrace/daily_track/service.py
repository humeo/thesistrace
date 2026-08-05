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
from thesistrace.daily_track.cache import _DailyTrackWorkingCache
from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
)
from thesistrace.daily_track.models import (
    DailyTrackDetail,
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
    advance_continuation,
    continuation_snapshot,
    empty_continuation,
    equivalence_bytes,
    first_divergence,
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
MAX_AUTOMATIC_PROGRESSION_ATTEMPTS = 3
PUBLIC_BLOCKED_REASON = "DailyTrack could not process this Dataset Release."
# 504 rolling signal sessions plus the 21-session maximum label maturity tail.
# The query reads one extra predecessor Checkpoint; _select_rebuild_steps then
# trims the selected Release suffix to this many actual Research Sessions.
REBUILD_CHECKPOINT_LIMIT = 525


class DailyTrackActivationConflict(RuntimeError):
    pass


class DailyTrackFenced(RuntimeError):
    pass


class DailyTrackProgressionFailed(RuntimeError):
    pass


class DailyTrackEquivalenceMismatch(RuntimeError):
    pass


class DailyTrackDetailUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyTrackEquivalenceEvidence:
    status: str
    track_id: str
    head_release_id: str
    release_sequence: tuple[str, ...]
    checkpoint_count: int
    checkpoint_evidence_sha256s: tuple[str, ...]
    final_evidence_sha256: str


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
                self._record_progression_failure(claim, error)
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

    def get(self, track_id: str) -> DailyTrackDetail | None:
        if self._publication is None or self._next_release is None:
            raise RuntimeError("DailyTrack detail dependencies are not configured")
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, status, origin, current_release_id,
                       current_strategy_session, head_manifest_sha256,
                       blocked_reason
                FROM daily_tracks.tracks
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
            if row is None:
                return None
            lag_releases = self._release_lag(
                transaction,
                current_release_id=str(row["current_release_id"]),
            )
            checkpoint_rows = _recent_checkpoint_rows(
                transaction,
                track_id=track_id,
                head_manifest_sha256=row["head_manifest_sha256"],
            )
            if row["head_manifest_sha256"] is not None and not checkpoint_rows:
                raise DailyTrackDetailUnavailable("DailyTrack detail is unavailable")
        try:
            return self._detail_projection(
                row,
                lag_releases=lag_releases,
                checkpoint_rows=checkpoint_rows,
            )
        except Exception as error:
            logger.error(
                "DailyTrack detail read failed",
                extra={"track_id": track_id, "error_type": type(error).__name__},
            )
            raise DailyTrackDetailUnavailable("DailyTrack detail is unavailable") from error

    def _release_lag(
        self,
        transaction: PostgresTransaction,
        *,
        current_release_id: str,
    ) -> int:
        assert self._next_release is not None
        lag = 0
        cursor = current_release_id
        visited = {cursor}
        while (successor := self._next_release(transaction, cursor)) is not None:
            if successor.predecessor_id != cursor or successor.id in visited:
                raise RuntimeError("Dataset Release successor chain is invalid")
            visited.add(successor.id)
            cursor = successor.id
            lag += 1
        return lag

    def _detail_projection(
        self,
        row: dict[str, object],
        *,
        lag_releases: int,
        checkpoint_rows: list[dict[str, object]],
    ) -> DailyTrackDetail:
        assert self._publication is not None
        origin = TrackingOrigin.model_validate(row["origin"])
        seed_result = _read_publication_json(
            self._publication,
            PublishedRef(
                manifest_sha256=origin.verified_result.result_manifest_sha256,
                kind=origin.verified_result.kind,
                provenance=_seed_result_provenance(origin),
            ),
            payload_name="result",
        )
        seed_factor = _mapping_value(seed_result.get("factor_summary"), "Factor Summary")
        seed_strategy_summary = _mapping_value(
            seed_result.get("strategy_summary"),
            "Strategy Summary",
        )
        seed_observations = _mapping_rows(
            seed_result.get("strategy_daily_observations"),
            "Strategy observations",
        )
        seed_benchmark = _mapping_value(
            seed_strategy_summary.get("benchmark"),
            "Strategy Benchmark",
        )
        universe = _origin_universe(origin)
        if seed_benchmark != {
            "universe": universe,
            "methodology": "selected_universe_equal_weight",
        }:
            raise RuntimeError("Tracking Origin Benchmark is invalid")

        recent_by_session: dict[str, dict[str, object]] = {}
        head_checkpoint: Mapping[str, object] | None = None
        for checkpoint_row in checkpoint_rows:
            checkpoint = _read_publication_json(
                self._publication,
                PublishedRef(
                    manifest_sha256=str(checkpoint_row["manifest_sha256"]),
                    kind="daily-track.checkpoint",
                    provenance=dict(
                        _mapping_value(
                            checkpoint_row["provenance"],
                            "Checkpoint provenance",
                        )
                    ),
                ),
                payload_name="checkpoint",
            )
            if head_checkpoint is None:
                head_checkpoint = checkpoint
            strategy_state = _mapping_value(
                checkpoint.get("strategy_state"),
                "Checkpoint Strategy state",
            )
            retained = _mapping_rows(
                strategy_state.get("retained_delta"),
                "Checkpoint Strategy observations",
            )
            for observation in reversed(retained):
                session = str(observation.get("session", ""))
                if not session:
                    raise RuntimeError("Strategy observation session is invalid")
                recent_by_session.setdefault(session, dict(observation))
                if len(recent_by_session) >= 504:
                    break
            if len(recent_by_session) >= 504:
                break
        if len(recent_by_session) < 504:
            if (
                checkpoint_rows
                and str(checkpoint_rows[-1]["predecessor_release_id"])
                != origin.seed_release_id
            ):
                raise RuntimeError("DailyTrack Checkpoint chain is incomplete")
            for observation in reversed(seed_observations):
                session = str(observation.get("session", ""))
                if not session:
                    raise RuntimeError("Seed Strategy observation session is invalid")
                recent_by_session.setdefault(session, dict(observation))
                if len(recent_by_session) >= 504:
                    break
        observations = [recent_by_session[session] for session in sorted(recent_by_session)]

        if head_checkpoint is None:
            factor = _public_factor(seed_factor)
            strategy_summary = {
                name: value
                for name, value in seed_strategy_summary.items()
                if name != "benchmark"
            }
        else:
            factor = _public_factor(
                _mapping_value(head_checkpoint.get("factor_summary"), "Factor Summary")
            )
            strategy_state = _mapping_value(
                head_checkpoint.get("strategy_state"),
                "Checkpoint Strategy state",
            )
            strategy_summary = {
                "metrics": dict(
                    _mapping_value(strategy_state.get("summary"), "Strategy summary")
                )
            }
        return DailyTrackDetail.model_validate(
            {
                "id": str(row["id"]),
                "status": row["status"],
                "origin": {
                    "seed_run_id": origin.seed_run_id,
                    "seed_release_id": origin.seed_release_id,
                    "definition_id": origin.definition_id,
                    "definition_revision": origin.definition_revision,
                    "result_checksum_sha256": (
                        origin.verified_result.result_checksum_sha256
                    ),
                    "strategy_session": origin.initial_strategy_state.session,
                },
                "head_release_id": str(row["current_release_id"]),
                "strategy_session": str(row["current_strategy_session"]),
                "lag_releases": lag_releases,
                "blocked_reason": row["blocked_reason"],
                "factor": factor,
                "strategy": {
                    "summary": strategy_summary,
                    "benchmark": {
                        "universe": universe,
                        "methodology": "selected_universe_equal_weight",
                    },
                    "observations": observations,
                },
            }
        )

    def verify_persisted_equivalence(
        self,
        track_id: str,
    ) -> DailyTrackEquivalenceEvidence:
        """Replay one immutable Checkpoint chain without changing durable state."""
        if self._publication is None or self._load_canonical is None:
            raise RuntimeError("DailyTrack equivalence dependencies are not configured")
        with self._database.transaction() as transaction:
            track = transaction.execute(
                """
                SELECT id, origin, current_release_id, current_strategy_session,
                       head_manifest_sha256
                FROM daily_tracks.tracks
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
            rows = transaction.execute(
                """
                SELECT target_release_id, predecessor_release_id,
                       manifest_sha256, provenance, strategy_session
                FROM daily_tracks.checkpoints
                WHERE track_id = %s
                """,
                (track_id,),
            ).fetchall()
        if track is None:
            raise KeyError(track_id)
        origin = TrackingOrigin.model_validate(track["origin"])
        head_release_id = str(track["current_release_id"])
        chain = _ordered_checkpoint_chain(
            rows,
            seed_release_id=origin.seed_release_id,
            head_release_id=head_release_id,
        )
        expected_head_manifest = None if not chain else str(chain[-1]["manifest_sha256"])
        _assert_equivalent(
            track["head_manifest_sha256"],
            expected_head_manifest,
            "$.tracking_head.manifest_sha256",
        )

        seed = self._load_canonical(origin.seed_release_id)
        seed_sessions = canonical_sessions(seed, "Seed Dataset Release")
        if len(seed_sessions) < 756:
            raise RuntimeError("Seed Dataset Release has fewer than 756 sessions")
        state = run(
            _kernel_input(
                origin,
                slice_canonical_sessions(seed, seed_sessions[-756:]),
            )
        ).track_state
        _assert_equivalent(
            state.boundary_session,
            origin.initial_strategy_state.session,
            "$.tracking_origin.strategy_session",
        )

        origin_sha256 = hashlib.sha256(
            canonical_json_bytes(origin.model_dump(mode="json"))
        ).hexdigest()
        release_sequence = [origin.seed_release_id]
        evidence_sha256s: list[str] = []
        predecessor_manifest: str | None = None
        for row in chain:
            target_release_id = str(row["target_release_id"])
            target = self._load_canonical(target_release_id)
            prior_sessions = canonical_sessions(state.canonical_snapshot(), "Reference state")
            target_sessions = canonical_sessions(target, "Dataset Release")
            if target_sessions[: len(prior_sessions)] != prior_sessions:
                raise DailyTrackEquivalenceMismatch(
                    f"EQUIVALENCE_MISMATCH at $.checkpoints.{target_release_id}.research_calendar"
                )
            appended_sessions = target_sessions[len(prior_sessions) :]
            if not appended_sessions:
                raise DailyTrackEquivalenceMismatch(
                    f"EQUIVALENCE_MISMATCH at $.checkpoints.{target_release_id}.appended_sessions"
                )
            prior_boundary = state.boundary_session
            state = self._advance_kernel(
                AdvanceInput(
                    prior_state=state,
                    target_canonical_release=target,
                    appended_sessions=appended_sessions,
                    continuation=continuation_snapshot(state),
                )
            )
            expected_provenance = {
                "schema_version": "daily-track-checkpoint-v1",
                "daily_track_id": track_id,
                "tracking_origin_sha256": origin_sha256,
                "predecessor": (
                    {
                        "kind": "tracking.origin",
                        "seed_release_id": origin.seed_release_id,
                        "seed_result_checksum_sha256": (
                            origin.verified_result.result_checksum_sha256
                        ),
                    }
                    if predecessor_manifest is None
                    else {
                        "kind": "daily-track.checkpoint",
                        "manifest_sha256": predecessor_manifest,
                        "release_id": str(row["predecessor_release_id"]),
                    }
                ),
                "target_release_id": target_release_id,
                "target_predecessor_id": str(row["predecessor_release_id"]),
                "calculation_contracts": origin.calculation_contracts,
            }
            coordinate = f"$.checkpoints.{target_release_id}"
            _assert_equivalent(row["provenance"], expected_provenance, f"{coordinate}.provenance")
            bundle = self._publication.read(
                PublishedRef(
                    manifest_sha256=str(row["manifest_sha256"]),
                    kind="daily-track.checkpoint",
                    provenance=dict(row["provenance"]),
                )
            )
            payload = bundle.payloads.get("checkpoint")
            if payload is None or payload.media_type != "application/json":
                raise DailyTrackEquivalenceMismatch(f"EQUIVALENCE_MISMATCH at {coordinate}.payload")
            actual = json.loads(payload.content)
            expected = _state_payload(
                state,
                retained_strategy_sessions=[prior_boundary, *appended_sessions],
            )
            _assert_equivalent(actual, expected, f"{coordinate}.state")
            _assert_equivalent(
                row["strategy_session"],
                state.boundary_session,
                f"{coordinate}.strategy_session",
            )
            evidence_sha256s.append(hashlib.sha256(equivalence_bytes(expected)).hexdigest())
            release_sequence.append(target_release_id)
            predecessor_manifest = str(row["manifest_sha256"])

        _assert_equivalent(
            track["current_strategy_session"],
            state.boundary_session,
            "$.tracking_head.strategy_session",
        )
        final_evidence = (
            evidence_sha256s[-1]
            if evidence_sha256s
            else hashlib.sha256(equivalence_bytes(state.output_snapshot())).hexdigest()
        )
        return DailyTrackEquivalenceEvidence(
            status="equivalent",
            track_id=track_id,
            head_release_id=head_release_id,
            release_sequence=tuple(release_sequence),
            checkpoint_count=len(chain),
            checkpoint_evidence_sha256s=tuple(evidence_sha256s),
            final_evidence_sha256=final_evidence,
        )

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
        prior, continuation = self._load_prior_state(claim)
        target_canonical = self._load_canonical(claim.target.id)
        target_sessions = canonical_sessions(target_canonical, "Dataset Release")
        appended_sessions = [
            session
            for session in target_sessions
            if claim.target.appended_session_start <= session <= claim.target.appended_session_end
        ]
        if not appended_sessions:
            raise RuntimeError("Dataset Release successor has no appended sessions")
        state = self._advance_kernel(
            AdvanceInput(
                prior_state=prior,
                target_canonical_release=target_canonical,
                appended_sessions=appended_sessions,
                continuation=continuation,
            )
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
            payloads={
                "checkpoint": JsonPayload(
                    _state_payload(
                        state,
                        retained_strategy_sessions=[
                            prior.boundary_session,
                            *appended_sessions,
                        ],
                    )
                )
            },
            provenance=provenance,
        )
        return prepared, provenance, state

    def _load_prior_state(
        self,
        claim: _ProgressionClaim,
    ) -> tuple[KernelState, Mapping[str, object]]:
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
            return state, continuation_snapshot(state)
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
        checkpoint = KernelStateCheckpoint.model_validate(value)
        canonical = self._load_canonical(claim.current_release_id)
        state = _state_from_payload(value, canonical)
        if self._working_cache is None:
            continuation = self._rebuild_prior_continuation(claim, state)
            _verify_checkpoint_continuation(checkpoint, continuation)
            return state, continuation
        cached = self._working_cache.load(
            track_id=claim.track_id,
            release_id=claim.current_release_id,
            head_manifest_sha256=claim.head_manifest_sha256,
            fence=claim.fence - 1,
            continuation_sha256=checkpoint.continuation_sha256,
            pending_alpha_sessions=checkpoint.pending_alpha_sessions,
            rolling_factor_rows=checkpoint.rolling_factor_rows,
        )
        if cached is not None:
            return state, cached
        verified_continuation = self._rebuild_prior_continuation(claim, state)
        _verify_checkpoint_continuation(checkpoint, verified_continuation)
        self._working_cache.store(
            track_id=claim.track_id,
            release_id=claim.current_release_id,
            head_manifest_sha256=claim.head_manifest_sha256,
            fence=claim.fence - 1,
            verified_continuation=verified_continuation,
        )
        return state, verified_continuation

    def _rebuild_prior_continuation(
        self,
        claim: _ProgressionClaim,
        head_state: KernelState,
    ) -> Mapping[str, object]:
        """Rebuild fixed-size transient windows from a bounded verified Release tail."""
        assert self._publication is not None
        assert self._load_canonical is not None
        with self._database.transaction() as transaction:
            fetched = transaction.execute(
                """
                SELECT target_release_id, predecessor_release_id,
                       manifest_sha256, provenance, strategy_session
                FROM daily_tracks.checkpoints
                WHERE track_id = %s
                ORDER BY strategy_session DESC, target_release_id DESC
                LIMIT %s
                """,
                (claim.track_id, REBUILD_CHECKPOINT_LIMIT + 1),
            ).fetchall()
        if not fetched:
            raise RuntimeError("DailyTrack Checkpoint chain is missing")
        if str(fetched[0]["target_release_id"]) != claim.current_release_id:
            raise RuntimeError("DailyTrack Checkpoint chain does not reach its Head")
        head_calendar = canonical_sessions(
            head_state.canonical_snapshot(),
            "DailyTrack Head Dataset Release",
        )
        selected_steps, use_seed_continuation = _select_rebuild_steps(
            fetched,
            head_calendar=head_calendar,
            seed_release_id=claim.origin.seed_release_id,
            seed_session=claim.origin.initial_strategy_state.session,
        )
        if use_seed_continuation:
            seed = self._load_canonical(claim.origin.seed_release_id)
            seed_sessions = canonical_sessions(seed, "Seed Dataset Release")
            if len(seed_sessions) < 756:
                raise RuntimeError("Seed Dataset Release has fewer than 756 sessions")
            seed_state = run(
                _kernel_input(
                    claim.origin,
                    slice_canonical_sessions(
                        seed,
                        seed_sessions[-756:],
                    ),
                )
            ).track_state
            continuation = continuation_snapshot(seed_state)
        else:
            continuation = empty_continuation()
        predecessor_release_id = str(selected_steps[0][0]["predecessor_release_id"])
        processed_sessions = 0
        for row, appended_sessions in selected_steps:
            target_release_id = str(row["target_release_id"])
            if str(row["predecessor_release_id"]) != predecessor_release_id:
                raise RuntimeError("DailyTrack Checkpoint Release chain is invalid")
            bundle = self._publication.read(
                PublishedRef(
                    manifest_sha256=str(row["manifest_sha256"]),
                    kind="daily-track.checkpoint",
                    provenance=dict(row["provenance"]),
                )
            )
            checkpoint_payload = bundle.payloads.get("checkpoint")
            if checkpoint_payload is None or checkpoint_payload.media_type != "application/json":
                raise RuntimeError("DailyTrack Checkpoint payload is missing")
            checkpoint_value = json.loads(checkpoint_payload.content)
            if not isinstance(checkpoint_value, Mapping):
                raise RuntimeError("DailyTrack Checkpoint payload is invalid")
            checkpoint = KernelStateCheckpoint.model_validate(checkpoint_value)
            target_canonical = self._load_canonical(target_release_id)
            target_sessions = canonical_sessions(target_canonical, "Dataset Release")
            try:
                target_boundary_index = head_calendar.index(checkpoint.boundary_session)
            except ValueError as error:
                raise RuntimeError(
                    "DailyTrack Checkpoint boundary is outside its Head Release"
                ) from error
            if (
                checkpoint.session_count != len(target_sessions)
                or checkpoint.boundary_session != target_sessions[-1]
                or target_sessions != head_calendar[: target_boundary_index + 1]
            ):
                raise RuntimeError(
                    "DailyTrack Checkpoint boundary does not match its Dataset Release"
                )
            continuation = advance_continuation(
                run_input=head_state.run_input_with_canonical(target_canonical),
                prior_continuation=continuation,
                target_canonical=target_canonical,
                appended_sessions=appended_sessions,
            )
            processed_sessions += len(appended_sessions)
            predecessor_release_id = target_release_id
        if processed_sessions > REBUILD_CHECKPOINT_LIMIT:
            raise RuntimeError("DailyTrack continuation rebuild exceeded its session bound")
        return continuation

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
                verified_continuation=continuation_snapshot(state),
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

    def _record_progression_failure(
        self,
        claim: _ProgressionClaim,
        error: Exception,
    ) -> None:
        failure_reason = type(error).__name__
        with self._database.transaction() as transaction:
            track = transaction.execute(
                """
                SELECT status, current_release_id, execution_fence
                FROM daily_tracks.tracks
                WHERE id = %s
                FOR UPDATE
                """,
                (claim.track_id,),
            ).fetchone()
            progression = transaction.execute(
                """
                SELECT status, fence
                FROM daily_tracks.progressions
                WHERE track_id = %s AND target_release_id = %s
                FOR UPDATE
                """,
                (claim.track_id, claim.target.id),
            ).fetchone()
            attempt = transaction.execute(
                """
                SELECT status, fence, ordinal
                FROM daily_tracks.progression_attempts
                WHERE id = %s AND track_id = %s AND target_release_id = %s
                FOR UPDATE
                """,
                (claim.attempt_id, claim.track_id, claim.target.id),
            ).fetchone()
            if track != {
                "status": "active",
                "current_release_id": claim.current_release_id,
                "execution_fence": claim.fence,
            }:
                raise DailyTrackFenced
            if progression != {"status": "running", "fence": claim.fence}:
                raise DailyTrackFenced
            if (
                attempt is None
                or attempt["status"] != "running"
                or int(attempt["fence"]) != claim.fence
            ):
                raise DailyTrackFenced
            failed = transaction.execute(
                """
                UPDATE daily_tracks.progression_attempts
                SET status = 'failed', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now(),
                    failure_reason = %s
                WHERE id = %s AND track_id = %s AND target_release_id = %s
                  AND status = 'running' AND fence = %s
                """,
                (
                    failure_reason,
                    claim.attempt_id,
                    claim.track_id,
                    claim.target.id,
                    claim.fence,
                ),
            )
            if failed.rowcount != 1:
                raise DailyTrackFenced
            if int(attempt["ordinal"]) < MAX_AUTOMATIC_PROGRESSION_ATTEMPTS:
                return
            blocked_progression = transaction.execute(
                """
                UPDATE daily_tracks.progressions
                SET status = 'blocked', finished_at = now()
                WHERE track_id = %s AND target_release_id = %s
                  AND status = 'running' AND fence = %s
                """,
                (claim.track_id, claim.target.id, claim.fence),
            )
            blocked_track = transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET status = 'blocked', blocked_target_release_id = %s,
                    blocked_reason = %s
                WHERE id = %s AND status = 'active'
                  AND current_release_id = %s AND execution_fence = %s
                """,
                (
                    claim.target.id,
                    PUBLIC_BLOCKED_REASON,
                    claim.track_id,
                    claim.current_release_id,
                    claim.fence,
                ),
            )
            if blocked_progression.rowcount != 1 or blocked_track.rowcount != 1:
                raise DailyTrackFenced

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
        status=row["status"],
        seed_run_id=origin.seed_run_id,
        seed_release_id=origin.seed_release_id,
        current_release_id=str(row["current_release_id"]),
        definition_id=origin.definition_id,
        definition_revision=origin.definition_revision,
        result_checksum_sha256=verified_result.result_checksum_sha256,
        strategy_session=str(row["current_strategy_session"]),
    )


def _recent_checkpoint_rows(
    transaction: PostgresTransaction,
    *,
    track_id: str,
    head_manifest_sha256: object,
) -> list[dict[str, object]]:
    if head_manifest_sha256 is None:
        return []
    return transaction.execute(
        """
        WITH RECURSIVE recent AS (
            SELECT checkpoint.track_id, checkpoint.target_release_id,
                   checkpoint.predecessor_release_id,
                   checkpoint.manifest_sha256, checkpoint.provenance, 1 AS depth
            FROM daily_tracks.checkpoints AS checkpoint
            WHERE checkpoint.track_id = %s
              AND checkpoint.manifest_sha256 = %s

            UNION ALL

            SELECT predecessor.track_id, predecessor.target_release_id,
                   predecessor.predecessor_release_id,
                   predecessor.manifest_sha256, predecessor.provenance,
                   recent.depth + 1
            FROM recent
            JOIN daily_tracks.checkpoints AS predecessor
              ON predecessor.track_id = recent.track_id
             AND predecessor.target_release_id = recent.predecessor_release_id
            WHERE recent.depth < 504
        )
        SELECT target_release_id, predecessor_release_id,
               manifest_sha256, provenance
        FROM recent
        ORDER BY depth
        """,
        (track_id, str(head_manifest_sha256)),
    ).fetchall()


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
        "dataset_release_id": origin.seed_release_id,
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


def _ordered_checkpoint_chain(
    rows: list[Mapping[str, object]],
    *,
    seed_release_id: str,
    head_release_id: str,
) -> list[Mapping[str, object]]:
    by_target = {str(row["target_release_id"]): row for row in rows}
    if len(by_target) != len(rows):
        raise DailyTrackEquivalenceMismatch("EQUIVALENCE_MISMATCH at $.checkpoints.identity")
    ordered_desc: list[Mapping[str, object]] = []
    visited: set[str] = set()
    cursor = head_release_id
    while cursor != seed_release_id:
        if cursor in visited:
            raise DailyTrackEquivalenceMismatch("EQUIVALENCE_MISMATCH at $.checkpoints.cycle")
        visited.add(cursor)
        row = by_target.get(cursor)
        if row is None:
            raise DailyTrackEquivalenceMismatch(f"EQUIVALENCE_MISMATCH at $.checkpoints.{cursor}")
        ordered_desc.append(row)
        cursor = str(row["predecessor_release_id"])
    if len(ordered_desc) != len(rows):
        raise DailyTrackEquivalenceMismatch("EQUIVALENCE_MISMATCH at $.checkpoints.length")
    return list(reversed(ordered_desc))


def _assert_equivalent(actual: object, expected: object, coordinate: str) -> None:
    divergence = first_divergence(actual, expected)
    if not divergence:
        return
    suffix = divergence[1:] if divergence.startswith("$") else divergence
    raise DailyTrackEquivalenceMismatch(f"EQUIVALENCE_MISMATCH at {coordinate}{suffix}")


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


def _select_rebuild_steps(
    fetched: list[Mapping[str, object]],
    *,
    head_calendar: list[str],
    seed_release_id: str,
    seed_session: str,
) -> tuple[list[tuple[Mapping[str, object], list[str]]], bool]:
    """Select an ordered Release suffix containing at most 525 actual sessions."""
    calendar_index = {session: index for index, session in enumerate(head_calendar)}
    selected_desc: list[tuple[Mapping[str, object], list[str]]] = []
    selected_session_count = 0
    reached_origin = False
    for index, row in enumerate(fetched):
        target_boundary = str(row["strategy_session"])
        target_index = calendar_index.get(target_boundary)
        if target_index is None:
            raise RuntimeError("DailyTrack Checkpoint boundary is outside its Head Release")
        if index + 1 < len(fetched):
            predecessor_row = fetched[index + 1]
            if str(row["predecessor_release_id"]) != str(predecessor_row["target_release_id"]):
                raise RuntimeError("DailyTrack Checkpoint Release chain is invalid")
            predecessor_boundary = str(predecessor_row["strategy_session"])
        elif str(row["predecessor_release_id"]) == seed_release_id:
            predecessor_boundary = seed_session
            reached_origin = True
        else:
            raise RuntimeError("DailyTrack Checkpoint tail is too short to rebuild")
        predecessor_index = calendar_index.get(predecessor_boundary)
        if predecessor_index is None or predecessor_index >= target_index:
            raise RuntimeError("DailyTrack Checkpoint session chain is invalid")
        available = target_index - predecessor_index
        selected_count = min(
            available,
            REBUILD_CHECKPOINT_LIMIT - selected_session_count,
        )
        selected_desc.append(
            (
                row,
                head_calendar[target_index - selected_count + 1 : target_index + 1],
            )
        )
        selected_session_count += selected_count
        if selected_session_count == REBUILD_CHECKPOINT_LIMIT or reached_origin:
            break
    if selected_session_count < REBUILD_CHECKPOINT_LIMIT and not reached_origin:
        raise RuntimeError("DailyTrack Checkpoint tail is too short to rebuild")
    return (
        list(reversed(selected_desc)),
        selected_session_count < REBUILD_CHECKPOINT_LIMIT,
    )


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


def _verify_checkpoint_continuation(
    checkpoint: KernelStateCheckpoint,
    continuation: Mapping[str, object],
) -> None:
    content = canonical_json_bytes(continuation)
    pending = continuation.get("pending_alpha")
    rolling = continuation.get("rolling_factor")
    if not isinstance(pending, list) or not isinstance(rolling, list):
        raise RuntimeError("DailyTrack rebuilt continuation is invalid")
    if (
        hashlib.sha256(content).hexdigest() != checkpoint.continuation_sha256
        or len(pending) != checkpoint.pending_alpha_sessions
        or len(rolling) != checkpoint.rolling_factor_rows
    ):
        raise PublicationVerificationError(
            "DailyTrack Checkpoint continuation does not match rebuilt state"
        )
