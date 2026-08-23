from __future__ import annotations

import hashlib
import json
import math
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from psycopg import OperationalError
from psycopg.errors import OutOfMemory
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout
from pydantic import ValidationError

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.alpha_language import CompiledAlpha, FormulaCompilationError, alpha_language
from thesistrace.daily_track import DailyTrackSummary, TrackingOrigin
from thesistrace.data import (
    FINANCIAL_FIELDS,
    DatasetAdmissionSnapshot,
    DatasetLifecycle,
    DatasetWarmupUnavailable,
    MountedGenerationStore,
)
from thesistrace.operational_events import non_blocking_operational_event_sink
from thesistrace.publication import (
    JsonPayload,
    ParquetRowsPayload,
    PreparedPublication,
    Publication,
    PublicationNotFoundError,
    PublicationPreparationError,
    PublicationUnavailableError,
    PublicationVerificationError,
    PublishedRef,
    StagedPayload,
    lock_publication_mutation,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.alpha_expression import estimate_alpha_run_work
from thesistrace.research_kernel.numeric import (
    NUMERIC_CONTRACT_ID,
    NumericContractError,
    require_current_numeric_contract,
)
from thesistrace.research_kernel.research_chunks import validated_research_continuation
from thesistrace.research_run.execution import (
    ExecutionEvent,
    ResearchExecutionCancelled,
    ResearchExecutionError,
    ResearchExecutionInputInvalid,
    ResearchExecutionInsufficientWarmup,
    ResearchExecutionRequest,
    ResearchExecutionResourceExhausted,
    ResearchExecutionResume,
    SupervisedResearchExecution,
    SupervisedResearchExecutor,
)
from thesistrace.research_run.failure_policy import (
    RETRYABLE_ATTEMPT_FAILURES,
    attempt_failure_code,
    attempt_retry_eligible,
)
from thesistrace.research_run.models import (
    AlphaAdmissionFacts,
    DataAdmissionFacts,
    FactorEvaluationResearchRunKeyMetrics,
    FactorEvaluationResearchRunResult,
    ImmutableRunInput,
    OrganizeResearchRunCommand,
    ResearchKind,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionIssue,
    ResearchRunAuthorableInput,
    ResearchRunCancelCommand,
    ResearchRunDetail,
    ResearchRunExecutionTiming,
    ResearchRunKeyMetrics,
    ResearchRunList,
    ResearchRunProgress,
    ResearchRunResult,
    ResearchRunSummary,
    StartTrackingCommand,
    StrategyBacktestAdmissionCommand,
    StrategyBacktestResearchRunKeyMetrics,
    StrategyBacktestResearchRunResult,
)
from thesistrace.research_run.planning import (
    DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES,
    ResearchChunkCapacityError,
    plan_research_chunks,
)
from thesistrace.research_run.result import (
    STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
    ResearchResultError,
    enforce_result_bundle_budget,
    read_result_bundle,
    result_publication_payloads_from_staged,
)

ATTEMPT_LEASE_SECONDS = 15 * 60
ATTEMPT_HEARTBEAT_SECONDS = 30
INFRASTRUCTURE_FAILURE = "InfrastructureUnavailable"
RESOURCE_EXHAUSTED_FAILURE = "ResourceExhausted"
WORKER_LOST_FAILURE = "WorkerLost"
CHECKPOINT_INTEGRITY_FAILURE = "CheckpointIntegrityFailure"
CONTRACT_MISMATCH_FAILURE = "ContractMismatch"
CALCULATION_FAILURE = "CalculationFailure"
INFRASTRUCTURE_PUBLIC_REASON = "Research execution could not access required infrastructure."
RESOURCE_EXHAUSTED_PUBLIC_REASON = "Research execution exceeded its resource limit."
AUTOMATIC_RETRIES_PUBLIC_REASON = "Research execution could not complete after automatic retries."
PERMANENT_FAILURE_PUBLIC_REASON = "Research execution failed."
CHECKPOINT_INTEGRITY_PUBLIC_REASON = "Research execution checkpoint integrity validation failed."
CONTRACT_MISMATCH_PUBLIC_REASON = "Research execution contract does not match this runtime."
CALCULATION_PUBLIC_REASON = "Research calculation failed."
INSUFFICIENT_WARMUP_PUBLIC_REASON = (
    "Selected data does not contain the complete Calculation Warm-up."
)
SELECTED_DATA_INVALID_PUBLIC_REASON = "Current data cannot execute the requested Research Period."
Progress = Callable[[str, str], None]
CompileFormula = Callable[[str], CompiledAlpha]
CurrentDataset = Callable[[], DatasetAdmissionSnapshot | None]
TrackReferencesResult = Callable[[PostgresTransaction, str], bool]
ActivateTrack = Callable[
    [PostgresTransaction, TrackingOrigin],
    DailyTrackSummary,
]


class ResearchRunFenced(RuntimeError):
    pass


class ResearchCheckpointIntegrityError(RuntimeError):
    pass


class ResearchRunContractMismatch(RuntimeError):
    pass


class ResearchRunCancelConflict(RuntimeError):
    pass


class ResearchRunStartTrackingConflict(RuntimeError):
    pass


class ResearchRunResultUnavailable(RuntimeError):
    pass


class ResearchRunTrackingUnavailable(RuntimeError):
    pass


class ResearchRunTrackingTemporarilyUnavailable(RuntimeError):
    pass


class ResearchRunInsufficientWarmup(ValueError):
    pass


class ResearchRunInputInvalid(ValueError):
    pass


class ResearchRunAdmissionConflict(RuntimeError):
    pass


class ResearchRunOrganizationConflict(RuntimeError):
    pass


class ResearchRunDeleteConflict(RuntimeError):
    pass


class ResearchRunAdmissionRejected(ValueError):
    def __init__(self, issues: list[ResearchRunAdmissionIssue]) -> None:
        super().__init__("ResearchRun admission rejected")
        self.issues = issues


FIXED_STRATEGY_KIND = "long_only_top_n_equal_weight"
FIXED_INITIAL_CASH_CNY = "10000000"
FIXED_EXECUTION = "next_open_full_fill"
FIXED_COSTS = {
    "commission_rate_all_in": "0.0003",
    "commission_min_cny": "5",
    "stamp_duty_sell_rate": "0.0005",
    "transfer_fee_rate": "0.00001",
}
SEMANTIC_VERSIONS = {
    "factor": "factor-v1",
    "strategy": "strategy-v1",
    "kernel": "kernel-v4",
}


@dataclass(frozen=True)
class _ExecutionClaim:
    run_id: str
    attempt_id: str
    attempt_number: int
    previous_status: str
    fence: int
    generation_pin_id: str
    data_generation_id: str
    data_through_session: str
    immutable_input: ImmutableRunInput


@dataclass(frozen=True)
class _FailurePolicy:
    attempt_reason: str
    public_reason: str


@dataclass(frozen=True)
class _RecordedFailure:
    retry: bool
    attempt_number: int
    failure_code: str


@dataclass(frozen=True)
class _RecoveredCancellation:
    run_id: str
    attempt_id: str


@dataclass(frozen=True)
class _WorkerLossRecovery:
    run_id: str
    attempt_id: str
    attempt_number: int
    retry: bool


@dataclass(frozen=True)
class _ClaimResult:
    claim: _ExecutionClaim | None
    worker_loss: _WorkerLossRecovery | None = None


class ResearchRunService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        dataset_lifecycle: DatasetLifecycle | None = None,
        generation_store: MountedGenerationStore | None = None,
        publication: Publication | None = None,
        progress: Progress | None = None,
        lease_seconds: float = ATTEMPT_LEASE_SECONDS,
        heartbeat_seconds: float = ATTEMPT_HEARTBEAT_SECONDS,
        activate_track: ActivateTrack | None = None,
        compile_formula: CompileFormula | None = None,
        current_dataset: CurrentDataset | None = None,
        track_references_result: TrackReferencesResult | None = None,
        execution: SupervisedResearchExecutor | None = None,
        execution_memory_bytes: int = DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES,
        lifecycle_event: ExecutionEvent | None = None,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0:
            raise ValueError("ResearchRun lease and heartbeat intervals must be positive")
        self._database = database
        self._dataset_lifecycle = dataset_lifecycle
        self._generation_store = generation_store
        self._publication = publication
        self._progress = progress or (lambda _stage, _run_id: None)
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._activate_track = activate_track
        self._compile_formula = compile_formula
        self._current_dataset = current_dataset
        self._track_references_result = track_references_result
        self._execution = execution
        self._execution_memory_bytes = execution_memory_bytes
        self._lifecycle_event = non_blocking_operational_event_sink(
            lifecycle_event or (lambda _event: None),
            component="core_api",
        )

    @property
    def execution_memory_bytes(self) -> int:
        return self._execution_memory_bytes

    def admit(
        self,
        command: ResearchRunAdmissionCommand,
    ) -> ResearchRunSummary:
        if self._compile_formula is None or self._current_dataset is None:
            raise RuntimeError("ResearchRun admission dependencies are not configured")
        fingerprint = _admission_fingerprint(command)
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"research_runs.admit:{command.request_id}",),
            ).fetchone()
            receipt = _admission_receipt(transaction, command.request_id)
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise ResearchRunAdmissionConflict("ResearchRun request_id conflicts")
                return _summary(receipt)
        try:
            compiled = self._compile_formula(command.formula)
        except FormulaCompilationError as error:
            raise ResearchRunAdmissionRejected(
                [
                    ResearchRunAdmissionIssue(
                        code=diagnostic.code,
                        field="formula",
                        message=diagnostic.message,
                        range=diagnostic.range,
                        details=diagnostic.details,
                    )
                    for diagnostic in error.diagnostics
                ]
            ) from error
        snapshot = self._current_dataset()
        immutable_input = _admitted_input(
            command,
            compiled,
            snapshot,
            execution_memory_bytes=self._execution_memory_bytes,
        )
        run_id = f"run_{uuid4().hex[:20]}"
        submitted_name = (command.name or "").strip()
        name = submitted_name or f"Research {run_id[-8:].upper()}"
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"research_runs.admit:{command.request_id}",),
            ).fetchone()
            receipt = _admission_receipt(transaction, command.request_id)
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise ResearchRunAdmissionConflict("ResearchRun request_id conflicts")
                return _summary(receipt)
            folder = transaction.execute(
                "SELECT id FROM research_folders.folders WHERE id = %s FOR KEY SHARE",
                (command.folder_id,),
            ).fetchone()
            if folder is None:
                raise ResearchRunAdmissionRejected(
                    [
                        ResearchRunAdmissionIssue(
                            code="FOLDER_NOT_FOUND",
                            field="folder_id",
                            message="Research Folder does not exist",
                        )
                    ]
                )
            row = transaction.execute(
                """
                INSERT INTO research_runs.runs (
                    id, folder_id, name, requested_start_date,
                    requested_end_date, status, immutable_input
                ) VALUES (%s, %s, %s, %s, %s, 'queued', %s)
                RETURNING id, name, folder_id, status, requested_start_date,
                          requested_end_date, created_at, immutable_input, failure_reason
                """,
                (
                    run_id,
                    command.folder_id,
                    name,
                    immutable_input.requested_start_date,
                    immutable_input.requested_end_date,
                    Jsonb(immutable_input.canonical_value()),
                ),
            ).fetchone()
            transaction.execute(
                """
                INSERT INTO research_runs.admission_requests (
                    request_id, request_fingerprint, run_id
                ) VALUES (%s, %s, %s)
                """,
                (command.request_id, fingerprint, run_id),
            )
            transaction.execute(
                """
                INSERT INTO research_runs.progress (
                    run_id, phase,
                    completed_warmup_sessions, total_warmup_sessions,
                    completed_research_sessions, total_research_sessions,
                    committed_chunk_count
                ) VALUES (%s, 'queued', 0, %s, 0, %s, 0)
                """,
                (
                    run_id,
                    immutable_input.execution_plan.research_session_offset,
                    immutable_input.execution_plan.research_session_count,
                ),
            )
            if self._dataset_lifecycle is not None:
                self._dataset_lifecycle.retain_generation_in_transaction(
                    transaction,
                    retention_id=f"queued-research-run:{run_id}",
                    generation_manifest_sha256=(
                        immutable_input.data_admission.generation_manifest_sha256
                    ),
                    lease_seconds=self._lease_seconds,
                )
        assert row is not None
        return _summary(row)

    def process_next(
        self,
        *,
        on_claim: Callable[[str, str], None] | None = None,
        on_execution_event: ExecutionEvent | None = None,
    ) -> bool:
        self._require_execution_dependencies()
        emit_execution_event = on_execution_event or (lambda _event: None)
        emit = non_blocking_operational_event_sink(
            emit_execution_event,
            component="research_worker",
            worker_role="research",
        )
        recovered_cancellation = self._recover_cancelled_attempt()
        if recovered_cancellation is not None:
            emit(
                _research_event(
                    "research_run_cancelled",
                    run_id=recovered_cancellation.run_id,
                    attempt_id=recovered_cancellation.attempt_id,
                    status="cancelled",
                )
            )
            return True
        claim_result = self._claim_next()
        if claim_result.worker_loss is not None:
            recovery = claim_result.worker_loss
            level = "WARNING" if recovery.retry else "ERROR"
            emit(
                _research_event(
                    "research_attempt_failed",
                    level=level,
                    run_id=recovery.run_id,
                    attempt_id=recovery.attempt_id,
                    attempt_number=recovery.attempt_number,
                    status="failed",
                    failure_code=attempt_failure_code(WORKER_LOST_FAILURE)
                    or "UNCLASSIFIED_FAILURE",
                )
            )
            emit(
                _research_event(
                    "research_retry_scheduled" if recovery.retry else "research_run_failed",
                    level=level,
                    run_id=recovery.run_id,
                    attempt_id=recovery.attempt_id,
                    attempt_number=recovery.attempt_number,
                    status="running" if recovery.retry else "failed",
                    failure_code=attempt_failure_code(WORKER_LOST_FAILURE)
                    or "UNCLASSIFIED_FAILURE",
                )
            )
        claim = claim_result.claim
        if claim is None:
            return False
        if on_claim is not None:
            try:
                on_claim(claim.run_id, claim.attempt_id)
            except Exception:
                pass
        emit(
            _research_event(
                "research_attempt_started",
                run_id=claim.run_id,
                attempt_id=claim.attempt_id,
                attempt_number=claim.attempt_number,
                status="running",
            )
        )
        if claim.previous_status != "running":
            emit(
                _research_event(
                    "research_run_state_changed",
                    run_id=claim.run_id,
                    attempt_id=claim.attempt_id,
                    previous_status=claim.previous_status,
                    status="running",
                )
            )
        with self._maintain_claim(claim, emit):
            self._progress("claimed", claim.run_id)
            execution: SupervisedResearchExecution | None = None
            cancellation_pending = False
            execution_failure: Exception | None = None
            try:
                execution = self._execute(
                    claim,
                    emit=emit,
                )
                while True:
                    chunk = execution.chunk
                    if chunk.get("reused_checkpoint") is not True:
                        commit_started = monotonic()
                        self._commit_execution_chunk(claim, chunk)
                        emit(
                            {
                                "event": "research_execution_chunk_committed",
                                "resource_type": "ResearchRun",
                                "resource_id": claim.run_id,
                                "attempt_id": claim.attempt_id,
                                "research_kind": claim.immutable_input.research_kind,
                                "chunk_ordinal": int(chunk["ordinal"]),
                                "boundary_session": str(chunk["boundary_session"]),
                                "supervisor_commit_seconds": monotonic() - commit_started,
                            }
                        )
                        if _chunk_completes_phase(claim, chunk):
                            emit(
                                _research_event(
                                    "research_run_phase_completed",
                                    run_id=claim.run_id,
                                    attempt_id=claim.attempt_id,
                                    phase=str(chunk["phase"]),
                                )
                            )
                        emit(
                            _research_event(
                                "research_checkpoint_committed",
                                run_id=claim.run_id,
                                attempt_id=claim.attempt_id,
                                phase=str(chunk["phase"]),
                            )
                        )
                        self._progress("checkpoint", claim.run_id)
                    if chunk["final"] is True:
                        prepared, provenance, key_metrics = self._prepare_execution_result(
                            claim,
                            chunk,
                        )
                        self._progress("prepared", claim.run_id)
                        self._validate_current_execution(claim)
                        execution.acknowledge(
                            cancel_requested=lambda: self._cancellation_is_pending(claim)
                        )
                        self._publish_success(
                            claim,
                            prepared,
                            provenance,
                            key_metrics,
                        )
                        emit(
                            _research_event(
                                "research_result_published",
                                run_id=claim.run_id,
                                attempt_id=claim.attempt_id,
                                status="succeeded",
                            )
                        )
                        emit(
                            _research_event(
                                "research_run_succeeded",
                                run_id=claim.run_id,
                                attempt_id=claim.attempt_id,
                                status="succeeded",
                            )
                        )
                        self._progress("succeeded", claim.run_id)
                        break
                    execution.advance(cancel_requested=lambda: self._cancellation_is_pending(claim))
            except ResearchExecutionCancelled:
                cancellation_pending = True
            except ResearchRunFenced:
                cancellation_pending = self._cancellation_is_pending(claim)
                emit(
                    _research_event(
                        "research_attempt_fenced",
                        run_id=claim.run_id,
                        attempt_id=claim.attempt_id,
                        outcome="fenced",
                    )
                )
            except Exception as error:
                execution_failure = error
            finally:
                if execution is not None:
                    if cancellation_pending:
                        execution.cancel()
                    else:
                        execution.close()
            if execution_failure is not None:
                recorded_failure = self._record_failure(claim, execution_failure)
                cancellation_pending = cancellation_pending or self._cancellation_is_pending(claim)
                if recorded_failure is not None:
                    level = "WARNING" if recorded_failure.retry else "ERROR"
                    emit(
                        _research_event(
                            "research_attempt_failed",
                            level=level,
                            run_id=claim.run_id,
                            attempt_id=claim.attempt_id,
                            attempt_number=recorded_failure.attempt_number,
                            status="failed",
                            failure_code=recorded_failure.failure_code,
                        )
                    )
                    if recorded_failure.retry:
                        emit(
                            _research_event(
                                "research_retry_scheduled",
                                level="WARNING",
                                run_id=claim.run_id,
                                attempt_id=claim.attempt_id,
                                attempt_number=recorded_failure.attempt_number,
                                status="running",
                                failure_code=recorded_failure.failure_code,
                            )
                        )
                    else:
                        emit(
                            _research_event(
                                "research_run_failed",
                                level="ERROR",
                                run_id=claim.run_id,
                                attempt_id=claim.attempt_id,
                                attempt_number=recorded_failure.attempt_number,
                                status="failed",
                                failure_code=recorded_failure.failure_code,
                            )
                        )
            if cancellation_pending:
                if self._confirm_cancelled(claim):
                    emit(
                        _research_event(
                            "research_run_cancelled",
                            run_id=claim.run_id,
                            attempt_id=claim.attempt_id,
                            status="cancelled",
                        )
                    )
        return True

    def list(
        self,
        *,
        folder_id: str | None = None,
        research_kind: ResearchKind | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ResearchRunList:
        cursor_created_at, cursor_id = _decode_list_cursor(cursor)
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, name, folder_id, status, requested_start_date,
                       requested_end_date, created_at, immutable_input,
                       key_metrics, failure_reason
                FROM research_runs.runs
                WHERE (%s::text IS NULL OR folder_id = %s::text)
                  AND (%s::text IS NULL OR immutable_input->>'research_kind' = %s::text)
                  AND (
                    %s::timestamptz IS NULL
                    OR created_at < %s::timestamptz
                    OR (created_at = %s::timestamptz AND id > %s::text)
                  )
                ORDER BY created_at DESC, id
                LIMIT %s::integer
                """,
                (
                    folder_id,
                    folder_id,
                    research_kind,
                    research_kind,
                    cursor_created_at,
                    cursor_created_at,
                    cursor_created_at,
                    cursor_id,
                    limit + 1,
                ),
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        next_cursor = _encode_list_cursor(selected[-1]) if has_more else None
        return ResearchRunList(
            items=[_summary(row) for row in selected],
            next_cursor=next_cursor,
        )

    def get(self, run_id: str) -> ResearchRunSummary | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, name, folder_id, status, requested_start_date,
                       requested_end_date, created_at, immutable_input,
                       key_metrics, failure_reason
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        return None if row is None else _summary(row)

    def organize(
        self,
        run_id: str,
        command: OrganizeResearchRunCommand,
    ) -> ResearchRunSummary | None:
        with self._database.transaction() as transaction:
            if command.folder_id is not None:
                folder = transaction.execute(
                    """
                    SELECT id
                    FROM research_folders.folders
                    WHERE id = %s
                    FOR KEY SHARE
                    """,
                    (command.folder_id,),
                ).fetchone()
                if folder is None:
                    raise ResearchRunOrganizationConflict("Research Folder does not exist")
            row = transaction.execute(
                """
                UPDATE research_runs.runs
                SET name = CASE WHEN %s THEN %s ELSE name END,
                    folder_id = CASE WHEN %s THEN %s ELSE folder_id END,
                    updated_at = now()
                WHERE id = %s
                RETURNING id, name, folder_id, status, requested_start_date,
                          requested_end_date, created_at, immutable_input,
                          key_metrics, failure_reason
                """,
                (
                    command.name is not None,
                    command.name,
                    command.folder_id is not None,
                    command.folder_id,
                    run_id,
                ),
            ).fetchone()
        return None if row is None else _summary(row)

    def delete(self, run_id: str) -> bool:
        if self._publication is None:
            raise RuntimeError("ResearchRun deletion is not configured")
        with self._database.transaction() as transaction:
            lock_publication_mutation(transaction)
            row = transaction.execute(
                """
                SELECT status, result_manifest_sha256
                FROM research_runs.runs
                WHERE id = %s
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] not in {"succeeded", "failed", "cancelled"}:
                raise ResearchRunDeleteConflict("ResearchRun deletion requires terminal status")
            manifest_sha256 = row.get("result_manifest_sha256")
            transaction.execute(
                "DELETE FROM research_runs.start_tracking_receipts WHERE seed_run_id = %s",
                (run_id,),
            )
            transaction.execute(
                "DELETE FROM research_runs.cancel_receipts WHERE run_id = %s",
                (run_id,),
            )
            transaction.execute(
                "DELETE FROM research_runs.admission_requests WHERE run_id = %s",
                (run_id,),
            )
            transaction.execute(
                "DELETE FROM research_runs.execution_checkpoints WHERE run_id = %s",
                (run_id,),
            )
            transaction.execute(
                "DELETE FROM research_runs.attempts WHERE run_id = %s",
                (run_id,),
            )
            transaction.execute(
                "DELETE FROM research_runs.runs WHERE id = %s",
                (run_id,),
            )
            if isinstance(manifest_sha256, str):
                still_referenced = research_result_manifest_is_referenced(
                    transaction,
                    manifest_sha256,
                ) or (
                    self._track_references_result is not None
                    and self._track_references_result(transaction, manifest_sha256)
                )
                self._publication.release_manifest_in_transaction(
                    transaction,
                    manifest_sha256,
                    still_referenced=still_referenced,
                )
        _collect_publication_deletions(
            self._publication,
            lifecycle_event=self._lifecycle_event,
            run_id=run_id,
        )
        return True

    def cancel(
        self,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunSummary | None:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("ResearchRun Cancel request_id is required")
        fingerprint = _cancel_fingerprint(run_id)
        cancelled_attempt_id: str | None = None
        cancelled_after_commit = False
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

            self._lock_result_staging(transaction, run_id)
            row = transaction.execute(
                """
                SELECT id, name, folder_id, status, requested_start_date,
                       requested_end_date, created_at, immutable_input,
                       failure_reason
                FROM research_runs.runs
                WHERE id = %s
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] == "running":
                cancelling_attempt = transaction.execute(
                    """
                    UPDATE research_runs.attempts
                    SET status = 'cancelling', heartbeat_at = now(),
                        failure_reason = 'UserCancelled'
                    WHERE run_id = %s AND status = 'running'
                    RETURNING id
                    """,
                    (run_id,),
                ).fetchone()
                if cancelling_attempt is None:
                    updated = transaction.execute(
                        """
                        UPDATE research_runs.runs
                        SET status = 'cancelled',
                            execution_fence = execution_fence + 1,
                            failure_reason = NULL, updated_at = now()
                        WHERE id = %s AND status = 'running'
                        RETURNING id, name, folder_id, status,
                                  requested_start_date, requested_end_date,
                                  created_at, immutable_input, failure_reason
                        """,
                        (run_id,),
                    ).fetchone()
                    if updated is not None and self._dataset_lifecycle is not None:
                        self._dataset_lifecycle.release_retention_in_transaction(
                            transaction,
                            retention_id=f"queued-research-run:{run_id}",
                        )
                    cancelled_after_commit = updated is not None
                else:
                    cancelled_attempt_id = str(cancelling_attempt["id"])
                    updated = transaction.execute(
                        """
                        UPDATE research_runs.runs
                        SET status = 'cancelling',
                            execution_fence = execution_fence + 1,
                            failure_reason = NULL, updated_at = now()
                        WHERE id = %s AND status = 'running'
                        RETURNING id, name, folder_id, status,
                                  requested_start_date, requested_end_date,
                                  created_at, immutable_input, failure_reason
                        """,
                        (run_id,),
                    ).fetchone()
                if updated is None:
                    raise ResearchRunFenced
                row = updated
            elif row["status"] == "queued":
                updated = transaction.execute(
                    """
                    UPDATE research_runs.runs
                    SET status = 'cancelled',
                        execution_fence = execution_fence + 1,
                        failure_reason = NULL, updated_at = now()
                    WHERE id = %s AND status = 'queued'
                    RETURNING id, name, folder_id, status,
                              requested_start_date, requested_end_date,
                              created_at, immutable_input, failure_reason
                    """,
                    (run_id,),
                ).fetchone()
                if updated is None:
                    raise ResearchRunFenced
                row = updated
                cancelled_after_commit = True
                if self._dataset_lifecycle is not None:
                    self._dataset_lifecycle.release_retention_in_transaction(
                        transaction,
                        retention_id=f"queued-research-run:{run_id}",
                    )
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
        if cancelled_after_commit:
            event_context: dict[str, object] = {
                "run_id": run_id,
                "status": "cancelled",
            }
            if cancelled_attempt_id is not None:
                event_context["attempt_id"] = cancelled_attempt_id
            self._lifecycle_event(
                {
                    "event": "research_run_cancelled",
                    **event_context,
                }
            )
        return outcome

    def _cancellation_is_pending(self, claim: _ExecutionClaim) -> bool:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.status AS run_status, attempt.status AS attempt_status
                FROM research_runs.runs AS run
                JOIN research_runs.attempts AS attempt ON attempt.run_id = run.id
                WHERE run.id = %s AND attempt.id = %s AND attempt.fence = %s
                """,
                (claim.run_id, claim.attempt_id, claim.fence),
            ).fetchone()
        return row == {"run_status": "cancelling", "attempt_status": "cancelling"}

    def _confirm_cancelled(self, claim: _ExecutionClaim) -> bool:
        assert self._dataset_lifecycle is not None
        with self._database.transaction() as transaction:
            run = transaction.execute(
                """
                SELECT status
                FROM research_runs.runs
                WHERE id = %s
                FOR UPDATE
                """,
                (claim.run_id,),
            ).fetchone()
            if run != {"status": "cancelling"}:
                return False
            attempt = transaction.execute(
                """
                UPDATE research_runs.attempts
                SET status = 'cancelled', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now()
                WHERE id = %s AND run_id = %s AND fence = %s
                  AND status = 'cancelling'
                """,
                (claim.attempt_id, claim.run_id, claim.fence),
            )
            if attempt.rowcount != 1:
                return False
            transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = 'cancelled', updated_at = now()
                WHERE id = %s AND status = 'cancelling'
                """,
                (claim.run_id,),
            )
            self._release_execution_checkpoints(transaction, claim.run_id)
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )
        return True

    def _recover_cancelled_attempt(self) -> _RecoveredCancellation | None:
        assert self._dataset_lifecycle is not None
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.id AS run_id, attempt.id AS attempt_id,
                       attempt.generation_pin_id
                FROM research_runs.runs AS run
                JOIN research_runs.attempts AS attempt ON attempt.run_id = run.id
                WHERE run.status = 'cancelling'
                  AND attempt.status = 'cancelling'
                  AND attempt.lease_expires_at <= now()
                ORDER BY run.created_at, run.id
                FOR UPDATE OF run, attempt SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            transaction.execute(
                """
                UPDATE research_runs.attempts
                SET status = 'cancelled', heartbeat_at = now(),
                    lease_expires_at = now(), finished_at = now()
                WHERE id = %s AND status = 'cancelling'
                """,
                (row["attempt_id"],),
            )
            transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = 'cancelled', updated_at = now()
                WHERE id = %s AND status = 'cancelling'
                """,
                (row["run_id"],),
            )
            self._release_execution_checkpoints(transaction, str(row["run_id"]))
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                str(row["generation_pin_id"]),
                owner_id=str(row["attempt_id"]),
            )
        return _RecoveredCancellation(
            run_id=str(row["run_id"]),
            attempt_id=str(row["attempt_id"]),
        )

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
                lock_publication_mutation(transaction)
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
                    SELECT id, name, folder_id, status,
                           requested_start_date, requested_end_date, created_at,
                           immutable_input,
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
                immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
                if immutable_input.research_kind != "strategy_backtest":
                    raise ResearchRunTrackingUnavailable(
                        "Start Tracking requires a Strategy Backtest Result"
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
            raise ResearchRunTrackingTemporarilyUnavailable(
                "Start Tracking is temporarily unavailable"
            ) from error

    def get_detail(self, run_id: str) -> ResearchRunDetail | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.id, run.name, run.folder_id, run.status,
                       run.requested_start_date, run.requested_end_date,
                       run.created_at, run.immutable_input,
                       run.result_manifest_sha256, run.result_provenance,
                       run.key_metrics, run.failure_reason,
                       progress.phase AS progress_phase,
                       progress.completed_warmup_sessions,
                       progress.total_warmup_sessions,
                       progress.completed_research_sessions,
                       progress.total_research_sessions,
                       progress.committed_chunk_count,
                       progress.last_completed_warmup_session,
                       progress.last_completed_research_session,
                       progress.remaining_duration_estimate_seconds,
                       timing.execution_started_at,
                       timing.execution_finished_at,
                       CURRENT_TIMESTAMP AS execution_observed_at
                FROM research_runs.runs AS run
                JOIN research_runs.progress AS progress ON progress.run_id = run.id
                LEFT JOIN LATERAL (
                    SELECT min(attempt.started_at) AS execution_started_at,
                           max(attempt.finished_at) AS execution_finished_at
                    FROM research_runs.attempts AS attempt
                    WHERE attempt.run_id = run.id
                ) AS timing ON true
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        summary = _summary(row)
        authorable_input = _authorable_input(row)
        if summary.status != "succeeded":
            return ResearchRunDetail(
                **summary.model_dump(),
                input=authorable_input,
                progress=_research_progress(row),
                execution_timing=_research_execution_timing(row, summary.status),
            )
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
            stored_result = read_result_bundle(bundle, research_kind=summary.research_kind)
            result = _public_result(
                stored_result,
                dict(provenance),
                research_kind=summary.research_kind,
            )
        except Exception as error:
            raise ResearchRunResultUnavailable from error
        return ResearchRunDetail(
            **summary.model_dump(),
            input=authorable_input,
            progress=_research_progress(row),
            execution_timing=_research_execution_timing(row, summary.status),
            result=result,
        )

    def _tracking_origin(
        self,
        transaction: PostgresTransaction,
        row: dict[str, object],
    ) -> TrackingOrigin:
        if self._publication is None:
            raise ResearchRunTrackingUnavailable
        immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
        if immutable_input.research_kind != "strategy_backtest":
            raise ResearchRunTrackingUnavailable
        try:
            require_current_numeric_contract(immutable_input.numeric_execution_contract)
        except NumericContractError as error:
            raise ResearchRunTrackingUnavailable from error
        manifest_sha256 = row.get("result_manifest_sha256")
        provenance = row.get("result_provenance")
        if not isinstance(manifest_sha256, str) or not isinstance(provenance, Mapping):
            raise ResearchRunTrackingUnavailable
        selected_provenance = dict(provenance)
        expected_digest = hashlib.sha256(
            canonical_json_bytes(immutable_input.canonical_value())
        ).hexdigest()
        if (
            selected_provenance.get("research_run_id") != row["id"]
            or selected_provenance.get("immutable_input_sha256") != expected_digest
        ):
            raise ResearchRunTrackingUnavailable
        data_generation_id = selected_provenance.get("data_generation_id")
        data_through_session = selected_provenance.get("data_through_session")
        if not isinstance(data_generation_id, str) or not isinstance(
            data_through_session,
            str,
        ):
            raise ResearchRunTrackingUnavailable
        bundle = self._publication.read_in_transaction(
            transaction,
            PublishedRef(
                manifest_sha256=manifest_sha256,
                kind="research.result",
                provenance=selected_provenance,
            ),
        )
        stored_result = read_result_bundle(bundle, research_kind=immutable_input.research_kind)
        _public_result(
            stored_result,
            selected_provenance,
            research_kind=immutable_input.research_kind,
        )
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
            immutable_input=immutable_input.canonical_value(),
            seed_data_generation_id=data_generation_id,
            seed_data_through_session=data_through_session,
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

    def _require_execution_dependencies(self) -> None:
        if self._dataset_lifecycle is None or self._publication is None or self._execution is None:
            raise RuntimeError("ResearchRun execution dependencies are not configured")

    def _claim_next(self) -> _ClaimResult:
        assert self._dataset_lifecycle is not None
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.id, run.status, run.immutable_input,
                       run.execution_fence,
                       attempt.id AS latest_attempt_id,
                       attempt.ordinal AS latest_attempt_ordinal,
                       attempt.status AS latest_attempt_status,
                       attempt.generation_pin_id AS latest_generation_pin_id
                FROM research_runs.runs AS run
                LEFT JOIN LATERAL (
                    SELECT id, ordinal, status, lease_expires_at, failure_reason,
                           generation_pin_id
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
                (list(RETRYABLE_ATTEMPT_FAILURES),),
            ).fetchone()
            if row is None:
                return _ClaimResult(claim=None)
            run_id = str(row["id"])
            worker_loss: _WorkerLossRecovery | None = None
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
                    return _ClaimResult(claim=None)
                self._dataset_lifecycle.release_pin_in_transaction(
                    transaction,
                    str(row["latest_generation_pin_id"]),
                    owner_id=str(row["latest_attempt_id"]),
                )
                attempt_number = int(row["latest_attempt_ordinal"])
                retry = attempt_retry_eligible(WORKER_LOST_FAILURE, attempt_number)
                worker_loss = _WorkerLossRecovery(
                    run_id=run_id,
                    attempt_id=str(row["latest_attempt_id"]),
                    attempt_number=attempt_number,
                    retry=retry,
                )
                if not retry:
                    transaction.execute(
                        """
                        UPDATE research_runs.runs
                        SET status = 'failed',
                            failure_reason = %s, updated_at = now()
                        WHERE id = %s AND status = 'running'
                          AND execution_fence = %s
                        """,
                        (
                            AUTOMATIC_RETRIES_PUBLIC_REASON,
                            run_id,
                            row["execution_fence"],
                        ),
                    )
                    self._release_execution_checkpoints(transaction, run_id)
                    return _ClaimResult(claim=None, worker_loss=worker_loss)
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
            immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
            pinned = self._dataset_lifecycle.pin_generation_in_transaction(
                transaction,
                generation_manifest_sha256=(
                    immutable_input.data_admission.generation_manifest_sha256
                ),
                owner_kind="research_run_attempt",
                owner_id=attempt_id,
                lease_seconds=self._lease_seconds,
            )
            pin = pinned.pin
            generation = pinned.descriptor
            if not _generation_matches_frozen_facts(generation, immutable_input):
                self._dataset_lifecycle.release_pin_in_transaction(
                    transaction,
                    pin.id,
                    owner_id=attempt_id,
                )
                self._dataset_lifecycle.release_retention_in_transaction(
                    transaction,
                    retention_id=f"queued-research-run:{run_id}",
                )
                raise ResearchRunInputInvalid("selected Data Generation facts changed")
            self._dataset_lifecycle.release_retention_in_transaction(
                transaction,
                retention_id=f"queued-research-run:{run_id}",
            )
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
                    id, run_id, ordinal, fence, generation_pin_id,
                    data_generation_id, data_through_session,
                    status, lease_expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 'running',
                    now() + make_interval(secs => %s)
                )
                """,
                (
                    attempt_id,
                    run_id,
                    int(ordinal_row["ordinal"]),
                    fence,
                    pin.id,
                    generation.manifest_sha256,
                    generation.data_through_session,
                    self._lease_seconds,
                ),
            )
        return _ClaimResult(
            claim=_ExecutionClaim(
                run_id=run_id,
                attempt_id=attempt_id,
                attempt_number=int(ordinal_row["ordinal"]),
                previous_status=str(row["status"]),
                fence=fence,
                generation_pin_id=pin.id,
                data_generation_id=generation.manifest_sha256,
                data_through_session=generation.data_through_session,
                immutable_input=immutable_input,
            ),
            worker_loss=worker_loss,
        )

    @contextmanager
    def _maintain_claim(
        self,
        claim: _ExecutionClaim,
        emit: ExecutionEvent,
    ) -> Iterator[None]:
        stopped = Event()
        heartbeat = Thread(
            target=self._heartbeat_claim,
            args=(claim, stopped, emit),
            name=f"research-run-heartbeat-{claim.run_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat.join(timeout=5)

    def _heartbeat_claim(
        self,
        claim: _ExecutionClaim,
        stopped: Event,
        emit: ExecutionEvent,
    ) -> None:
        assert self._dataset_lifecycle is not None
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
                    if renewed.rowcount == 1:
                        self._dataset_lifecycle.heartbeat_pin_in_transaction(
                            transaction,
                            claim.generation_pin_id,
                            owner_id=claim.attempt_id,
                            lease_seconds=self._lease_seconds,
                        )
            except Exception as error:
                emit(
                    _research_event(
                        "research_attempt_heartbeat_failed",
                        level="WARNING",
                        run_id=claim.run_id,
                        attempt_id=claim.attempt_id,
                        failure_code="INFRASTRUCTURE_UNAVAILABLE",
                        exception_type=type(error).__name__,
                    )
                )
                return
            if renewed.rowcount != 1:
                return

    def _execute(
        self,
        claim: _ExecutionClaim,
        *,
        emit: ExecutionEvent,
    ) -> SupervisedResearchExecution:
        assert self._execution is not None
        immutable_input = claim.immutable_input
        self._require_current_execution_contracts(immutable_input)
        resume_from = self._validated_resume_checkpoint(claim)
        try:
            return self._execution.execute(
                ResearchExecutionRequest(
                    run_id=claim.run_id,
                    attempt_id=claim.attempt_id,
                    data_generation_id=claim.data_generation_id,
                    immutable_input=immutable_input,
                    resume_from=resume_from,
                ),
                emit=emit,
                cancel_requested=lambda: self._cancellation_is_pending(claim),
            )
        except ResearchExecutionCancelled:
            raise
        except ResearchExecutionInsufficientWarmup as error:
            raise ResearchRunInsufficientWarmup(str(error)) from error
        except ResearchExecutionInputInvalid as error:
            raise ResearchRunInputInvalid(
                "selected Data Generation cannot resolve Formula"
            ) from error

    def _require_current_execution_contracts(
        self,
        immutable_input: ImmutableRunInput,
    ) -> None:
        try:
            require_current_numeric_contract(immutable_input.numeric_execution_contract)
            compiled = alpha_language.compile(immutable_input.formula_source)
        except (NumericContractError, FormulaCompilationError) as error:
            raise ResearchRunContractMismatch(
                "frozen Research execution contract is obsolete"
            ) from error
        current_bindings = {
            field_id: identifier
            for identifier, field_id in compiled.field_ids_by_identifier.items()
        }
        admission = immutable_input.alpha_admission
        strategy = immutable_input.strategy
        common_contract_mismatch = (
            immutable_input.semantic_versions != SEMANTIC_VERSIONS
            or compiled.expression != immutable_input.alpha_expression
            or current_bindings != immutable_input.field_bindings
            or compiled.effective_lookback != admission.effective_lookback
            or compiled.node_count != admission.node_count
            or compiled.depth != admission.depth
            or compiled.estimated_work != admission.formula_work
        )
        strategy_contract_mismatch = immutable_input.research_kind == "strategy_backtest" and (
            strategy is None
            or strategy.get("kind") != FIXED_STRATEGY_KIND
            or strategy.get("initial_cash_cny") != FIXED_INITIAL_CASH_CNY
            or strategy.get("execution") != FIXED_EXECUTION
            or immutable_input.costs != FIXED_COSTS
            or immutable_input.risk_free_rate != "0"
        )
        if common_contract_mismatch or strategy_contract_mismatch:
            raise ResearchRunContractMismatch("frozen Research execution contract is obsolete")

    def _validated_resume_checkpoint(
        self,
        claim: _ExecutionClaim,
    ) -> ResearchExecutionResume | None:
        assert self._publication is not None
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT checkpoint.*, attempt.fence AS creator_fence,
                       attempt.data_generation_id
                FROM research_runs.execution_checkpoints AS checkpoint
                JOIN research_runs.attempts AS attempt
                  ON attempt.id = checkpoint.attempt_id
                WHERE checkpoint.run_id = %s
                ORDER BY checkpoint.ordinal
                """,
                (claim.run_id,),
            ).fetchall()
            progress = transaction.execute(
                """
                SELECT completed_warmup_sessions, completed_research_sessions,
                       committed_chunk_count, last_completed_warmup_session,
                       last_completed_research_session
                FROM research_runs.progress
                WHERE run_id = %s
                """,
                (claim.run_id,),
            ).fetchone()
        if not rows:
            return None
        try:
            prior_chain: str | None = None
            continuation: Mapping[str, object] | None = None
            final_values: Mapping[str, object] | None = None
            completed_warmup = 0
            completed_research = 0
            for expected_ordinal, row in enumerate(rows, start=1):
                plan_chunk = claim.immutable_input.execution_plan.chunks[expected_ordinal - 1]
                completed_warmup += plan_chunk.warmup_session_count
                completed_research += plan_chunk.research_session_count
                observation_value = row["observation_payload"]
                final_values_value = row["final_values_payload"]
                binding = _checkpoint_binding(
                    immutable_input=claim.immutable_input,
                    run_id=claim.run_id,
                    creator_attempt_id=str(row["attempt_id"]),
                    creator_fence=int(row["creator_fence"]),
                    data_generation_id=str(row["data_generation_id"]),
                    ordinal=int(row["ordinal"]),
                    boundary_session=row["boundary_session"].isoformat(),
                    phase=str(row["phase"]),
                    completed_warmup_sessions=int(row["completed_warmup_sessions"]),
                    completed_research_sessions=int(row["completed_research_sessions"]),
                    continuation_payload=dict(row["continuation_payload"]),
                    observation_payload=(
                        None if observation_value is None else dict(observation_value)
                    ),
                    final_values_payload=(
                        None if final_values_value is None else dict(final_values_value)
                    ),
                    prior_chain_sha256=prior_chain,
                )
                chain_sha256 = hashlib.sha256(canonical_json_bytes(binding)).hexdigest()
                is_final = expected_ordinal == len(claim.immutable_input.execution_plan.chunks)
                expected_phase = "research" if plan_chunk.research_session_count else "warmup"
                expected_observation_count = (
                    plan_chunk.research_session_count
                    if claim.immutable_input.research_kind == "strategy_backtest"
                    else 0
                )
                if (
                    int(row["ordinal"]) != expected_ordinal
                    or str(row["chain_sha256"]) != chain_sha256
                    or str(row["data_generation_id"]) != claim.data_generation_id
                    or row["boundary_session"] != plan_chunk.last_session
                    or str(row["phase"]) != expected_phase
                    or int(row["completed_warmup_sessions"]) != completed_warmup
                    or int(row["completed_research_sessions"]) != completed_research
                    or int(row["observation_row_count"]) != expected_observation_count
                    or (final_values_value is not None) != is_final
                ):
                    raise ResearchCheckpointIntegrityError
                bundle = self._publication.read(
                    PublishedRef(
                        manifest_sha256=str(row["checkpoint_manifest_sha256"]),
                        kind="research.execution-checkpoint",
                        provenance=binding,
                    )
                )
                expected_payload_names = {"continuation"}
                if observation_value is not None:
                    expected_payload_names.add("strategy_daily_observations")
                if final_values_value is not None:
                    expected_payload_names.add("final_values")
                if set(bundle.payloads) != expected_payload_names:
                    raise ResearchCheckpointIntegrityError
                continuation = _checkpoint_json_payload(
                    bundle.payloads["continuation"],
                    subject="continuation",
                )
                try:
                    continuation = validated_research_continuation(
                        continuation,
                        research_kind=claim.immutable_input.research_kind,
                    )
                except ValueError as error:
                    raise ResearchCheckpointIntegrityError from error
                final_values = (
                    _checkpoint_json_payload(
                        bundle.payloads["final_values"],
                        subject="final values",
                    )
                    if final_values_value is not None
                    else None
                )
                observation = bundle.payloads.get("strategy_daily_observations")
                if observation is not None and (
                    observation.media_type != "application/vnd.apache.parquet"
                    or observation.serialization
                    != {
                        "format": "canonical-parquet",
                        "writer_contract": (STRATEGY_DAILY_OBSERVATIONS_CONTRACT.descriptor()),
                    }
                ):
                    raise ResearchCheckpointIntegrityError
                prior_chain = chain_sha256
            latest = rows[-1]
            if (
                continuation is None
                or progress is None
                or progress
                != {
                    "completed_warmup_sessions": completed_warmup,
                    "completed_research_sessions": completed_research,
                    "committed_chunk_count": len(rows),
                    "last_completed_warmup_session": (
                        None
                        if completed_warmup == 0
                        else claim.immutable_input.execution_plan.calculation_sessions[
                            completed_warmup - 1
                        ]
                    ),
                    "last_completed_research_session": (
                        None if completed_research == 0 else latest["boundary_session"]
                    ),
                }
            ):
                raise ResearchCheckpointIntegrityError
            return ResearchExecutionResume(
                completed_chunk_ordinal=len(rows),
                boundary_session=latest["boundary_session"].isoformat(),
                completed_warmup_sessions=completed_warmup,
                completed_research_sessions=completed_research,
                continuation=dict(continuation),
                final_values=None if final_values is None else dict(final_values),
            )
        except PublicationUnavailableError:
            raise
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            PublicationNotFoundError,
            PublicationVerificationError,
            ResearchCheckpointIntegrityError,
        ) as error:
            raise ResearchCheckpointIntegrityError(
                "Research execution Checkpoint chain is invalid"
            ) from error

    def _prepare_execution_result(
        self,
        claim: _ExecutionClaim,
        chunk: Mapping[str, object],
    ) -> tuple[PreparedPublication, dict[str, object], ResearchRunKeyMetrics]:
        assert self._publication is not None
        final_values = chunk.get("final_values")
        if not isinstance(final_values, Mapping):
            raise ResearchResultError("Final Research Chunk has no Result values")
        key_metrics = _result_key_metrics(
            final_values,
            claim.immutable_input.research_kind,
        )
        provenance = _result_provenance(claim)
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT observation_payload, observation_row_count,
                       observation_first_session, observation_last_session
                FROM research_runs.execution_checkpoints
                WHERE run_id = %s AND observation_row_count > 0
                ORDER BY ordinal
                """,
                (claim.run_id,),
            ).fetchall()
            progress = transaction.execute(
                """
                SELECT completed_research_sessions
                FROM research_runs.progress
                WHERE run_id = %s
                """,
                (claim.run_id,),
            ).fetchone()
        partitions = [
            (
                _staged_payload(row["observation_payload"]),
                int(row["observation_row_count"]),
                row["observation_first_session"].isoformat(),
                row["observation_last_session"].isoformat(),
            )
            for row in rows
        ]
        prepared = self._publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads_from_staged(
                final_values,
                partitions,
                research_kind=claim.immutable_input.research_kind,
            ),
            provenance=provenance,
            staging_authority=lambda: self._authorize_result_staging(claim),
        )
        if progress is None:
            raise ResearchResultError("Research Progress is missing")
        enforce_result_bundle_budget(
            prepared.exact_bytes,
            int(progress["completed_research_sessions"]),
        )
        return prepared, provenance, key_metrics

    def _commit_execution_chunk(
        self,
        claim: _ExecutionClaim,
        chunk: Mapping[str, object],
    ) -> None:
        assert self._publication is not None
        ordinal = int(chunk["ordinal"])
        boundary_session = str(chunk["boundary_session"])
        phase = str(chunk["phase"])
        completed_warmup = int(chunk["completed_warmup_sessions"])
        completed_research = int(chunk["completed_research_sessions"])
        continuation = chunk.get("continuation")
        observations = chunk.get("strategy_daily_observations")
        final_values = chunk.get("final_values")
        try:
            plan_chunk = claim.immutable_input.execution_plan.chunks[ordinal - 1]
        except IndexError as error:
            raise ResearchResultError("Research Chunk ordinal is invalid") from error
        expected_warmup = sum(
            item.warmup_session_count
            for item in claim.immutable_input.execution_plan.chunks[:ordinal]
        )
        expected_research = sum(
            item.research_session_count
            for item in claim.immutable_input.execution_plan.chunks[:ordinal]
        )
        expected_observation_count = (
            plan_chunk.research_session_count
            if claim.immutable_input.research_kind == "strategy_backtest"
            else 0
        )
        if (
            ordinal < 1
            or phase not in {"warmup", "research"}
            or not isinstance(continuation, Mapping)
            or not isinstance(observations, list)
            or any(not isinstance(value, Mapping) for value in observations)
            or ((chunk.get("final") is True) != isinstance(final_values, Mapping))
            or boundary_session != plan_chunk.last_session.isoformat()
            or phase != ("research" if plan_chunk.research_session_count else "warmup")
            or completed_warmup != expected_warmup
            or completed_research != expected_research
            or len(observations) != expected_observation_count
        ):
            raise ResearchResultError("Research Chunk boundary is invalid")
        try:
            continuation = validated_research_continuation(
                continuation,
                research_kind=claim.immutable_input.research_kind,
            )
        except ValueError as error:
            raise ResearchResultError("Research Chunk continuation is invalid") from error
        continuation_payload = self._publication.stage(
            JsonPayload(continuation),
            staging_authority=lambda: self._authorize_result_staging(claim),
        )
        observation_payload = (
            self._publication.stage(
                ParquetRowsPayload(
                    rows=tuple(dict(value) for value in observations),
                    contract=STRATEGY_DAILY_OBSERVATIONS_CONTRACT,
                ),
                staging_authority=lambda: self._authorize_result_staging(claim),
            )
            if observations
            else None
        )
        final_values_payload = (
            self._publication.stage(
                JsonPayload(dict(final_values)),
                staging_authority=lambda: self._authorize_result_staging(claim),
            )
            if isinstance(final_values, Mapping)
            else None
        )
        with self._database.transaction() as transaction:
            self._validate_current_execution_in_transaction(transaction, claim)
            prior = transaction.execute(
                """
                SELECT ordinal, chain_sha256
                FROM research_runs.execution_checkpoints
                WHERE run_id = %s
                ORDER BY ordinal DESC
                LIMIT 1
                """,
                (claim.run_id,),
            ).fetchone()
        expected_prior_ordinal = None if prior is None else int(prior["ordinal"])
        expected_prior_chain = None if prior is None else str(prior["chain_sha256"])
        if ordinal != (1 if expected_prior_ordinal is None else expected_prior_ordinal + 1):
            raise ResearchRunFenced
        continuation_value = _staged_payload_value(continuation_payload)
        observation_value = (
            _staged_payload_value(observation_payload) if observation_payload is not None else None
        )
        final_values_value = (
            _staged_payload_value(final_values_payload)
            if final_values_payload is not None
            else None
        )
        checkpoint_identity = _checkpoint_binding(
            immutable_input=claim.immutable_input,
            run_id=claim.run_id,
            creator_attempt_id=claim.attempt_id,
            creator_fence=claim.fence,
            data_generation_id=claim.data_generation_id,
            ordinal=ordinal,
            boundary_session=boundary_session,
            phase=phase,
            completed_warmup_sessions=completed_warmup,
            completed_research_sessions=completed_research,
            continuation_payload=continuation_value,
            observation_payload=observation_value,
            final_values_payload=final_values_value,
            prior_chain_sha256=expected_prior_chain,
        )
        chain_sha256 = hashlib.sha256(canonical_json_bytes(checkpoint_identity)).hexdigest()
        checkpoint_prepared = self._publication.prepare(
            kind="research.execution-checkpoint",
            payloads={
                "continuation": continuation_payload,
                **(
                    {"strategy_daily_observations": observation_payload}
                    if observation_payload is not None
                    else {}
                ),
                **(
                    {"final_values": final_values_payload}
                    if final_values_payload is not None
                    else {}
                ),
            },
            provenance=checkpoint_identity,
            staging_authority=lambda: self._authorize_result_staging(claim),
        )
        with self._database.transaction() as transaction:
            self._validate_current_execution_in_transaction(transaction, claim)
            prior = transaction.execute(
                """
                SELECT ordinal, chain_sha256
                FROM research_runs.execution_checkpoints
                WHERE run_id = %s
                ORDER BY ordinal DESC
                LIMIT 1
                FOR UPDATE
                """,
                (claim.run_id,),
            ).fetchone()
            current_prior_ordinal = None if prior is None else int(prior["ordinal"])
            current_prior_chain = None if prior is None else str(prior["chain_sha256"])
            if (
                current_prior_ordinal != expected_prior_ordinal
                or current_prior_chain != expected_prior_chain
            ):
                raise ResearchRunFenced
            checkpoint_publication = self._publication.record(
                transaction,
                checkpoint_prepared,
            )
            transaction.execute(
                """
                INSERT INTO research_runs.execution_checkpoints (
                    id, run_id, attempt_id, ordinal, boundary_session, phase,
                    completed_warmup_sessions, completed_research_sessions,
                    continuation_payload, observation_payload, final_values_payload,
                    observation_row_count, observation_first_session,
                    observation_last_session, checkpoint_manifest_sha256,
                    chain_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"checkpoint_{uuid4().hex[:20]}",
                    claim.run_id,
                    claim.attempt_id,
                    ordinal,
                    boundary_session,
                    phase,
                    completed_warmup,
                    completed_research,
                    Jsonb(continuation_value),
                    Jsonb(observation_value) if observation_value is not None else None,
                    Jsonb(final_values_value) if final_values_value is not None else None,
                    len(observations),
                    observations[0]["session"] if observations else None,
                    observations[-1]["session"] if observations else None,
                    checkpoint_publication.manifest_sha256,
                    chain_sha256,
                ),
            )
            remaining_estimate: int | None = None
            if ordinal >= 2:
                timing = transaction.execute(
                    """
                    SELECT extract(epoch FROM (now() - min(created_at))) AS elapsed_seconds
                    FROM research_runs.execution_checkpoints
                    WHERE run_id = %s
                    """,
                    (claim.run_id,),
                ).fetchone()
                remaining_chunks = len(claim.immutable_input.execution_plan.chunks) - ordinal
                if timing is not None and remaining_chunks > 0:
                    elapsed_seconds = float(timing["elapsed_seconds"] or 0)
                    remaining_estimate = max(
                        1,
                        math.ceil(elapsed_seconds / (ordinal - 1) * remaining_chunks),
                    )
            last_warmup_session = (
                claim.immutable_input.execution_plan.calculation_sessions[completed_warmup - 1]
                if completed_warmup > 0
                else None
            )
            transaction.execute(
                """
                UPDATE research_runs.progress
                SET phase = %s,
                    completed_warmup_sessions = %s,
                    completed_research_sessions = %s,
                    committed_chunk_count = %s,
                    last_completed_warmup_session = CASE
                        WHEN %s > 0 THEN %s ELSE last_completed_warmup_session END,
                    last_completed_research_session = CASE
                        WHEN %s > 0 THEN %s ELSE last_completed_research_session END,
                    remaining_duration_estimate_seconds = %s,
                    updated_at = now()
                WHERE run_id = %s
                """,
                (
                    "finalizing" if chunk["final"] is True else phase,
                    completed_warmup,
                    completed_research,
                    ordinal,
                    completed_warmup,
                    last_warmup_session,
                    completed_research,
                    plan_chunk.last_session,
                    remaining_estimate,
                    claim.run_id,
                ),
            )

    def _validate_current_execution(self, claim: _ExecutionClaim) -> None:
        with self._database.transaction() as transaction:
            self._validate_current_execution_in_transaction(transaction, claim)

    def _validate_current_execution_in_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _ExecutionClaim,
    ) -> None:
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
        attempt = transaction.execute(
            """
            SELECT 1
            FROM research_runs.attempts
            WHERE id = %s AND run_id = %s AND fence = %s AND status = 'running'
            """,
            (claim.attempt_id, claim.run_id, claim.fence),
        ).fetchone()
        if attempt is None:
            raise ResearchRunFenced

    @contextmanager
    def _authorize_result_staging(
        self,
        claim: _ExecutionClaim,
    ) -> Iterator[None]:
        with self._database.transaction() as transaction:
            self._lock_result_staging(transaction, claim.run_id)
            self._validate_current_execution_in_transaction(transaction, claim)
            yield

    def _lock_result_staging(
        self,
        transaction: PostgresTransaction,
        run_id: str,
    ) -> None:
        transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"research_runs.result_staging:{run_id}",),
        ).fetchone()

    def _publish_success(
        self,
        claim: _ExecutionClaim,
        prepared: PreparedPublication,
        provenance: dict[str, object],
        key_metrics: ResearchRunKeyMetrics,
    ) -> None:
        assert self._publication is not None
        assert self._dataset_lifecycle is not None
        with self._database.transaction() as transaction:
            lock_publication_mutation(transaction)
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
            self._release_execution_checkpoints(transaction, claim.run_id)
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
                    result_provenance = %s, key_metrics = %s, failure_reason = NULL,
                    updated_at = now()
                WHERE id = %s AND status = 'running' AND execution_fence = %s
                """,
                (
                    published.manifest_sha256,
                    Jsonb(provenance),
                    Jsonb(key_metrics.model_dump(mode="json")),
                    claim.run_id,
                    claim.fence,
                ),
            )
            if updated.rowcount != 1:
                raise ResearchRunFenced
            transaction.execute(
                """
                UPDATE research_runs.progress
                SET phase = 'succeeded', updated_at = now()
                WHERE run_id = %s
                """,
                (claim.run_id,),
            )
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )

    def _record_failure(
        self,
        claim: _ExecutionClaim,
        error: Exception,
    ) -> _RecordedFailure | None:
        assert self._dataset_lifecycle is not None
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
                return None
            attempt = transaction.execute(
                """
                SELECT status,
                       (SELECT count(*)
                        FROM research_runs.attempts AS counted
                        WHERE counted.run_id = %s) AS attempt_count
                FROM research_runs.attempts
                WHERE id = %s AND run_id = %s AND fence = %s
                FOR UPDATE
                """,
                (
                    claim.run_id,
                    claim.attempt_id,
                    claim.run_id,
                    claim.fence,
                ),
            ).fetchone()
            if attempt is None or attempt["status"] != "running":
                return None
            attempt_number = int(attempt["attempt_count"])
            retry = attempt_retry_eligible(policy.attempt_reason, attempt_number)
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
                return None
            transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = %s, failure_reason = %s, updated_at = now()
                WHERE id = %s AND status = 'running' AND execution_fence = %s
                """,
                (
                    "running" if retry else "failed",
                    None if retry else policy.public_reason,
                    claim.run_id,
                    claim.fence,
                ),
            )
            if not retry:
                self._release_execution_checkpoints(transaction, claim.run_id)
            if retry:
                self._dataset_lifecycle.retain_generation_in_transaction(
                    transaction,
                    retention_id=f"queued-research-run:{claim.run_id}",
                    generation_manifest_sha256=(
                        claim.immutable_input.data_admission.generation_manifest_sha256
                    ),
                    lease_seconds=self._lease_seconds,
                )
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )
        return _RecordedFailure(
            retry=retry,
            attempt_number=attempt_number,
            failure_code=attempt_failure_code(policy.attempt_reason)
            or "UNCLASSIFIED_FAILURE",
        )

    def _release_execution_checkpoints(
        self,
        transaction: PostgresTransaction,
        run_id: str,
    ) -> None:
        assert self._publication is not None
        rows = transaction.execute(
            """
            SELECT checkpoint_manifest_sha256
            FROM research_runs.execution_checkpoints
            WHERE run_id = %s
            ORDER BY ordinal
            FOR UPDATE
            """,
            (run_id,),
        ).fetchall()
        transaction.execute(
            "DELETE FROM research_runs.execution_checkpoints WHERE run_id = %s",
            (run_id,),
        )
        for row in rows:
            self._publication.release_manifest_in_transaction(
                transaction,
                str(row["checkpoint_manifest_sha256"]),
                still_referenced=False,
            )


