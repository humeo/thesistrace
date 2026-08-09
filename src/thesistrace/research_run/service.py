from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Thread
from uuid import uuid4

from psycopg import OperationalError
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout
from pydantic import ValidationError

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.daily_track import DailyTrackSummary, TrackingOrigin
from thesistrace.publication import (
    PreparedPublication,
    Publication,
    PublicationNotFoundError,
    PublicationUnavailableError,
    PublicationVerificationError,
    PublishedRef,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)
from thesistrace.research_kernel.kernel_run import RunInput, RunOutput
from thesistrace.research_kernel.kernel_run import run as run_kernel
from thesistrace.research_run.models import (
    ImmutableRunInput,
    ResearchRunCancelCommand,
    ResearchRunDetail,
    ResearchRunList,
    ResearchRunRerunCommand,
    ResearchRunResult,
    ResearchRunSummary,
    StartTrackingCommand,
)
from thesistrace.research_run.result import (
    ResearchResultError,
    build_result_payload,
    enforce_result_bundle_budget,
    read_result_bundle,
    result_publication_payloads,
)

logger = logging.getLogger(__name__)
ATTEMPT_LEASE_SECONDS = 15 * 60
ATTEMPT_HEARTBEAT_SECONDS = 30
MAX_RESEARCH_RUN_ATTEMPTS = 3
MAX_RESOURCE_EXHAUSTED_ATTEMPTS = 2
INFRASTRUCTURE_FAILURE = "InfrastructureUnavailable"
RESOURCE_EXHAUSTED_FAILURE = "ResourceExhausted"
WORKER_LOST_FAILURE = "WorkerLost"
INFRASTRUCTURE_PUBLIC_REASON = "Research execution could not access required infrastructure."
RESOURCE_EXHAUSTED_PUBLIC_REASON = "Research execution exceeded its resource limit."
AUTOMATIC_RETRIES_PUBLIC_REASON = "Research execution could not complete after automatic retries."
PERMANENT_FAILURE_PUBLIC_REASON = "Research execution failed."
RETRYABLE_FAILURES = (
    INFRASTRUCTURE_FAILURE,
    RESOURCE_EXHAUSTED_FAILURE,
    WORKER_LOST_FAILURE,
)
LoadCanonical = Callable[[str], dict[str, object]]
ExecuteKernel = Callable[[RunInput], RunOutput]
Progress = Callable[[str, str], None]
ActivateTrack = Callable[
    [PostgresTransaction, TrackingOrigin],
    DailyTrackSummary,
]


class ResearchRunFenced(RuntimeError):
    pass


class ResearchRunCancelConflict(RuntimeError):
    pass


class ResearchRunRerunConflict(RuntimeError):
    pass


class ResearchRunStartTrackingConflict(RuntimeError):
    pass


class ResearchRunResultUnavailable(RuntimeError):
    pass


class ResearchRunTrackingUnavailable(RuntimeError):
    pass


class ResearchRunTrackingTemporarilyUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class _ExecutionClaim:
    run_id: str
    attempt_id: str
    fence: int
    immutable_input: ImmutableRunInput


@dataclass(frozen=True)
class _FailurePolicy:
    attempt_reason: str
    public_reason: str
    max_attempts: int
    retryable: bool