def _admission_receipt(
    transaction: PostgresTransaction,
    request_id: str,
) -> dict[str, object] | None:
    return transaction.execute(
        """
        SELECT request.request_fingerprint,
               run.id, run.name, run.folder_id, run.status,
               run.requested_start_date, run.requested_end_date,
               run.created_at, run.immutable_input, run.failure_reason
        FROM research_runs.admission_requests AS request
        JOIN research_runs.runs AS run ON run.id = request.run_id
        WHERE request.request_id = %s
        """,
        (request_id,),
    ).fetchone()


def _encode_list_cursor(row: Mapping[str, object]) -> str:
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise TypeError("ResearchRun created_at must be a datetime")
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": row["id"]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_list_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded: object = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(decoded, dict) or set(decoded) != {"created_at", "id"}:
            raise ValueError
        created_at = datetime.fromisoformat(str(decoded["created_at"]))
        run_id = decoded["id"]
        if created_at.tzinfo is None or not isinstance(run_id, str) or not run_id:
            raise ValueError
    except (ValueError, UnicodeDecodeError, Base64DecodeError) as error:
        raise ValueError("ResearchRun cursor is invalid") from error
    return created_at, run_id


def _admitted_input(
    command: ResearchRunAdmissionCommand,
    compiled: CompiledAlpha,
    snapshot: DatasetAdmissionSnapshot | None,
    *,
    execution_memory_bytes: int,
) -> ImmutableRunInput:
    if snapshot is None:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="DATA_NOT_READY",
                    field="data",
                    message="Current Dataset is not ready",
                )
            ]
        )
    if command.start_date < snapshot.coverage_start or command.end_date > snapshot.coverage_end:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="RESEARCH_PERIOD_OUTSIDE_COVERAGE",
                    field="start_date",
                    message="Requested Research Dates must be inside current Dataset Coverage",
                )
            ]
        )
    sessions = snapshot.research_period(command.start_date, command.end_date)
    if not sessions:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="RESEARCH_PERIOD_HAS_NO_SESSIONS",
                    field="start_date",
                    message="Requested Research Dates contain no Research Session",
                )
            ]
        )
    field_ids = frozenset(compiled.field_ids_by_identifier.values())
    if not field_ids <= snapshot.available_field_ids:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="FIELD_UNAVAILABLE_IN_CURRENT_DATA",
                    field="formula",
                    message="Alpha field is unavailable in current Data",
                )
            ]
        )
    financial_field_ids = {field.field_id for field in FINANCIAL_FIELDS}
    if field_ids & financial_field_ids:
        first_index = snapshot.research_sessions.index(sessions[0])
        warmup_index = first_index - compiled.effective_lookback
        financial_start = snapshot.financial_coverage_start
        financial_end = snapshot.financial_coverage_end
        if (
            financial_start is None
            or financial_end is None
            or warmup_index < 0
            or snapshot.research_sessions[warmup_index] < financial_start
            or sessions[-1] > financial_end
        ):
            available = (
                "not ready"
                if financial_start is None or financial_end is None
                else f"{financial_start.isoformat()} to {financial_end.isoformat()}"
            )
            raise ResearchRunAdmissionRejected(
                [
                    ResearchRunAdmissionIssue(
                        code="FINANCIAL_CALCULATION_OUTSIDE_COVERAGE",
                        field="formula",
                        message=(
                            "Financial Formula needs its requested period and lookback inside "
                            f"Financial Coverage; current Financial Coverage is {available}."
                        ),
                    )
                ]
            )
    try:
        calculation_session_count, universe_instrument_count = snapshot.calculation_shape(
            start=sessions[0],
            end=sessions[-1],
            lookback=compiled.effective_lookback,
            universe=command.universe,
        )
    except DatasetWarmupUnavailable as error:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="INSUFFICIENT_CALCULATION_WARMUP",
                    field="start_date",
                    message=str(error),
                )
            ]
        ) from error
    estimated_run_work = estimate_alpha_run_work(
        compiled.estimated_work,
        research_session_count=calculation_session_count,
        universe_instrument_count=universe_instrument_count,
    )
    first_research_index = snapshot.research_sessions.index(sessions[0])
    calculation_start_index = first_research_index - compiled.effective_lookback
    calculation_sessions = snapshot.research_sessions[
        calculation_start_index : snapshot.research_sessions.index(sessions[-1]) + 1
    ]
    try:
        execution_plan = plan_research_chunks(
            calculation_sessions=calculation_sessions,
            research_session_offset=compiled.effective_lookback,
            formula_work=compiled.estimated_work,
            node_count=compiled.node_count,
            field_count=len(compiled.field_ids_by_identifier),
            maximum_universe_cardinality=universe_instrument_count,
            effective_lookback=compiled.effective_lookback,
            execution_memory_bytes=execution_memory_bytes,
        )
    except ResearchChunkCapacityError as error:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="RESEARCH_SESSION_EXCEEDS_WORKER_CAPACITY",
                    field="universe",
                    message=str(error),
                )
            ]
        ) from error
    strategy_values: dict[str, object] = {}
    if isinstance(command, StrategyBacktestAdmissionCommand):
        strategy_values = {
            "strategy": {
                "kind": FIXED_STRATEGY_KIND,
                "holdings_count": command.holdings_count,
                "rebalance_every_sessions": command.rebalance_every_sessions,
                "initial_cash_cny": FIXED_INITIAL_CASH_CNY,
                "execution": FIXED_EXECUTION,
            },
            "costs": FIXED_COSTS,
            "risk_free_rate": "0",
        }
    return ImmutableRunInput(
        formula_source=command.formula,
        alpha_expression=compiled.expression,
        hypothesis=command.hypothesis,
        requested_start_date=command.start_date,
        requested_end_date=command.end_date,
        field_bindings={
            field_id: identifier
            for identifier, field_id in compiled.field_ids_by_identifier.items()
        },
        universe=command.universe,
        neutralization=command.neutralization,
        research_kind=command.research_kind,
        **strategy_values,
        numeric_execution_contract=NUMERIC_CONTRACT_ID,
        semantic_versions=SEMANTIC_VERSIONS,
        alpha_admission=AlphaAdmissionFacts(
            effective_lookback=compiled.effective_lookback,
            node_count=compiled.node_count,
            depth=compiled.depth,
            formula_work=compiled.estimated_work,
            estimated_run_work=estimated_run_work,
        ),
        data_admission=DataAdmissionFacts(
            generation_manifest_sha256=snapshot.generation_manifest_sha256,
            data_through_session=snapshot.data_through_session,
            coverage_start=snapshot.coverage_start,
            coverage_end=snapshot.coverage_end,
            first_research_session=sessions[0],
            last_research_session=sessions[-1],
            calculation_session_count=calculation_session_count,
            universe_instrument_count=universe_instrument_count,
        ),
        execution_plan=execution_plan,
    )