class ResearchRunService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        load_canonical: LoadCanonical | None = None,
        publication: Publication | None = None,
        execute_kernel: ExecuteKernel = run_kernel,
        progress: Progress | None = None,
        lease_seconds: float = ATTEMPT_LEASE_SECONDS,
        heartbeat_seconds: float = ATTEMPT_HEARTBEAT_SECONDS,
        activate_track: ActivateTrack | None = None,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0:
            raise ValueError("ResearchRun lease and heartbeat intervals must be positive")
        self._database = database
        self._load_canonical = load_canonical
        self._publication = publication
        self._execute_kernel = execute_kernel
        self._progress = progress or (lambda _stage, _run_id: None)
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._activate_track = activate_track

    def admit(
        self,
        transaction: PostgresTransaction,
        immutable_input: ImmutableRunInput,
    ) -> ResearchRunSummary:
        """Admit one Run in the caller's transaction without committing it."""
        definition = immutable_input.definition
        run_id = f"run_{uuid4().hex[:20]}"
        row = transaction.execute(
            """
            INSERT INTO research_runs.runs (
                id, definition_id, definition_revision,
                requested_start_date, requested_end_date, status, immutable_input
            ) VALUES (%s, %s, %s, %s, %s, 'queued', %s)
            RETURNING id, status, definition_id, definition_revision,
                      requested_start_date, requested_end_date, rerun_of_id
            """,
            (
                run_id,
                str(definition["id"]),
                int(definition["revision"]),
                immutable_input.requested_start_date,
                immutable_input.requested_end_date,
                Jsonb(immutable_input.model_dump(mode="json")),
            ),
        ).fetchone()
        assert row is not None
        return _summary(row)

    def process_next(self) -> bool:
        if not self._execution_is_configured():
            return False
        claim = self._claim_next()
        if claim is None:
            return False
        with self._maintain_claim(claim):
            self._progress("claimed", claim.run_id)
            try:
                prepared, provenance = self._execute(claim)
                self._progress("prepared", claim.run_id)
                self._publish_success(claim, prepared, provenance)
                self._progress("succeeded", claim.run_id)
            except ResearchRunFenced:
                logger.info(
                    "ResearchRun result rejected by execution fence",
                    extra={"run_id": claim.run_id},
                )
            except Exception as error:
                self._record_failure(claim, error)
                logger.error(
                    "ResearchRun execution failed",
                    extra={"run_id": claim.run_id, "error_type": type(error).__name__},
                )
        return True

    def list(self) -> ResearchRunList:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, status, definition_id, definition_revision,
                       requested_start_date, requested_end_date,
                       rerun_of_id, failure_reason
                FROM research_runs.runs
                ORDER BY created_at DESC, id
                """
            ).fetchall()
        return ResearchRunList(items=[_summary(row) for row in rows], next_cursor=None)

    def get(self, run_id: str) -> ResearchRunSummary | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, status, definition_id, definition_revision,
                       requested_start_date, requested_end_date,
                       rerun_of_id, failure_reason
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        return None if row is None else _summary(row)

    def cancel(
        self,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunSummary | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("ResearchRun Cancel request_id is required")
        fingerprint = _cancel_fingerprint(run_id)
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"research_runs.cancel:{request_id}",),
            ).fetchone()
            receipt = transaction.execute(
                """
                SELECT request_fingerprint, outcome
                FROM research_runs.cancel_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise ResearchRunCancelConflict("ResearchRun Cancel request_id conflicts")
                return ResearchRunSummary.model_validate(receipt["outcome"])

            row = transaction.execute(
                """
                SELECT id, status, definition_id, definition_revision,
                       requested_start_date, requested_end_date,
                       rerun_of_id, failure_reason
                FROM research_runs.runs
                WHERE id = %s
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] in {"queued", "running"}:
                transaction.execute(
                    """
                    UPDATE research_runs.attempts
                    SET status = 'cancelled', heartbeat_at = now(),
                        lease_expires_at = now(), finished_at = now(),
                        failure_reason = 'UserCancelled'
                    WHERE run_id = %s AND status = 'running'
                    """,
                    (run_id,),
                )
                updated = transaction.execute(
                    """
                    UPDATE research_runs.runs
                    SET status = 'cancelled',
                        execution_fence = execution_fence + 1,
                        failure_reason = NULL, updated_at = now()
                    WHERE id = %s AND status IN ('queued', 'running')
                    RETURNING id, status, definition_id, definition_revision,
                              requested_start_date, requested_end_date,
                              rerun_of_id, failure_reason
                    """,
                    (run_id,),
                ).fetchone()
                if updated is None:
                    raise ResearchRunFenced
                row = updated
            outcome = _summary(row)
            transaction.execute(
                """
                INSERT INTO research_runs.cancel_receipts (
                    request_id, request_fingerprint, run_id, outcome
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    request_id,
                    fingerprint,
                    run_id,
                    Jsonb(outcome.model_dump(mode="json")),
                ),
            )
        return outcome

    def rerun(
        self,
        run_id: str,
        command: ResearchRunRerunCommand,
    ) -> ResearchRunSummary | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("ResearchRun Rerun request_id is required")
        fingerprint = _rerun_fingerprint(run_id)
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"research_runs.rerun:{request_id}",),
            ).fetchone()
            receipt = transaction.execute(
                """
                SELECT request_fingerprint, outcome
                FROM research_runs.rerun_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise ResearchRunRerunConflict("ResearchRun Rerun request_id conflicts")
                return ResearchRunSummary.model_validate(receipt["outcome"])

            rerun_id = f"run_{uuid4().hex[:20]}"
            row = transaction.execute(
                """
                INSERT INTO research_runs.runs (
                    id, definition_id, definition_revision,
                    requested_start_date, requested_end_date,
                    status, immutable_input, rerun_of_id
                )
                SELECT %s, definition_id, definition_revision,
                       requested_start_date, requested_end_date,
                       'queued', immutable_input, id
                FROM research_runs.runs
                WHERE id = %s
                RETURNING id, status, definition_id, definition_revision,
                          requested_start_date, requested_end_date, rerun_of_id
                """,
                (rerun_id, run_id),
            ).fetchone()
            if row is None:
                return None
            outcome = _summary(row)
            transaction.execute(
                """
                INSERT INTO research_runs.rerun_receipts (
                    request_id, request_fingerprint, source_run_id,
                    rerun_id, outcome
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    request_id,
                    fingerprint,
                    run_id,
                    rerun_id,
                    Jsonb(outcome.model_dump(mode="json")),
                ),
            )
        return outcome

    def start_tracking(
        self,
        run_id: str,
        command: StartTrackingCommand,
    ) -> DailyTrackSummary | None:
        if self._activate_track is None or self._publication is None:
            raise RuntimeError("DailyTrack activation dependencies are not configured")
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("Start Tracking request_id is required")
        fingerprint = _start_tracking_fingerprint(run_id)
        try:
            with self._database.transaction() as transaction:
                transaction.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"research_runs.start_tracking:{request_id}",),
                ).fetchone()
                receipt = transaction.execute(
                    """
                    SELECT request_fingerprint, outcome
                    FROM research_runs.start_tracking_receipts
                    WHERE request_id = %s
                    """,
                    (request_id,),
                ).fetchone()
                if receipt is not None:
                    if receipt["request_fingerprint"] != fingerprint:
                        raise ResearchRunStartTrackingConflict(
                            "Start Tracking request_id conflicts"
                        )
                    return DailyTrackSummary.model_validate(receipt["outcome"])
                row = transaction.execute(
                    """
                    SELECT id, status, definition_id, definition_revision,
                           requested_start_date, requested_end_date, immutable_input,
                           result_manifest_sha256, result_provenance
                    FROM research_runs.runs
                    WHERE id = %s
                    FOR SHARE
                    """,
                    (run_id,),
                ).fetchone()
                if row is None:
                    return None
                if row["status"] != "succeeded":
                    raise ResearchRunTrackingUnavailable(
                        "Start Tracking requires a succeeded ResearchRun"
                    )
                try:
                    origin = self._tracking_origin(transaction, row)
                except PublicationUnavailableError:
                    raise
                except (
                    json.JSONDecodeError,
                    KeyError,
                    PublicationNotFoundError,
                    PublicationVerificationError,
                    ResearchResultError,
                    ResearchRunResultUnavailable,
                    ValidationError,
                ) as error:
                    logger.info(
                        "ResearchRun is not eligible for Tracking",
                        extra={"run_id": run_id, "error_type": type(error).__name__},
                    )
                    raise ResearchRunTrackingUnavailable(
                        "Start Tracking requires a complete verified Result"
                    ) from error
                outcome = self._activate_track(transaction, origin)
                transaction.execute(
                    """
                    INSERT INTO research_runs.start_tracking_receipts (
                        request_id, request_fingerprint, seed_run_id,
                        track_id, outcome
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        request_id,
                        fingerprint,
                        run_id,
                        outcome.id,
                        Jsonb(outcome.model_dump(mode="json")),
                    ),
                )
                return outcome
        except (OperationalError, PoolTimeout, PublicationUnavailableError) as error:
            logger.warning(
                "Start Tracking infrastructure is temporarily unavailable",
                extra={"run_id": run_id, "error_type": type(error).__name__},
            )
            raise ResearchRunTrackingTemporarilyUnavailable(
                "Start Tracking is temporarily unavailable"
            ) from error

    def get_detail(self, run_id: str) -> ResearchRunDetail | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, status, definition_id, definition_revision,
                       requested_start_date, requested_end_date,
                       rerun_of_id, result_manifest_sha256,
                       result_provenance, failure_reason
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        summary = _summary(row)
        if summary.status != "succeeded":
            return ResearchRunDetail(**summary.model_dump())
        manifest_sha256 = row.get("result_manifest_sha256")
        provenance = row.get("result_provenance")
        if (
            self._publication is None
            or not isinstance(manifest_sha256, str)
            or not isinstance(provenance, Mapping)
        ):
            raise ResearchRunResultUnavailable
        try:
            bundle = self._publication.read(
                PublishedRef(
                    manifest_sha256=manifest_sha256,
                    kind="research.result",
                    provenance=dict(provenance),
                )
            )
            stored_result = read_result_bundle(bundle)
            result = _public_result(stored_result, dict(provenance))
        except Exception as error:
            logger.error(
                "ResearchRun Result read failed",
                extra={"run_id": run_id, "error_type": type(error).__name__},
            )
            raise ResearchRunResultUnavailable from error
        return ResearchRunDetail(**summary.model_dump(), result=result)

    def _tracking_origin(
        self,
        transaction: PostgresTransaction,
        row: dict[str, object],
    ) -> TrackingOrigin:
        if self._publication is None:
            raise ResearchRunTrackingUnavailable
        immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
        manifest_sha256 = row.get("result_manifest_sha256")
        provenance = row.get("result_provenance")
        if not isinstance(manifest_sha256, str) or not isinstance(provenance, Mapping):
            raise ResearchRunTrackingUnavailable
        selected_provenance = dict(provenance)
        expected_digest = hashlib.sha256(
            canonical_json_bytes(immutable_input.model_dump(mode="json"))
        ).hexdigest()
        if (
            selected_provenance.get("research_run_id") != row["id"]
            or selected_provenance.get("immutable_input_sha256") != expected_digest
        ):
            raise ResearchRunTrackingUnavailable
        data_generation_id = selected_provenance.get("data_generation_id")
        if not isinstance(data_generation_id, str):
            raise ResearchRunTrackingUnavailable
        bundle = self._publication.read_in_transaction(
            transaction,
            PublishedRef(
                manifest_sha256=manifest_sha256,
                kind="research.result",
                provenance=selected_provenance,
            ),
        )
        stored_result = read_result_bundle(bundle)
        _public_result(stored_result, selected_provenance)
        if not isinstance(stored_result, Mapping):
            raise ResearchRunTrackingUnavailable
        initial_strategy_state = stored_result.get("terminal_strategy_state")
        calculation_contracts = selected_provenance.get("calculation_contracts")
        if not isinstance(initial_strategy_state, Mapping) or not isinstance(
            calculation_contracts, Mapping
        ):
            raise ResearchRunTrackingUnavailable
        return TrackingOrigin(
            seed_run_id=str(row["id"]),
            definition_id=str(row["definition_id"]),
            definition_revision=int(row["definition_revision"]),
            immutable_input=immutable_input.model_dump(mode="json"),
            seed_release_id=data_generation_id,
            verified_result={
                "kind": "research.result",
                "research_run_id": str(row["id"]),
                "schema_version": str(selected_provenance["schema_version"]),
                "result_manifest_sha256": manifest_sha256,
                "result_checksum_sha256": hashlib.sha256(
                    canonical_json_bytes(stored_result)
                ).hexdigest(),
            },
            initial_strategy_state=dict(initial_strategy_state),
            calculation_contracts=dict(calculation_contracts),
        )

    def _execution_is_configured(self) -> bool:
        return self._load_canonical is not None and self._publication is not None

    def _claim_next(self) -> _ExecutionClaim | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.id, run.status, run.immutable_input,
                       run.execution_fence,
                       attempt.id AS latest_attempt_id,
                       attempt.ordinal AS latest_attempt_ordinal,
                       attempt.status AS latest_attempt_status,
                       EXISTS (
                           SELECT 1
                           FROM research_runs.attempts AS exhausted
                           WHERE exhausted.run_id = run.id
                             AND exhausted.failure_reason = %s
                       ) AS resource_exhausted_seen
                FROM research_runs.runs AS run
                LEFT JOIN LATERAL (
                    SELECT id, ordinal, status, lease_expires_at, failure_reason
                    FROM research_runs.attempts
                    WHERE run_id = run.id
                    ORDER BY ordinal DESC
                    LIMIT 1
                ) AS attempt ON true
                WHERE run.status = 'queued'
                   OR (
                        run.status = 'running'
                        AND (
                            (
                                attempt.status = 'running'
                                AND attempt.lease_expires_at <= now()
                            )
                            OR (
                                attempt.status = 'failed'
                                AND attempt.failure_reason = ANY(%s)
                            )
                        )
                   )
                ORDER BY run.created_at, run.id
                FOR UPDATE OF run SKIP LOCKED
                LIMIT 1
                """,
                (RESOURCE_EXHAUSTED_FAILURE, list(RETRYABLE_FAILURES)),
            ).fetchone()
            if row is None:
                return None
            run_id = str(row["id"])
            if row["latest_attempt_status"] == "running":
                recovered = transaction.execute(
                    """
                    UPDATE research_runs.attempts
                    SET status = 'failed', heartbeat_at = now(),
                        lease_expires_at = now(), finished_at = now(),
                        failure_reason = %s
                    WHERE id = %s AND run_id = %s AND status = 'running'
                      AND lease_expires_at <= now()
                    """,
                    (WORKER_LOST_FAILURE, row["latest_attempt_id"], run_id),
                )
                if recovered.rowcount != 1:
                    return None
                attempt_limit = (
                    MAX_RESOURCE_EXHAUSTED_ATTEMPTS
                    if row["resource_exhausted_seen"]
                    else MAX_RESEARCH_RUN_ATTEMPTS
                )
                if int(row["latest_attempt_ordinal"]) >= attempt_limit:
                    terminal_reason = (
                        RESOURCE_EXHAUSTED_PUBLIC_REASON
                        if row["resource_exhausted_seen"]
                        else AUTOMATIC_RETRIES_PUBLIC_REASON
                    )
                    transaction.execute(
                        """
                        UPDATE research_runs.runs
                        SET status = 'failed',
                            failure_reason = %s, updated_at = now()
                        WHERE id = %s AND status = 'running'
                          AND execution_fence = %s
                        """,
                        (
                            terminal_reason,
                            run_id,
                            row["execution_fence"],
                        ),
                    )
                    return None
            fence = int(row["execution_fence"]) + 1
            ordinal_row = transaction.execute(
                """
                SELECT coalesce(max(ordinal), 0) + 1 AS ordinal
                FROM research_runs.attempts
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
            assert ordinal_row is not None
            attempt_id = f"attempt_{uuid4().hex[:20]}"
            transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = 'running', execution_fence = %s,
                    failure_reason = NULL, updated_at = now()
                WHERE id = %s
                """,
                (fence, run_id),
            )
            transaction.execute(
                """
                INSERT INTO research_runs.attempts (
                    id, run_id, ordinal, fence, status, lease_expires_at
                ) VALUES (
                    %s, %s, %s, %s, 'running',
                    now() + make_interval(secs => %s)
                )
                """,
                (
                    attempt_id,
                    run_id,
                    int(ordinal_row["ordinal"]),
                    fence,
                    self._lease_seconds,
                ),
            )
        return _ExecutionClaim(
            run_id=run_id,
            attempt_id=attempt_id,
            fence=fence,
            immutable_input=ImmutableRunInput.model_validate(row["immutable_input"]),
        )

    @contextmanager
    def _maintain_claim(self, claim: _ExecutionClaim) -> Iterator[None]:
        stopped = Event()
        heartbeat = Thread(
            target=self._heartbeat_claim,
            args=(claim, stopped),
            name=f"research-run-heartbeat-{claim.run_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat.join(timeout=5)

    def _heartbeat_claim(self, claim: _ExecutionClaim, stopped: Event) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    renewed = transaction.execute(
                        """
                        UPDATE research_runs.attempts AS attempt
                        SET heartbeat_at = now(),
                            lease_expires_at = now() + make_interval(secs => %s)
                        WHERE attempt.id = %s AND attempt.run_id = %s
                          AND attempt.fence = %s AND attempt.status = 'running'
                          AND EXISTS (
                              SELECT 1
                              FROM research_runs.runs AS run
                              WHERE run.id = attempt.run_id
                                AND run.status = 'running'
                                AND run.execution_fence = attempt.fence
                          )
                        """,
                        (
                            self._lease_seconds,
                            claim.attempt_id,
                            claim.run_id,
                            claim.fence,
                        ),
                    )
            except Exception as error:
                logger.error(
                    "ResearchRun claim heartbeat failed",
                    extra={
                        "run_id": claim.run_id,
                        "error_type": type(error).__name__,
                    },
                )
                return
            if renewed.rowcount != 1:
                return

    def _execute(
        self,
        claim: _ExecutionClaim,
    ) -> tuple[PreparedPublication, dict[str, object]]:
        raise RuntimeError("ResearchRun Attempt must select current Data before execution")

    def _prepare_result(
        self,
        claim: _ExecutionClaim,
        canonical: dict[str, object],
    ) -> tuple[PreparedPublication, dict[str, object]]:
        assert self._publication is not None
        immutable_input = claim.immutable_input
        kernel_input = _kernel_input(immutable_input, canonical)
        output = self._execute_kernel(kernel_input)
        self._progress("calculated", claim.run_id)
        definition_content = immutable_input.definition.get("content")
        if not isinstance(definition_content, Mapping):
            raise RuntimeError("ResearchRun Definition content is invalid")
        result = build_result_payload(
            output,
            rebalance_interval=int(immutable_input.strategy["rebalance_every_sessions"]),
            universe=str(definition_content["universe"]),
        )
        provenance = _result_provenance(claim.run_id, immutable_input)
        prepared = self._publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads(result),
            provenance=provenance,
        )
        observations = result["strategy_daily_observations"]
        if not isinstance(observations, list):
            raise RuntimeError("Result Strategy Daily Observations are invalid")
        enforce_result_bundle_budget(prepared.exact_bytes, len(observations))
        return prepared, provenance

    def _publish_success(
        self,
        claim: _ExecutionClaim,
        prepared: PreparedPublication,
        provenance: dict[str, object],
    ) -> None:
        assert self._publication is not None
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT status, execution_fence
                FROM research_runs.runs
                WHERE id = %s
                FOR UPDATE
                """,
                (claim.run_id,),
            ).fetchone()
            if current != {"status": "running", "execution_fence": claim.fence}:
                raise ResearchRunFenced
            published = self._publication.record(transaction, prepared)
            attempt = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET status = 'succeeded', heartbeat_at = now(),
                    finished_at = now()
                WHERE id = %s AND run_id = %s AND fence = %s AND status = 'running'
                """,
                (claim.attempt_id, claim.run_id, claim.fence),
            )
            if attempt.rowcount != 1:
                raise ResearchRunFenced
            updated = transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = 'succeeded', result_manifest_sha256 = %s,
                    result_provenance = %s, failure_reason = NULL,
                    updated_at = now()
                WHERE id = %s AND status = 'running' AND execution_fence = %s
                """,
                (
                    published.manifest_sha256,
                    Jsonb(provenance),
                    claim.run_id,
                    claim.fence,
                ),
            )
            if updated.rowcount != 1:
                raise ResearchRunFenced

    def _record_failure(self, claim: _ExecutionClaim, error: Exception) -> None:
        policy = _failure_policy(error)
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT status, execution_fence
                FROM research_runs.runs
                WHERE id = %s
                FOR UPDATE
                """,
                (claim.run_id,),
            ).fetchone()
            if current != {"status": "running", "execution_fence": claim.fence}:
                return
            attempt = transaction.execute(
                """
                SELECT status,
                       (SELECT count(*)
                        FROM research_runs.attempts AS counted
                        WHERE counted.run_id = %s) AS attempt_count,
                       EXISTS (
                           SELECT 1
                           FROM research_runs.attempts AS exhausted
                           WHERE exhausted.run_id = %s
                             AND exhausted.failure_reason = %s
                       ) AS resource_exhausted_seen
                FROM research_runs.attempts
                WHERE id = %s AND run_id = %s AND fence = %s
                FOR UPDATE
                """,
                (
                    claim.run_id,
                    claim.run_id,
                    RESOURCE_EXHAUSTED_FAILURE,
                    claim.attempt_id,
                    claim.run_id,
                    claim.fence,
                ),
            ).fetchone()
            if attempt is None or attempt["status"] != "running":
                return
            resource_limited = policy.attempt_reason == RESOURCE_EXHAUSTED_FAILURE or bool(
                attempt["resource_exhausted_seen"]
            )
            attempt_limit = (
                MAX_RESOURCE_EXHAUSTED_ATTEMPTS if resource_limited else policy.max_attempts
            )
            retry = policy.retryable and int(attempt["attempt_count"]) < attempt_limit
            failed_attempt = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET status = 'failed', heartbeat_at = now(), finished_at = now(),
                    lease_expires_at = now(), failure_reason = %s
                WHERE id = %s AND run_id = %s AND fence = %s AND status = 'running'
                """,
                (
                    policy.attempt_reason,
                    claim.attempt_id,
                    claim.run_id,
                    claim.fence,
                ),
            )
            if failed_attempt.rowcount != 1:
                return
            transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = %s, failure_reason = %s, updated_at = now()
                WHERE id = %s AND status = 'running' AND execution_fence = %s
                """,
                (
                    "running" if retry else "failed",
                    (
                        None
                        if retry
                        else (
                            RESOURCE_EXHAUSTED_PUBLIC_REASON
                            if resource_limited
                            else policy.public_reason
                        )
                    ),
                    claim.run_id,
                    claim.fence,
                ),
            )