def _admission_fingerprint(command: ResearchRunAdmissionCommand) -> str:
    value = {
        "action": "research-runs.admit/v1",
        "command": command.model_dump(mode="json", exclude={"request_id"}),
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _generation_matches_frozen_facts(
    generation: object,
    immutable_input: ImmutableRunInput,
) -> bool:
    facts = immutable_input.data_admission
    return (
        getattr(generation, "manifest_sha256", None) == facts.generation_manifest_sha256
        and getattr(generation, "data_through_session", None)
        == facts.data_through_session.isoformat()
        and tuple(getattr(generation, "research_sessions", ()))
        and generation.research_sessions[0] == facts.coverage_start.isoformat()
        and generation.research_sessions[-1] == facts.coverage_end.isoformat()
        and set(immutable_input.field_bindings)
        <= set(getattr(generation, "field_availability", ()))
    )


def _result_provenance(claim: _ExecutionClaim) -> dict[str, object]:
    value = claim.immutable_input.canonical_value()
    calculation_contracts: dict[str, object] = {
        "numeric_execution_contract": value["numeric_execution_contract"],
    }
    if claim.immutable_input.research_kind == "strategy_backtest":
        calculation_contracts.update(
            {
                "strategy": value["strategy"],
                "costs": value["costs"],
                "risk_free_rate": value["risk_free_rate"],
            }
        )
    return {
        "schema_version": "research-result-v1",
        "research_run_id": claim.run_id,
        "research_kind": claim.immutable_input.research_kind,
        "immutable_input_sha256": hashlib.sha256(canonical_json_bytes(value)).hexdigest(),
        "data_generation_id": claim.data_generation_id,
        "data_through_session": claim.data_through_session,
        "calculation_contracts": calculation_contracts,
        "semantic_versions": value["semantic_versions"],
    }


def _research_event(
    event: str,
    *,
    level: str = "INFO",
    **context: object,
) -> dict[str, object]:
    return {
        "event": event,
        "level": level,
        "component": "research_worker",
        "worker_role": "research",
        **context,
    }


def _chunk_completes_phase(
    claim: _ExecutionClaim,
    chunk: Mapping[str, object],
) -> bool:
    ordinal = int(chunk["ordinal"])
    chunks = claim.immutable_input.execution_plan.chunks
    if ordinal >= len(chunks):
        return True
    next_chunk = chunks[ordinal]
    next_phase = "research" if next_chunk.research_session_count else "warmup"
    return next_phase != chunk["phase"]


def _failure_policy(error: Exception) -> _FailurePolicy:
    if isinstance(error, ResearchRunInsufficientWarmup):
        return _FailurePolicy(
            attempt_reason="InsufficientCalculationWarmup",
            public_reason=INSUFFICIENT_WARMUP_PUBLIC_REASON,
        )
    if isinstance(error, ResearchRunInputInvalid):
        return _FailurePolicy(
            attempt_reason="SelectedDataInvalid",
            public_reason=SELECTED_DATA_INVALID_PUBLIC_REASON,
        )
    if isinstance(
        error,
        (MemoryError, OutOfMemory, ResearchExecutionResourceExhausted),
    ):
        return _FailurePolicy(
            attempt_reason=RESOURCE_EXHAUSTED_FAILURE,
            public_reason=RESOURCE_EXHAUSTED_PUBLIC_REASON,
        )
    if isinstance(error, PublicationUnavailableError):
        return _FailurePolicy(
            attempt_reason=INFRASTRUCTURE_FAILURE,
            public_reason=INFRASTRUCTURE_PUBLIC_REASON,
        )
    if isinstance(
        error,
        (ResearchCheckpointIntegrityError, PublicationVerificationError),
    ):
        return _FailurePolicy(
            attempt_reason=CHECKPOINT_INTEGRITY_FAILURE,
            public_reason=CHECKPOINT_INTEGRITY_PUBLIC_REASON,
        )
    if isinstance(error, (ResearchRunContractMismatch, NumericContractError)):
        return _FailurePolicy(
            attempt_reason=CONTRACT_MISMATCH_FAILURE,
            public_reason=CONTRACT_MISMATCH_PUBLIC_REASON,
        )
    if isinstance(
        error,
        (ResearchExecutionError, ResearchResultError),
    ):
        return _FailurePolicy(
            attempt_reason=CALCULATION_FAILURE,
            public_reason=CALCULATION_PUBLIC_REASON,
        )
    if isinstance(
        error,
        (
            OperationalError,
            PoolTimeout,
            ConnectionError,
            TimeoutError,
        ),
    ):
        return _FailurePolicy(
            attempt_reason=INFRASTRUCTURE_FAILURE,
            public_reason=INFRASTRUCTURE_PUBLIC_REASON,
        )
    return _FailurePolicy(
        attempt_reason="PermanentExecutionFailure",
        public_reason=PERMANENT_FAILURE_PUBLIC_REASON,
    )


def _cancel_fingerprint(run_id: str) -> str:
    value = {"action": "research-runs.cancel/v1", "run_id": run_id}
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
    immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
    compact_formula = " ".join(immutable_input.formula_source.split())
    formula_summary = (
        compact_formula if len(compact_formula) <= 120 else f"{compact_formula[:117]}..."
    )
    return ResearchRunSummary.model_validate(
        {
            "id": row["id"],
            "status": row["status"],
            "name": row["name"],
            "folder_id": row["folder_id"],
            "created_at": row["created_at"],
            "start_date": row["requested_start_date"],
            "end_date": row["requested_end_date"],
            "formula_summary": formula_summary,
            "research_kind": immutable_input.research_kind,
            "key_metrics": row.get("key_metrics"),
            "failure_reason": row.get("failure_reason"),
        }
    )


def _result_key_metrics(
    final_values: Mapping[str, object],
    research_kind: ResearchKind,
) -> ResearchRunKeyMetrics:
    if research_kind == "factor_evaluation":
        factor_summary = final_values.get("factor_summary")
        if not isinstance(factor_summary, Mapping):
            raise ResearchResultError("Final Research values have no Factor summary")
        horizons = factor_summary.get("horizons")
        if not isinstance(horizons, Mapping):
            raise ResearchResultError("Final Research Factor summary has no horizons")
        try:
            return FactorEvaluationResearchRunKeyMetrics.model_validate(
                {
                    "research_kind": research_kind,
                    "one_session_rank_ic": _factor_rank_ic_mean(horizons, "1"),
                    "five_session_rank_ic": _factor_rank_ic_mean(horizons, "5"),
                    "twenty_session_rank_ic": _factor_rank_ic_mean(horizons, "20"),
                }
            )
        except ValidationError as error:
            raise ResearchResultError("Final Research Factor key metrics are invalid") from error

    strategy_summary = final_values.get("strategy_summary")
    if not isinstance(strategy_summary, Mapping):
        raise ResearchResultError("Final Research values have no Strategy summary")
    metrics = strategy_summary.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ResearchResultError("Final Research values have no Strategy metrics")
    maximum_drawdown = metrics.get("maximum_drawdown")
    if not isinstance(maximum_drawdown, Mapping):
        raise ResearchResultError("Final Research values have no Maximum Drawdown")
    try:
        return StrategyBacktestResearchRunKeyMetrics.model_validate(
            {
                "research_kind": research_kind,
                "annualized_excess_return": metrics.get("annualized_excess_return"),
                "sharpe": metrics.get("sharpe"),
                "maximum_drawdown": maximum_drawdown.get("value"),
            }
        )
    except ValidationError as error:
        raise ResearchResultError("Final Research key metrics are invalid") from error


def _factor_rank_ic_mean(
    horizons: Mapping[object, object],
    horizon_name: str,
) -> object:
    horizon = horizons.get(horizon_name)
    if not isinstance(horizon, Mapping):
        raise ResearchResultError(
            f"Final Research Factor summary has no {horizon_name}-session horizon"
        )
    summary = horizon.get("summary")
    if not isinstance(summary, Mapping):
        raise ResearchResultError(f"Final Research {horizon_name}-session horizon has no summary")
    rank_ic = summary.get("rank_ic")
    if not isinstance(rank_ic, Mapping):
        raise ResearchResultError(f"Final Research {horizon_name}-session horizon has no Rank IC")
    return rank_ic.get("mean")


def _authorable_input(row: object) -> ResearchRunAuthorableInput:
    assert isinstance(row, dict)
    immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
    strategy_values: dict[str, object] = {}
    if immutable_input.research_kind == "strategy_backtest":
        assert immutable_input.strategy is not None
        strategy_values = {
            "holdings_count": int(immutable_input.strategy["holdings_count"]),
            "rebalance_every_sessions": int(
                immutable_input.strategy["rebalance_every_sessions"]
            ),
        }
    return ResearchRunAuthorableInput(
        formula=immutable_input.formula_source,
        hypothesis=immutable_input.hypothesis,
        start_date=immutable_input.requested_start_date,
        end_date=immutable_input.requested_end_date,
        universe=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        research_kind=immutable_input.research_kind,
        **strategy_values,
    )


def _research_progress(row: Mapping[str, object]) -> ResearchRunProgress:
    return ResearchRunProgress(
        phase=str(row["progress_phase"]),
        completed_warmup_sessions=int(row["completed_warmup_sessions"]),
        total_warmup_sessions=int(row["total_warmup_sessions"]),
        completed_research_sessions=int(row["completed_research_sessions"]),
        total_research_sessions=int(row["total_research_sessions"]),
        committed_chunk_count=int(row["committed_chunk_count"]),
        last_completed_warmup_session=row.get("last_completed_warmup_session"),
        last_completed_research_session=row.get("last_completed_research_session"),
        remaining_duration_estimate_seconds=row.get("remaining_duration_estimate_seconds"),
    )


def _research_execution_timing(
    row: Mapping[str, object],
    status: str,
) -> ResearchRunExecutionTiming:
    started_at = row.get("execution_started_at")
    finished_at = row.get("execution_finished_at")
    observed_at = row.get("execution_observed_at")
    is_final = status in {"succeeded", "failed", "cancelled"}
    elapsed_seconds: float | None = None
    if isinstance(started_at, datetime):
        endpoint = finished_at if is_final else observed_at
        if isinstance(endpoint, datetime):
            elapsed_seconds = max(0.0, (endpoint - started_at).total_seconds())
    return ResearchRunExecutionTiming(
        started_at=started_at if isinstance(started_at, datetime) else None,
        finished_at=(
            finished_at
            if is_final and isinstance(finished_at, datetime)
            else None
        ),
        elapsed_seconds=elapsed_seconds,
        is_final=is_final,
    )


def _staged_payload_value(payload: StagedPayload) -> dict[str, object]:
    return {
        "sha256": payload.sha256,
        "byte_size": payload.byte_size,
        "media_type": payload.media_type,
        "serialization": dict(payload.serialization),
    }


def _staged_payload(value: object) -> StagedPayload:
    if not isinstance(value, Mapping):
        raise ResearchResultError("Staged Result payload reference is invalid")
    serialization = value.get("serialization")
    if not isinstance(serialization, Mapping):
        raise ResearchResultError("Staged Result payload serialization is invalid")
    return StagedPayload(
        sha256=str(value["sha256"]),
        byte_size=int(value["byte_size"]),
        media_type=str(value["media_type"]),
        serialization=dict(serialization),
    )


def _checkpoint_binding(
    *,
    immutable_input: ImmutableRunInput,
    run_id: str,
    creator_attempt_id: str,
    creator_fence: int,
    data_generation_id: str,
    ordinal: int,
    boundary_session: str,
    phase: str,
    completed_warmup_sessions: int,
    completed_research_sessions: int,
    continuation_payload: Mapping[str, object],
    observation_payload: Mapping[str, object] | None,
    final_values_payload: Mapping[str, object] | None,
    prior_chain_sha256: str | None,
) -> dict[str, object]:
    immutable_value = immutable_input.canonical_value()
    calculation_contracts: dict[str, object] = {
        "numeric_execution_contract": immutable_value["numeric_execution_contract"],
        "semantic_versions": immutable_value["semantic_versions"],
    }
    if immutable_input.research_kind == "strategy_backtest":
        calculation_contracts.update(
            {
                "strategy": immutable_value["strategy"],
                "costs": immutable_value["costs"],
                "risk_free_rate": immutable_value["risk_free_rate"],
            }
        )
    return {
        "schema_version": "research-execution-checkpoint-v1",
        "research_kind": immutable_input.research_kind,
        "run_id": run_id,
        "creator_attempt_id": creator_attempt_id,
        "creator_fence": creator_fence,
        "immutable_input_sha256": hashlib.sha256(canonical_json_bytes(immutable_value)).hexdigest(),
        "data_generation_id": data_generation_id,
        "compiler_contract": {
            "alpha_expression_sha256": hashlib.sha256(
                canonical_json_bytes(immutable_value["alpha_expression"])
            ).hexdigest(),
            "field_bindings_sha256": hashlib.sha256(
                canonical_json_bytes(immutable_value["field_bindings"])
            ).hexdigest(),
            "alpha_admission": immutable_value["alpha_admission"],
        },
        "calculation_contracts": calculation_contracts,
        "execution_plan_sha256": hashlib.sha256(
            canonical_json_bytes(immutable_value["execution_plan"])
        ).hexdigest(),
        "ordinal": ordinal,
        "boundary_session": boundary_session,
        "phase": phase,
        "completed_warmup_sessions": completed_warmup_sessions,
        "completed_research_sessions": completed_research_sessions,
        "continuation_payload": dict(continuation_payload),
        "observation_payload": (None if observation_payload is None else dict(observation_payload)),
        "final_values_payload": (
            None if final_values_payload is None else dict(final_values_payload)
        ),
        "prior_chain_sha256": prior_chain_sha256,
    }


def _checkpoint_json_payload(payload: object, *, subject: str) -> dict[str, object]:
    media_type = getattr(payload, "media_type", None)
    serialization = getattr(payload, "serialization", None)
    content = getattr(payload, "content", None)
    if (
        media_type != "application/json"
        or serialization
        != {
            "format": "canonical-json",
            "version": 1,
        }
        or not isinstance(content, bytes)
    ):
        raise ResearchCheckpointIntegrityError(f"Research Checkpoint {subject} encoding is invalid")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ResearchCheckpointIntegrityError(f"Research Checkpoint {subject} is invalid")
    return value


def _public_result(
    stored: object,
    provenance: dict[str, object],
    *,
    research_kind: str,
) -> ResearchRunResult:
    if not isinstance(stored, Mapping):
        raise ResearchRunResultUnavailable
    factor = stored.get("factor_summary")
    if not isinstance(factor, Mapping) or provenance.get("research_kind") != research_kind:
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
    public: dict[str, object] = {
        "factor": {"horizons": horizons},
        "provenance": {
            name: provenance[name]
            for name in (
                "schema_version",
                "research_run_id",
                "research_kind",
                "immutable_input_sha256",
                "calculation_contracts",
                "semantic_versions",
            )
        },
    }
    if research_kind == "factor_evaluation":
        return FactorEvaluationResearchRunResult.model_validate(public)
    strategy_summary = stored.get("strategy_summary")
    observations = stored.get("strategy_daily_observations")
    terminal_strategy_state = stored.get("terminal_strategy_state")
    if (
        research_kind != "strategy_backtest"
        or not isinstance(strategy_summary, Mapping)
        or not isinstance(observations, list)
        or not isinstance(terminal_strategy_state, Mapping)
    ):
        raise ResearchRunResultUnavailable
    benchmark = strategy_summary.get("benchmark")
    public_strategy_summary = {
        name: value for name, value in strategy_summary.items() if name != "benchmark"
    }
    public.update(
        {
            "strategy": {
                "summary": public_strategy_summary,
                "benchmark": benchmark,
                "observations": observations,
            },
            "terminal_strategy_state": {
                name: terminal_strategy_state[name]
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
        }
    )
    return StrategyBacktestResearchRunResult.model_validate(public)


def _collect_publication_deletions(
    publication: Publication,
    *,
    lifecycle_event: Callable[[dict[str, object]], None],
    run_id: str,
) -> None:
    try:
        while publication.collect_one_pending_deletion():
            pass
    except (PublicationPreparationError, PublicationUnavailableError):
        lifecycle_event(
            {
                "event": "research_publication_cleanup_deferred",
                "level": "WARNING",
                "run_id": run_id,
                "failure_code": "PUBLICATION_UNAVAILABLE",
            }
        )


def research_run_exists(transaction: PostgresTransaction, run_id: str) -> bool:
    return (
        transaction.execute(
            "SELECT 1 FROM research_runs.runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        is not None
    )


def research_result_manifest_is_referenced(
    transaction: PostgresTransaction,
    manifest_sha256: str,
) -> bool:
    return (
        transaction.execute(
            """
        SELECT 1
        FROM research_runs.runs
        WHERE result_manifest_sha256 = %s
        LIMIT 1
        """,
            (manifest_sha256,),
        ).fetchone()
        is not None
    )