def _research_input_history(canonical: dict[str, object]) -> dict[str, object]:
    sessions = canonical_sessions(canonical, "Dataset Release")
    if len(sessions) < 756:
        raise RuntimeError("Dataset Release has fewer than 756 Research Sessions")
    return slice_canonical_sessions(canonical, sessions[-756:])


def _kernel_input(
    immutable_input: ImmutableRunInput,
    canonical: dict[str, object],
) -> RunInput:
    definition = immutable_input.definition
    content = definition.get("content")
    if not isinstance(content, Mapping):
        raise RuntimeError("ResearchRun Definition content is invalid")
    alpha = content.get("alpha")
    if not isinstance(alpha, Mapping):
        raise RuntimeError("ResearchRun Alpha is invalid")
    strategy = immutable_input.strategy
    costs = immutable_input.costs
    return RunInput(
        canonical_data=canonical,
        alpha_expression=dict(alpha),
        field_bindings=immutable_input.field_bindings,
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


def _result_provenance(
    run_id: str,
    immutable_input: ImmutableRunInput,
) -> dict[str, object]:
    value = immutable_input.model_dump(mode="json")
    return {
        "schema_version": "research-result-v1",
        "research_run_id": run_id,
        "immutable_input_sha256": hashlib.sha256(canonical_json_bytes(value)).hexdigest(),
        "calculation_contracts": {
            "strategy": value["strategy"],
            "costs": value["costs"],
            "risk_free_rate": value["risk_free_rate"],
            "numeric_execution_contract": value["numeric_execution_contract"],
        },
        "semantic_versions": value["semantic_versions"],
    }


def _failure_policy(error: Exception) -> _FailurePolicy:
    if isinstance(error, MemoryError):
        return _FailurePolicy(
            attempt_reason=RESOURCE_EXHAUSTED_FAILURE,
            public_reason=RESOURCE_EXHAUSTED_PUBLIC_REASON,
            max_attempts=MAX_RESOURCE_EXHAUSTED_ATTEMPTS,
            retryable=True,
        )
    if isinstance(
        error,
        (
            PublicationUnavailableError,
            OperationalError,
            ConnectionError,
            TimeoutError,
        ),
    ):
        return _FailurePolicy(
            attempt_reason=INFRASTRUCTURE_FAILURE,
            public_reason=INFRASTRUCTURE_PUBLIC_REASON,
            max_attempts=MAX_RESEARCH_RUN_ATTEMPTS,
            retryable=True,
        )
    return _FailurePolicy(
        attempt_reason="PermanentExecutionFailure",
        public_reason=PERMANENT_FAILURE_PUBLIC_REASON,
        max_attempts=1,
        retryable=False,
    )


def _cancel_fingerprint(run_id: str) -> str:
    value = {"action": "research-runs.cancel/v1", "run_id": run_id}
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _rerun_fingerprint(run_id: str) -> str:
    value = {"action": "research-runs.rerun/v1", "run_id": run_id}
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _start_tracking_fingerprint(run_id: str) -> str:
    # Keep the original wire fingerprint stable while receipt ownership moves
    # from DailyTracks to ResearchRuns.
    value = {"action": "research-runs.start-tracking/v1", "seed_run_id": run_id}
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _summary(row: object) -> ResearchRunSummary:
    assert isinstance(row, dict)
    summary = {
        name: row[name]
        for name in (
            "id",
            "status",
            "definition_id",
            "definition_revision",
            "requested_start_date",
            "requested_end_date",
        )
    }
    summary["start_date"] = summary.pop("requested_start_date")
    summary["end_date"] = summary.pop("requested_end_date")
    summary["rerun_of_id"] = row.get("rerun_of_id")
    summary["failure_reason"] = row.get("failure_reason")
    return ResearchRunSummary.model_validate(summary)


def _public_result(
    stored: object,
    provenance: dict[str, object],
) -> ResearchRunResult:
    if not isinstance(stored, Mapping):
        raise ResearchRunResultUnavailable
    factor = stored.get("factor_summary")
    strategy_summary = stored.get("strategy_summary")
    observations = stored.get("strategy_daily_observations")
    if (
        not isinstance(factor, Mapping)
        or not isinstance(strategy_summary, Mapping)
        or not isinstance(observations, list)
    ):
        raise ResearchRunResultUnavailable
    stored_horizons = factor.get("horizons")
    if not isinstance(stored_horizons, Mapping) or set(stored_horizons) != {
        "1",
        "5",
        "20",
    }:
        raise ResearchRunResultUnavailable
    horizons: dict[str, object] = {}
    for name in ("1", "5", "20"):
        horizon = stored_horizons[name]
        if not isinstance(horizon, Mapping):
            raise ResearchRunResultUnavailable
        horizons[name] = {
            "horizon": horizon.get("horizon"),
            "summary": horizon.get("summary"),
            "coverage": horizon.get("coverage"),
        }
    benchmark = strategy_summary.get("benchmark")
    public_strategy_summary = {
        name: value for name, value in strategy_summary.items() if name != "benchmark"
    }
    return ResearchRunResult.model_validate(
        {
            "factor": {"horizons": horizons},
            "strategy": {
                "summary": public_strategy_summary,
                "benchmark": benchmark,
                "observations": observations,
            },
            "provenance": {
                name: provenance[name]
                for name in (
                    "schema_version",
                    "research_run_id",
                    "immutable_input_sha256",
                    "calculation_contracts",
                    "semantic_versions",
                )
            },
        }
    )
