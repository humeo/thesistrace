from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import math
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from psycopg import OperationalError
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data import DatasetLifecycle
from thesistrace.publication import PublicationUnavailableError
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_batch.execution import (
    ExecutionEvent,
    ResearchBatchChildLost,
    ResearchBatchExecutionItem,
    ResearchBatchExecutionRequest,
    SupervisedResearchBatchExecution,
    SupervisedResearchBatchExecutor,
    item_failure_error,
)
from thesistrace.research_batch.models import (
    FactorEvaluationBatchAdmissionCommand,
    FactorEvaluationBatchProgress,
    ResearchBatchAdmissionCommand,
    ResearchBatchAdmissionIssue,
    ResearchBatchAttemptSummary,
    ResearchBatchDetail,
    ResearchBatchDiagnostic,
    ResearchBatchExecutionTiming,
    ResearchBatchItemSummary,
    ResearchBatchList,
    ResearchBatchLiveProgress,
    ResearchBatchScope,
    ResearchBatchSummary,
    StrategySweepBatchAdmissionCommand,
    StrategySweepBatchProgress,
)
from thesistrace.research_batch.planning import (
    ResearchBatchCapacityError,
    validate_research_batch_capacity,
)
from thesistrace.research_folder import BATCH_RESEARCH_FOLDER_ID
from thesistrace.research_run.models import (
    FactorEvaluationAdmissionCommand,
    ResearchRunAdmissionCommand,
    StrategyBacktestAdmissionCommand,
)
from thesistrace.research_run.service import (
    PreparedResearchRunAdmission,
    ResearchRunAdmissionRejected,
    ResearchRunExecutionClaim,
    ResearchRunService,
)

BATCH_ADMISSION_RETENTION_SECONDS = 15 * 60
BATCH_ATTEMPT_LEASE_SECONDS = 15 * 60
BATCH_ATTEMPT_HEARTBEAT_SECONDS = 30
MAX_FACTOR_TASK_ATTEMPTS = 3
FACTOR_TASK_INFRASTRUCTURE_FAILURE = "InfrastructureUnavailable"
FACTOR_TASK_WORKER_LOST_FAILURE = "WorkerLost"
FACTOR_TASK_PERMANENT_FAILURE = "PermanentExecutionFailure"
FACTOR_TASK_INFRASTRUCTURE_PUBLIC_REASON = (
    "Research execution could not complete after automatic retries."
)
FACTOR_TASK_PERMANENT_PUBLIC_REASON = "Research execution failed."
logger = logging.getLogger(__name__)


def _confirm_child_exited(value: str) -> bool:
    path = Path(value)
    if not path.is_absolute() or path.parent.name != ".batch-attempts":
        raise RuntimeError("Research Batch child control path is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    control = path.open("a+")
    try:
        try:
            fcntl.flock(control.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        path.unlink(missing_ok=True)
        return True
    finally:
        control.close()


@dataclass(frozen=True)
class _ResearchBatchClaim:
    batch_id: str
    batch_kind: str
    admitted_at: datetime
    attempt_id: str
    fence: int
    generation_pin_id: str
    data_generation_id: str
    items: tuple[tuple[int, str, ResearchRunExecutionClaim], ...]


@dataclass(frozen=True)
class _FactorTaskFailurePolicy:
    attempt_reason: str
    public_reason: str
    retryable: bool


class ResearchBatchAdmissionConflict(RuntimeError):
    pass


class ResearchBatchAdmissionRejected(ValueError):
    def __init__(self, issues: list[ResearchBatchAdmissionIssue]) -> None:
        super().__init__("Research Batch admission rejected")
        self.issues = issues


class ResearchBatchService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        research_runs: ResearchRunService,
        dataset_lifecycle: DatasetLifecycle,
        attempt_control_directory: Path,
        execution: SupervisedResearchBatchExecutor | None = None,
        retention_seconds: float = BATCH_ADMISSION_RETENTION_SECONDS,
        lease_seconds: float = BATCH_ATTEMPT_LEASE_SECONDS,
        heartbeat_seconds: float = BATCH_ATTEMPT_HEARTBEAT_SECONDS,
    ) -> None:
        if retention_seconds <= 0 or lease_seconds <= 0 or heartbeat_seconds <= 0:
            raise ValueError("Research Batch lease durations must be positive")
        self._database = database
        self._research_runs = research_runs
        self._dataset_lifecycle = dataset_lifecycle
        self._attempt_control_directory = attempt_control_directory.resolve()
        self._execution = execution
        self._retention_seconds = retention_seconds
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds

    @property
    def execution_memory_bytes(self) -> int:
        return self._research_runs.execution_memory_bytes

    def process_next(
        self,
        *,
        on_claim: Callable[[str, str, Mapping[str, object]], None] | None = None,
        on_execution_event: ExecutionEvent | None = None,
    ) -> bool:
        if self._execution is None:
            raise RuntimeError("Research Batch execution is not configured")
        claim = self._claim_next()
        if claim is None:
            return False
        external_emit = on_execution_event or (lambda _event: None)
        claim_announced = False

        def emit(event: dict[str, object]) -> None:
            nonlocal claim_announced
            if event.get("event") == "research_batch_execution_child_exited":
                try:
                    self._record_live_execution_event(claim, event)
                except (OperationalError, PoolTimeout):
                    logger.error(
                        "Research Batch child exit could not be persisted",
                        extra={"batch_id": claim.batch_id, "attempt_id": claim.attempt_id},
                    )
            else:
                self._record_live_execution_event(claim, event)
            if (
                event.get("event") == "research_batch_execution_child_started"
                and on_claim is not None
                and not claim_announced
            ):
                on_claim(
                    claim.batch_id,
                    claim.attempt_id,
                    {
                        "batch_kind": claim.batch_kind,
                        "claim_order": {
                            "admitted_at": claim.admitted_at.isoformat(),
                            "batch_id": claim.batch_id,
                        },
                        "owner_kind": "research_batch_attempt",
                        "owner_id": claim.attempt_id,
                        "item_count": len(claim.items),
                    },
                )
                claim_announced = True
            external_emit(event)

        execution: SupervisedResearchBatchExecution | None = None
        try:
            with self._maintain_claim(claim):
                execution = self._execution.execute(
                    ResearchBatchExecutionRequest(
                        batch_kind=claim.batch_kind,
                        batch_id=claim.batch_id,
                        attempt_id=claim.attempt_id,
                        data_generation_id=claim.data_generation_id,
                        items=tuple(
                            ResearchBatchExecutionItem(
                                ordinal=ordinal,
                                item_key=item_key,
                                run_id=run_claim.run_id,
                                immutable_input=run_claim.immutable_input,
                            )
                            for ordinal, item_key, run_claim in claim.items
                        ),
                    ),
                    emit=emit,
                )
                if execution.message.get("status") != "batch_prepared":
                    raise RuntimeError("Research Batch child did not prepare shared data")
                execution.advance("acknowledge_preparation")
                if claim.batch_kind == "strategy_sweep":
                    if execution.message.get("status") != "shared_alpha_factor_started":
                        raise RuntimeError(
                            "Strategy Sweep child did not start its shared prerequisite"
                        )
                    execution.advance("acknowledge_progress")
                    shared = execution.message
                    while shared.get("status") == "shared_alpha_factor_chunk_succeeded":
                        execution.advance("acknowledge_progress")
                        shared = execution.message
                    if shared.get("status") == "shared_alpha_factor_failed":
                        diagnostic = _message_diagnostic(shared)
                        self._fail_running_items(
                            claim,
                            item_failure_error(shared),
                            diagnostic=diagnostic,
                        )
                        self._set_shared_alpha_factor_status(claim, "failed")
                        execution.advance("acknowledge_shared")
                    elif shared.get("status") == "shared_alpha_factor_succeeded":
                        self._set_shared_alpha_factor_status(claim, "succeeded")
                        execution.advance("acknowledge_shared")
                    else:
                        raise RuntimeError(
                            "Strategy Sweep child did not complete its shared prerequisite"
                        )
                claims_by_ordinal = {
                    ordinal: (item_key, run_claim) for ordinal, item_key, run_claim in claim.items
                }
                while execution.message.get("status") != "batch_succeeded":
                    message = execution.message
                    self._validate_claim(claim)
                    ordinal = int(message.get("item_ordinal", 0))
                    selected = claims_by_ordinal.get(ordinal)
                    if selected is None:
                        raise RuntimeError("Factor Batch child returned an unknown item")
                    item_key, run_claim = selected
                    if (
                        message.get("item_key") != item_key
                        or message.get("run_id") != run_claim.run_id
                    ):
                        raise RuntimeError("Factor Batch child item identity is invalid")
                    if message.get("status") in {
                        "item_started",
                        "item_strategy_chunk_succeeded",
                    }:
                        execution.advance("acknowledge_progress")
                        continue
                    if message.get("status") == "item_failed":
                        diagnostic = _message_diagnostic(message)
                        self._research_runs.fail_batch_owned_item(
                            run_claim,
                            item_failure_error(message),
                            authorize_batch=lambda transaction: (
                                self._authorize_claim_in_transaction(transaction, claim)
                            ),
                            complete_batch_item=(
                                lambda transaction,
                                outcome,
                                reason,
                                ordinal=ordinal,
                                diagnostic=diagnostic: (
                                    self._complete_item_in_transaction(
                                        transaction,
                                        claim,
                                        ordinal,
                                        outcome,
                                        reason,
                                        diagnostic,
                                    )
                                )
                            ),
                        )
                        execution.advance("acknowledge_item")
                        continue
                    if message.get("status") == "item_succeeded":
                        if claim.batch_kind != "strategy_sweep":
                            raise RuntimeError("Research Batch item response Kind is invalid")
                        chunk = message.get("chunk")
                        if not isinstance(chunk, Mapping):
                            raise RuntimeError("Strategy Sweep child task is invalid")
                        self._research_runs.complete_batch_owned_strategy_item(
                            run_claim,
                            chunk,
                            authorize_batch=lambda transaction: (
                                self._authorize_claim_in_transaction(transaction, claim)
                            ),
                            complete_batch_item=(
                                lambda transaction, outcome, reason, ordinal=ordinal: (
                                    self._complete_item_in_transaction(
                                        transaction,
                                        claim,
                                        ordinal,
                                        outcome,
                                        reason,
                                        None,
                                    )
                                )
                            ),
                        )
                        execution.advance("acknowledge_item")
                        continue
                    if message.get("status") != "item_chunk_succeeded":
                        raise RuntimeError("Research Batch child response is invalid")
                    chunk = message.get("chunk")
                    if not isinstance(chunk, Mapping):
                        raise RuntimeError("Factor Batch child Chunk is invalid")
                    if chunk.get("final") is True:
                        self._research_runs.complete_batch_owned_factor_item(
                            run_claim,
                            chunk,
                            authorize_batch=lambda transaction: (
                                self._authorize_claim_in_transaction(transaction, claim)
                            ),
                            complete_batch_item=(
                                lambda transaction, outcome, reason, ordinal=ordinal: (
                                    self._complete_item_in_transaction(
                                        transaction,
                                        claim,
                                        ordinal,
                                        outcome,
                                        reason,
                                        None,
                                    )
                                )
                            ),
                        )
                        command = "acknowledge_item"
                    else:
                        command = "acknowledge_chunk"
                    execution.advance(command)
                self._validate_claim(claim)
                execution.acknowledge()
                self._finish_attempt(claim, failed=False)
        except Exception as error:
            if execution is not None:
                execution.close()
            try:
                starting_closed = self._finish_interrupted_starting_claim(claim, error)
                if starting_closed:
                    pass
                elif claim.batch_kind == "factor_evaluation":
                    self._finish_interrupted_factor_attempt(claim, error)
                else:
                    self._fail_running_items(claim, error)
            except Exception as cleanup_error:
                logger.error(
                    "Research Batch failure cleanup did not reach every child",
                    extra={
                        "batch_id": claim.batch_id,
                        "error_type": type(cleanup_error).__name__,
                    },
                    exc_info=(
                        type(cleanup_error),
                        cleanup_error,
                        cleanup_error.__traceback__,
                    ),
                )
            else:
                if starting_closed or claim.batch_kind == "factor_evaluation":
                    logger.error(
                        "Research Batch execution ended for recovery",
                        extra={
                            "batch_id": claim.batch_id,
                            "error_type": type(error).__name__,
                        },
                    )
                elif not starting_closed:
                    self._finish_attempt(claim, failed=True, error=error)
            logger.error(
                "Research Batch execution failed",
                extra={
                    "batch_id": claim.batch_id,
                    "error_type": type(error).__name__,
                },
                exc_info=(type(error), error, error.__traceback__),
            )
        finally:
            if execution is not None:
                execution.close()
        return True

    def admit(self, command: ResearchBatchAdmissionCommand) -> ResearchBatchDetail:
        fingerprint = _admission_fingerprint(command)
        replay = self._locked_receipt(command.request_id, fingerprint)
        if replay is not None:
            return replay

        _validate_unique_item_keys(command)
        dataset = self._research_runs.current_admission_dataset()
        child_commands = _child_commands(command)
        prepared: list[PreparedResearchRunAdmission] = []
        issues: list[ResearchBatchAdmissionIssue] = []
        for ordinal, (item_key, child_command) in enumerate(child_commands, start=1):
            try:
                child = self._research_runs.prepare_child_admission(
                    child_command,
                    dataset=dataset,
                )
            except ResearchRunAdmissionRejected as error:
                issues.extend(_child_issues(command, ordinal, item_key, error))
            else:
                prepared.append(child)
        if issues:
            raise ResearchBatchAdmissionRejected(_deduplicated_issues(issues))
        _validate_duplicate_computation(command, prepared)
        try:
            validate_research_batch_capacity(command.batch_kind, prepared)
        except ResearchBatchCapacityError as error:
            raise ResearchBatchAdmissionRejected(
                [
                    ResearchBatchAdmissionIssue(
                        code="RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY",
                        field="universe",
                        message=str(error),
                    )
                ]
            ) from error

        batch_id = f"batch_{uuid4().hex[:20]}"
        scope = _scope(prepared)
        with self._database.transaction() as transaction:
            _lock_admission(transaction, command.request_id)
            receipt = _receipt(transaction, command.request_id)
            if receipt is not None:
                return _replayed_receipt(receipt, fingerprint)
            folder = transaction.execute(
                """
                SELECT id
                FROM research_folders.folders
                WHERE id = %s
                FOR KEY SHARE
                """,
                (BATCH_RESEARCH_FOLDER_ID,),
            ).fetchone()
            if folder is None:
                raise RuntimeError("Batch Research Folder is unavailable")
            batch_row = transaction.execute(
                """
                INSERT INTO research_batches.batches (
                    id, batch_kind, status, scope
                ) VALUES (%s, %s, 'queued', %s)
                RETURNING id, batch_kind, status, scope, created_at
                """,
                (batch_id, command.batch_kind, Jsonb(scope.model_dump(mode="json"))),
            ).fetchone()
            assert batch_row is not None
            for ordinal, ((item_key, _), child) in enumerate(
                zip(child_commands, prepared, strict=True),
                start=1,
            ):
                self._research_runs.admit_prepared_child_in_transaction(
                    transaction,
                    child,
                    execution_owner="research_batch",
                    retain_generation=False,
                )
                transaction.execute(
                    """
                    INSERT INTO research_batches.items (
                        batch_id, ordinal, item_key, research_run_id, dependency_role
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        batch_id,
                        ordinal,
                        item_key,
                        child.run_id,
                        "factor" if command.batch_kind == "factor_evaluation" else "strategy",
                    ),
                )
            transaction.execute(
                """
                INSERT INTO research_batches.progress (
                    batch_id, completed_items, total_items,
                    shared_alpha_factor_status
                ) VALUES (%s, 0, %s, %s)
                """,
                (
                    batch_id,
                    len(prepared),
                    "pending" if command.batch_kind == "strategy_sweep" else None,
                ),
            )
            self._dataset_lifecycle.retain_generation_in_transaction(
                transaction,
                retention_id=f"research-batch:{batch_id}",
                generation_manifest_sha256=scope.data_generation_id,
                lease_seconds=self._retention_seconds,
            )
            outcome = _detail_in_transaction(
                transaction,
                batch_id,
                research_runs=self._research_runs,
            )
            transaction.execute(
                """
                INSERT INTO research_batches.admission_receipts (
                    request_id, request_fingerprint, batch_id, outcome
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    command.request_id,
                    fingerprint,
                    batch_id,
                    Jsonb(outcome.model_dump(mode="json")),
                ),
            )
        return outcome

    def list(self, *, cursor: str | None, limit: int) -> ResearchBatchList:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT batch.id, batch.batch_kind, batch.status, batch.scope,
                       batch.created_at, progress.completed_items,
                       progress.total_items,
                       progress.shared_alpha_factor_status,
                       timing.execution_started_at,
                       timing.execution_finished_at,
                       CURRENT_TIMESTAMP AS execution_observed_at
                FROM research_batches.batches AS batch
                JOIN research_batches.progress AS progress
                  ON progress.batch_id = batch.id
                LEFT JOIN LATERAL (
                    SELECT min(attempt.started_at) AS execution_started_at,
                           max(attempt.finished_at) AS execution_finished_at
                    FROM research_batches.attempts AS attempt
                    WHERE attempt.batch_id = batch.id
                ) AS timing ON true
                WHERE (
                    %s::timestamptz IS NULL
                    OR batch.created_at < %s::timestamptz
                    OR (
                        batch.created_at = %s::timestamptz
                        AND batch.id > %s::text
                    )
                )
                ORDER BY batch.created_at DESC, batch.id
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
            summaries = [_summary_from_row(row) for row in rows[:limit]]
        return ResearchBatchList(
            items=summaries,
            next_cursor=(_encode_cursor(summaries[-1]) if len(rows) > limit else None),
        )

    def get(self, batch_id: str) -> ResearchBatchDetail | None:
        with self._database.transaction() as transaction:
            exists = transaction.execute(
                "SELECT id FROM research_batches.batches WHERE id = %s",
                (batch_id,),
            ).fetchone()
            if exists is None:
                return None
            return _detail_in_transaction(
                transaction,
                batch_id,
                research_runs=self._research_runs,
            )

    def _claim_next(self) -> _ResearchBatchClaim | None:
        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("research_batches.claim_fifo",),
            ).fetchone()
            while True:
                row = transaction.execute(
                    """
                    SELECT batch.id, batch.batch_kind, batch.created_at,
                           batch.execution_fence, batch.scope, batch.status,
                           expired.id AS expired_attempt_id,
                           expired.fence AS expired_attempt_fence,
                           expired.generation_pin_id AS expired_generation_pin_id,
                           expired.child_control_path AS expired_child_control_path,
                           starting.id AS expired_starting_id,
                           starting.fence AS expired_starting_fence,
                           starting.generation_pin_id AS expired_starting_pin_id,
                           starting.child_control_path AS expired_starting_control_path
                    FROM research_batches.batches AS batch
                    LEFT JOIN LATERAL (
                        SELECT attempt.id, attempt.fence,
                               attempt.generation_pin_id,
                               attempt.child_control_path,
                               attempt.lease_expires_at
                        FROM research_batches.attempts AS attempt
                        WHERE attempt.batch_id = batch.id
                          AND attempt.status = 'running'
                        ORDER BY attempt.ordinal DESC
                        LIMIT 1
                    ) AS expired ON true
                    LEFT JOIN research_batches.starting_claims AS starting
                      ON starting.batch_id = batch.id
                    WHERE batch.status = 'queued'
                       OR (
                           batch.status = 'running'
                           AND (
                               starting.lease_expires_at <= now()
                               OR (
                                   batch.batch_kind = 'factor_evaluation'
                                   AND expired.lease_expires_at <= now()
                               )
                           )
                       )
                    ORDER BY batch.created_at, batch.id
                    FOR UPDATE OF batch SKIP LOCKED
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    return None
                if row["status"] == "running":
                    if row["expired_starting_id"] is not None:
                        recovered = self._recover_expired_starting_claim_in_transaction(
                            transaction, row
                        )
                    else:
                        recovered = self._recover_expired_factor_attempt_in_transaction(
                            transaction,
                            row,
                        )
                    if not recovered:
                        return None
                    refreshed = transaction.execute(
                        """
                        SELECT id, batch_kind, created_at, execution_fence,
                               scope, status
                        FROM research_batches.batches
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (row["id"],),
                    ).fetchone()
                    if refreshed is None or refreshed["status"] != "queued":
                        continue
                    row = refreshed
                break
            batch_id = str(row["id"])
            batch_kind = str(row["batch_kind"])
            if batch_kind == "factor_evaluation":
                dependency_role = "factor"
            elif batch_kind == "strategy_sweep":
                dependency_role = "strategy"
            else:
                raise RuntimeError("Research Batch Kind is invalid")
            fence = int(row["execution_fence"]) + 1
            ordinal_row = transaction.execute(
                """
                SELECT coalesce(max(ordinal), 0) + 1 AS ordinal
                FROM research_batches.attempts
                WHERE batch_id = %s
                """,
                (batch_id,),
            ).fetchone()
            assert ordinal_row is not None
            attempt_id = f"batch_attempt_{uuid4().hex[:20]}"
            child_control_path = str(
                self._attempt_control_directory / f"{attempt_id}.lock"
            )
            scope = ResearchBatchScope.model_validate(row["scope"])
            pinned = self._dataset_lifecycle.pin_generation_in_transaction(
                transaction,
                generation_manifest_sha256=scope.data_generation_id,
                owner_kind="research_batch_attempt",
                owner_id=attempt_id,
                lease_seconds=self._lease_seconds,
            )
            if (
                pinned.descriptor.manifest_sha256 != scope.data_generation_id
                or pinned.descriptor.data_through_session != scope.data_through_session.isoformat()
            ):
                raise RuntimeError("Factor Batch Generation facts changed")
            item_rows = transaction.execute(
                """
                SELECT ordinal, item_key, research_run_id
                FROM research_batches.items
                WHERE batch_id = %s AND dependency_role = %s
                  AND outcome IS NULL
                ORDER BY ordinal
                FOR UPDATE
                """,
                (batch_id, dependency_role),
            ).fetchall()
            if not item_rows:
                raise RuntimeError("Research Batch has no incomplete items")
            claimed_items = tuple(
                (
                    int(item["ordinal"]),
                    str(item["item_key"]),
                    self._research_runs.begin_batch_owned_execution_in_transaction(
                        transaction,
                        str(item["research_run_id"]),
                        batch_attempt_id=attempt_id,
                        generation_pin_id=pinned.pin.id,
                        generation=pinned.descriptor,
                        batch_kind=batch_kind,
                    ),
                )
                for item in item_rows
            )
            generation_ids = {item[2].data_generation_id for item in claimed_items}
            if len(generation_ids) != 1:
                raise RuntimeError("Factor Batch Generation is inconsistent")
            updated = transaction.execute(
                """
                UPDATE research_batches.batches
                SET status = 'running', execution_fence = %s, updated_at = now()
                WHERE id = %s AND status = 'queued'
                """,
                (fence, batch_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Factor Batch claim was fenced")
            transaction.execute(
                """
                INSERT INTO research_batches.starting_claims (
                    id, batch_id, ordinal, fence, generation_pin_id,
                    data_generation_id, data_through_session,
                    child_control_path, lease_expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    now() + make_interval(secs => %s)
                )
                """,
                (
                    attempt_id,
                    batch_id,
                    int(ordinal_row["ordinal"]),
                    fence,
                    pinned.pin.id,
                    pinned.descriptor.manifest_sha256,
                    pinned.descriptor.data_through_session,
                    child_control_path,
                    self._lease_seconds,
                ),
            )
            self._dataset_lifecycle.release_retention_in_transaction(
                transaction,
                retention_id=f"research-batch:{batch_id}",
            )
        return _ResearchBatchClaim(
            batch_id=batch_id,
            batch_kind=batch_kind,
            admitted_at=row["created_at"],
            attempt_id=attempt_id,
            fence=fence,
            generation_pin_id=pinned.pin.id,
            data_generation_id=pinned.descriptor.manifest_sha256,
            items=claimed_items,
        )

    def _recover_expired_factor_attempt_in_transaction(
        self,
        transaction: PostgresTransaction,
        row: Mapping[str, object],
    ) -> bool:
        batch_id = str(row["id"])
        attempt_id = row["expired_attempt_id"]
        attempt_fence = row["expired_attempt_fence"]
        generation_pin_id = row["expired_generation_pin_id"]
        child_control_path = row["expired_child_control_path"]
        if (
            not isinstance(attempt_id, str)
            or not isinstance(attempt_fence, int)
            or not isinstance(generation_pin_id, str)
            or not isinstance(child_control_path, str)
            or attempt_fence != int(row["execution_fence"])
        ):
            raise RuntimeError("Expired Factor Batch Attempt authority is invalid")
        if not _confirm_child_exited(child_control_path):
            return False
        diagnostic = ResearchBatchDiagnostic(
            code="FACTOR_TASK_WORKER_LOST",
            category="infrastructure",
            message="The Factor task Worker was lost before acknowledgement.",
        )
        self._close_factor_attempt_in_transaction(
            transaction,
            batch_id=batch_id,
            attempt_id=attempt_id,
            fence=attempt_fence,
            generation_pin_id=generation_pin_id,
            policy=_FactorTaskFailurePolicy(
                attempt_reason=FACTOR_TASK_WORKER_LOST_FAILURE,
                public_reason=FACTOR_TASK_INFRASTRUCTURE_PUBLIC_REASON,
                retryable=True,
            ),
            diagnostic=diagnostic,
            require_expired=True,
        )
        return True

    def _recover_expired_starting_claim_in_transaction(
        self,
        transaction: PostgresTransaction,
        row: Mapping[str, object],
    ) -> bool:
        batch_id = str(row["id"])
        claim_id = row["expired_starting_id"]
        fence = row["expired_starting_fence"]
        pin_id = row["expired_starting_pin_id"]
        control_path = row["expired_starting_control_path"]
        if (
            not isinstance(claim_id, str)
            or not isinstance(fence, int)
            or not isinstance(pin_id, str)
            or not isinstance(control_path, str)
            or fence != int(row["execution_fence"])
        ):
            raise RuntimeError("Expired Factor Batch starting authority is invalid")
        if not _confirm_child_exited(control_path):
            return False
        incomplete = transaction.execute(
            """
            SELECT research_run_id
            FROM research_batches.items
            WHERE batch_id = %s AND outcome IS NULL
            ORDER BY ordinal
            FOR UPDATE
            """,
            (batch_id,),
        ).fetchall()
        self._research_runs.reset_incomplete_batch_owned_executions_in_transaction(
            transaction,
            [str(item["research_run_id"]) for item in incomplete],
        )
        deleted = transaction.execute(
            """
            DELETE FROM research_batches.starting_claims
            WHERE id = %s AND batch_id = %s AND fence = %s
              AND lease_expires_at <= now()
            """,
            (claim_id, batch_id, fence),
        )
        if deleted.rowcount != 1:
            raise RuntimeError("Expired Factor Batch starting claim was fenced")
        self._dataset_lifecycle.release_pin_in_transaction(
            transaction,
            pin_id,
            owner_id=claim_id,
        )
        updated = transaction.execute(
            """
            UPDATE research_batches.batches
            SET status = 'queued', updated_at = now()
            WHERE id = %s AND status = 'running' AND execution_fence = %s
            """,
            (batch_id, fence),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Expired Factor Batch starting recovery was fenced")
        return True

    def _fail_recovered_factor_item_in_transaction(
        self,
        transaction: PostgresTransaction,
        *,
        batch_id: str,
        item_ordinal: int,
        run_id: str,
        diagnostic: ResearchBatchDiagnostic,
    ) -> None:
        self._research_runs.fail_recovered_batch_owned_item_in_transaction(
            transaction,
            run_id,
            public_reason=diagnostic.message,
        )
        updated = transaction.execute(
            """
            UPDATE research_batches.items
            SET outcome = 'failed', diagnostic = %s
            WHERE batch_id = %s AND ordinal = %s AND outcome IS NULL
            """,
            (Jsonb(diagnostic.model_dump(mode="json")), batch_id, item_ordinal),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Recovered Factor task completion was fenced")
        progress = transaction.execute(
            """
            UPDATE research_batches.progress
            SET completed_items = completed_items + 1, updated_at = now()
            WHERE batch_id = %s AND completed_items < total_items
            """,
            (batch_id,),
        )
        if progress.rowcount != 1:
            raise RuntimeError("Recovered Factor progress was fenced")

    def _terminal_status_from_items_in_transaction(
        self,
        transaction: PostgresTransaction,
        batch_id: str,
    ) -> str:
        counts = transaction.execute(
            """
            SELECT count(*) FILTER (WHERE outcome = 'succeeded') AS succeeded,
                   count(*) FILTER (WHERE outcome IS NULL) AS incomplete,
                   count(*) AS total
            FROM research_batches.items
            WHERE batch_id = %s
            """,
            (batch_id,),
        ).fetchone()
        if counts is None or int(counts["incomplete"]) != 0:
            raise RuntimeError("Research Batch terminal outcomes are incomplete")
        succeeded = int(counts["succeeded"])
        total = int(counts["total"])
        if succeeded == total:
            return "succeeded"
        return "completed_with_failures" if succeeded else "failed"

    @contextmanager
    def _maintain_claim(self, claim: _ResearchBatchClaim) -> Iterator[None]:
        stopped = Event()
        heartbeat = Thread(
            target=self._heartbeat_claim,
            args=(claim, stopped),
            name=f"research-batch-heartbeat-{claim.batch_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat.join(timeout=5)

    def _heartbeat_claim(self, claim: _ResearchBatchClaim, stopped: Event) -> None:
        while not stopped.wait(self._heartbeat_seconds):
            try:
                with self._database.transaction() as transaction:
                    renewed = transaction.execute(
                        """
                        UPDATE research_batches.attempts AS attempt
                        SET heartbeat_at = now(),
                            lease_expires_at = now() + make_interval(secs => %s),
                            live_progress_updated_at = CASE
                                WHEN current_task_role IS NOT NULL THEN now()
                                ELSE live_progress_updated_at
                            END
                        WHERE attempt.id = %s AND attempt.batch_id = %s
                          AND attempt.fence = %s AND attempt.status = 'running'
                          AND attempt.lease_expires_at > now()
                          AND EXISTS (
                              SELECT 1
                              FROM research_batches.batches AS batch
                              WHERE batch.id = attempt.batch_id
                                AND batch.status = 'running'
                                AND batch.execution_fence = attempt.fence
                          )
                        """,
                        (
                            self._lease_seconds,
                            claim.attempt_id,
                            claim.batch_id,
                            claim.fence,
                        ),
                    )
                    if renewed.rowcount == 0:
                        renewed = transaction.execute(
                            """
                            UPDATE research_batches.starting_claims AS claim
                            SET heartbeat_at = now(),
                                lease_expires_at = now() + make_interval(secs => %s)
                            WHERE claim.id = %s AND claim.batch_id = %s
                              AND claim.fence = %s
                              AND claim.lease_expires_at > now()
                              AND EXISTS (
                                  SELECT 1
                                  FROM research_batches.batches AS batch
                                  WHERE batch.id = claim.batch_id
                                    AND batch.status = 'running'
                                    AND batch.execution_fence = claim.fence
                              )
                            """,
                            (
                                self._lease_seconds,
                                claim.attempt_id,
                                claim.batch_id,
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
                logger.error(
                    "Research Batch claim heartbeat failed",
                    extra={
                        "batch_id": claim.batch_id,
                        "error_type": type(error).__name__,
                    },
                )
                return
            if renewed.rowcount != 1:
                return

    def _validate_claim(self, claim: _ResearchBatchClaim) -> None:
        with self._database.transaction() as transaction:
            self._authorize_claim_in_transaction(transaction, claim)

    def _authorize_claim_in_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _ResearchBatchClaim,
    ) -> None:
        current = transaction.execute(
            """
            SELECT batch.status, batch.execution_fence,
                   attempt.status AS attempt_status,
                   attempt.generation_pin_id
            FROM research_batches.batches AS batch
            JOIN research_batches.attempts AS attempt ON attempt.batch_id = batch.id
            WHERE batch.id = %s AND attempt.id = %s AND attempt.fence = %s
              AND attempt.lease_expires_at > now()
            FOR UPDATE OF batch, attempt
            """,
            (claim.batch_id, claim.attempt_id, claim.fence),
        ).fetchone()
        if current != {
            "status": "running",
            "execution_fence": claim.fence,
            "attempt_status": "running",
            "generation_pin_id": claim.generation_pin_id,
        }:
            raise RuntimeError("Factor Batch execution was fenced")

    def _record_live_execution_event(
        self,
        claim: _ResearchBatchClaim,
        event: Mapping[str, object],
    ) -> None:
        name = str(event.get("event"))
        task_role: str | None = None
        item_key: str | None = None
        phase: str | None = None
        completed: int | None = None
        total: int | None = None
        reset_started_at = False
        if name == "research_batch_execution_child_started":
            child_pid = event.get("child_pid")
            child_control_path = event.get("child_control_path")
            if not isinstance(child_pid, int) or not isinstance(child_control_path, str):
                raise RuntimeError("Research Batch child identity is invalid")
            with self._database.transaction() as transaction:
                self._activate_starting_claim_in_transaction(
                    transaction,
                    claim,
                    child_pid=child_pid,
                    child_control_path=child_control_path,
                )
            task_role = "preparation"
            phase = "preparing_data"
            reset_started_at = True
        elif name == "research_batch_execution_child_exited":
            child_pid = event.get("child_pid")
            exit_code = event.get("exit_code")
            acknowledged = event.get("acknowledged")
            if (
                not isinstance(child_pid, int)
                or not isinstance(exit_code, int)
                or not isinstance(acknowledged, bool)
            ):
                raise RuntimeError("Research Batch child exit evidence is invalid")
            with self._database.transaction() as transaction:
                updated = transaction.execute(
                    """
                    UPDATE research_batches.attempts
                    SET child_exited_at = now(), child_exit_code = %s,
                        child_acknowledged = %s
                    WHERE id = %s AND batch_id = %s AND fence = %s
                      AND child_pid = %s AND child_exited_at IS NULL
                    """,
                    (
                        exit_code,
                        acknowledged,
                        claim.attempt_id,
                        claim.batch_id,
                        claim.fence,
                        child_pid,
                    ),
                )
                if updated.rowcount != 1:
                    existing = transaction.execute(
                        """
                        SELECT child_exit_code, child_acknowledged
                        FROM research_batches.attempts
                        WHERE id = %s AND batch_id = %s AND fence = %s
                          AND child_pid = %s AND child_exited_at IS NOT NULL
                        """,
                        (claim.attempt_id, claim.batch_id, claim.fence, child_pid),
                    ).fetchone()
                    if existing != {
                        "child_exit_code": exit_code,
                        "child_acknowledged": acknowledged,
                    }:
                        raise RuntimeError("Research Batch child exit was fenced")
            return
        elif name in {
            "research_batch_execution_shared_alpha_factor_started",
            "research_batch_execution_item_started",
        }:
            task_role = str(event.get("task_role"))
            item_key = str(event["item_key"]) if isinstance(event.get("item_key"), str) else None
            phase = str(event.get("phase"))
            completed, total = _live_session_counts(event)
            reset_started_at = True
        elif name in {
            "research_batch_execution_shared_alpha_factor_succeeded",
            "research_batch_execution_shared_alpha_factor_failed",
            "research_batch_execution_shared_alpha_factor_chunk_succeeded",
            "research_batch_execution_item_strategy_chunk_succeeded",
            "research_batch_execution_item_chunk_succeeded",
            "research_batch_execution_item_succeeded",
            "research_batch_execution_item_failed",
        }:
            task_role = str(event["task_role"]) if isinstance(event.get("task_role"), str) else None
            item_key = str(event["item_key"]) if isinstance(event.get("item_key"), str) else None
            phase = str(event["phase"]) if isinstance(event.get("phase"), str) else None
            completed, total = _live_session_counts(event)
        else:
            return
        with self._database.transaction() as transaction:
            if (
                claim.batch_kind == "factor_evaluation"
                and name == "research_batch_execution_item_started"
            ):
                item_ordinal = event.get("item_ordinal")
                if not isinstance(item_ordinal, int):
                    raise RuntimeError("Factor task start ordinal is invalid")
                self._ensure_factor_task_attempt_in_transaction(
                    transaction,
                    claim,
                    item_ordinal,
                )
            current = transaction.execute(
                """
                SELECT current_task_role, current_item_key, current_phase,
                       completed_research_sessions, total_research_sessions
                FROM research_batches.attempts
                WHERE id = %s AND batch_id = %s AND fence = %s
                  AND status = 'running' AND lease_expires_at > now()
                FOR UPDATE
                """,
                (claim.attempt_id, claim.batch_id, claim.fence),
            ).fetchone()
            if current is None:
                raise RuntimeError("Research Batch live progress was fenced")
            if task_role is None:
                task_role = str(current["current_task_role"])
            if item_key is None and task_role not in {"preparation", "shared_alpha_factor"}:
                item_key = (
                    str(current["current_item_key"])
                    if current["current_item_key"] is not None
                    else None
                )
            if phase is None:
                phase = str(current["current_phase"])
            if completed is None and total is None:
                completed = (
                    int(current["completed_research_sessions"])
                    if current["completed_research_sessions"] is not None
                    else None
                )
                total = (
                    int(current["total_research_sessions"])
                    if current["total_research_sessions"] is not None
                    else None
                )
            updated = transaction.execute(
                """
                UPDATE research_batches.attempts AS attempt
                SET current_task_role = %s,
                    current_item_key = %s,
                    current_phase = %s,
                    completed_research_sessions = %s,
                    total_research_sessions = %s,
                    task_started_at = CASE WHEN %s THEN now() ELSE task_started_at END,
                    live_progress_updated_at = now()
                FROM research_batches.batches AS batch
                WHERE attempt.id = %s AND attempt.batch_id = %s
                  AND attempt.fence = %s AND attempt.status = 'running'
                  AND attempt.lease_expires_at > now()
                  AND batch.id = attempt.batch_id AND batch.status = 'running'
                  AND batch.execution_fence = attempt.fence
                """,
                (
                    task_role,
                    item_key,
                    phase,
                    completed,
                    total,
                    reset_started_at,
                    claim.attempt_id,
                    claim.batch_id,
                    claim.fence,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Research Batch live progress was fenced")
            if name == "research_batch_execution_shared_alpha_factor_started":
                shared = transaction.execute(
                    """
                    UPDATE research_batches.progress
                    SET shared_alpha_factor_status = 'running', updated_at = now()
                    WHERE batch_id = %s AND shared_alpha_factor_status = 'pending'
                    """,
                    (claim.batch_id,),
                )
                if shared.rowcount != 1:
                    raise RuntimeError("Shared Alpha-and-Factor live progress did not start")

    def _activate_starting_claim_in_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _ResearchBatchClaim,
        *,
        child_pid: int,
        child_control_path: str,
    ) -> None:
        starting = transaction.execute(
            """
            SELECT ordinal, generation_pin_id, data_generation_id,
                   data_through_session, child_control_path
            FROM research_batches.starting_claims
            WHERE id = %s AND batch_id = %s AND fence = %s
              AND lease_expires_at > now()
            FOR UPDATE
            """,
            (claim.attempt_id, claim.batch_id, claim.fence),
        ).fetchone()
        if starting is None or starting["child_control_path"] != child_control_path:
            raise RuntimeError("Research Batch starting claim was fenced")
        inserted = transaction.execute(
            """
            INSERT INTO research_batches.attempts (
                id, batch_id, ordinal, fence, generation_pin_id,
                data_generation_id, data_through_session, status,
                lease_expires_at, child_pid, child_control_path, child_started_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 'running',
                now() + make_interval(secs => %s), %s, %s, now()
            )
            """,
            (
                claim.attempt_id,
                claim.batch_id,
                starting["ordinal"],
                claim.fence,
                starting["generation_pin_id"],
                starting["data_generation_id"],
                starting["data_through_session"],
                self._lease_seconds,
                child_pid,
                child_control_path,
            ),
        )
        if inserted.rowcount != 1:
            raise RuntimeError("Research Batch Attempt activation was fenced")
        if claim.batch_kind == "factor_evaluation":
            self._ensure_factor_task_attempt_in_transaction(
                transaction,
                claim,
                claim.items[0][0],
            )
        deleted = transaction.execute(
            """
            DELETE FROM research_batches.starting_claims
            WHERE id = %s AND batch_id = %s AND fence = %s
            """,
            (claim.attempt_id, claim.batch_id, claim.fence),
        )
        if deleted.rowcount != 1:
            raise RuntimeError("Research Batch starting claim activation was fenced")

    def _ensure_factor_task_attempt_in_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _ResearchBatchClaim,
        item_ordinal: int,
    ) -> None:
        running = transaction.execute(
            """
            SELECT item_ordinal
            FROM research_batches.task_attempts
            WHERE batch_id = %s AND status = 'running'
            FOR UPDATE
            """,
            (claim.batch_id,),
        ).fetchone()
        if running is not None:
            if int(running["item_ordinal"]) != item_ordinal:
                raise RuntimeError("A different Factor task Attempt is still active")
            return
        ordinal_row = transaction.execute(
            """
            SELECT coalesce(max(ordinal), 0) + 1 AS ordinal
            FROM research_batches.task_attempts
            WHERE batch_id = %s AND item_ordinal = %s
            """,
            (claim.batch_id, item_ordinal),
        ).fetchone()
        assert ordinal_row is not None
        ordinal = int(ordinal_row["ordinal"])
        if ordinal > MAX_FACTOR_TASK_ATTEMPTS:
            raise RuntimeError("Factor task retry limit was exceeded")
        inserted = transaction.execute(
            """
            INSERT INTO research_batches.task_attempts (
                id, batch_id, item_ordinal, task_key, task_role, ordinal,
                batch_attempt_id, fence, status
            ) SELECT %s, %s, %s, item.item_key, 'factor', %s, %s, %s, 'running'
            FROM research_batches.items AS item
            WHERE item.batch_id = %s AND item.ordinal = %s
            """,
            (
                f"factor_task_attempt_{uuid4().hex[:20]}",
                claim.batch_id,
                item_ordinal,
                ordinal,
                claim.attempt_id,
                claim.fence,
                claim.batch_id,
                item_ordinal,
            ),
        )
        if inserted.rowcount != 1:
            raise RuntimeError("Factor task Attempt item is unavailable")

    def _set_shared_alpha_factor_status(
        self,
        claim: _ResearchBatchClaim,
        status: str,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("Shared Alpha-and-Factor status is invalid")
        with self._database.transaction() as transaction:
            self._authorize_claim_in_transaction(transaction, claim)
            updated = transaction.execute(
                """
                UPDATE research_batches.progress
                SET shared_alpha_factor_status = %s, updated_at = now()
                WHERE batch_id = %s AND shared_alpha_factor_status = 'running'
                """,
                (status, claim.batch_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Shared Alpha-and-Factor progress did not advance")

    def _complete_item_in_transaction(
        self,
        transaction: PostgresTransaction,
        claim: _ResearchBatchClaim,
        ordinal: int,
        outcome: str,
        public_reason: str | None,
        diagnostic: ResearchBatchDiagnostic | None,
    ) -> None:
        if outcome not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("Research Batch item outcome is invalid")
        self._authorize_claim_in_transaction(transaction, claim)
        if diagnostic is None and public_reason is not None:
            diagnostic = ResearchBatchDiagnostic(
                code="RESEARCH_ITEM_FAILED",
                category="execution",
                message=public_reason,
            )
        if claim.batch_kind == "factor_evaluation":
            task_attempt = transaction.execute(
                """
                UPDATE research_batches.task_attempts
                SET status = %s, finished_at = now(),
                    failure_reason = %s, failure_diagnostic = %s
                WHERE batch_id = %s AND item_ordinal = %s
                  AND batch_attempt_id = %s AND fence = %s
                  AND status = 'running'
                """,
                (
                    "succeeded" if outcome == "succeeded" else "failed",
                    None if outcome == "succeeded" else (public_reason or "FactorTaskFailed"),
                    (
                        None
                        if outcome == "succeeded"
                        else Jsonb(diagnostic.model_dump(mode="json"))
                    ),
                    claim.batch_id,
                    ordinal,
                    claim.attempt_id,
                    claim.fence,
                ),
            )
            if task_attempt.rowcount != 1:
                raise RuntimeError("Factor task Attempt completion was fenced")
        updated = transaction.execute(
            """
            UPDATE research_batches.items
            SET outcome = %s,
                diagnostic = %s
            WHERE batch_id = %s AND ordinal = %s AND outcome IS NULL
            """,
            (
                outcome,
                (None if diagnostic is None else Jsonb(diagnostic.model_dump(mode="json"))),
                claim.batch_id,
                ordinal,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Research Batch item task was already complete")
        progress = transaction.execute(
            """
            SELECT completed_items, total_items
            FROM research_batches.progress
            WHERE batch_id = %s
            FOR UPDATE
            """,
            (claim.batch_id,),
        ).fetchone()
        if progress is None:
            raise RuntimeError("Research Batch durable progress is missing")
        completed = int(progress["completed_items"]) + 1
        if completed > int(progress["total_items"]):
            raise RuntimeError("Research Batch durable progress exceeded its total")
        transaction.execute(
            """
            UPDATE research_batches.progress
            SET completed_items = %s, updated_at = now()
            WHERE batch_id = %s
            """,
            (completed, claim.batch_id),
        )

    def _fail_running_items(
        self,
        claim: _ResearchBatchClaim,
        error: Exception,
        *,
        diagnostic: ResearchBatchDiagnostic | None = None,
    ) -> None:
        for ordinal, _item_key, run_claim in claim.items:
            self._research_runs.fail_batch_owned_item(
                run_claim,
                error,
                authorize_batch=lambda transaction: self._authorize_claim_in_transaction(
                    transaction, claim
                ),
                complete_batch_item=lambda transaction, outcome, reason, ordinal=ordinal: (
                    self._complete_item_in_transaction(
                        transaction,
                        claim,
                        ordinal,
                        outcome,
                        reason,
                        diagnostic,
                    )
                ),
            )

    def _finish_interrupted_starting_claim(
        self,
        claim: _ResearchBatchClaim,
        error: Exception,
    ) -> bool:
        with self._database.transaction() as transaction:
            starting = transaction.execute(
                """
                SELECT child_control_path
                FROM research_batches.starting_claims
                WHERE id = %s AND batch_id = %s AND fence = %s
                FOR UPDATE
                """,
                (claim.attempt_id, claim.batch_id, claim.fence),
            ).fetchone()
            if starting is None:
                return False
            if not _confirm_child_exited(str(starting["child_control_path"])):
                raise RuntimeError("Interrupted Batch starting child exit is not confirmed")
            incomplete = transaction.execute(
                """
                SELECT ordinal, research_run_id
                FROM research_batches.items
                WHERE batch_id = %s AND outcome IS NULL
                ORDER BY ordinal
                FOR UPDATE
                """,
                (claim.batch_id,),
            ).fetchall()
            self._research_runs.reset_incomplete_batch_owned_executions_in_transaction(
                transaction,
                [str(item["research_run_id"]) for item in incomplete],
            )
            if claim.batch_kind == "factor_evaluation":
                batch_status = "queued"
            else:
                diagnostic = _exception_diagnostic(error)
                for item in incomplete:
                    self._fail_recovered_factor_item_in_transaction(
                        transaction,
                        batch_id=claim.batch_id,
                        item_ordinal=int(item["ordinal"]),
                        run_id=str(item["research_run_id"]),
                        diagnostic=diagnostic,
                    )
                batch_status = "failed"
            deleted = transaction.execute(
                """
                DELETE FROM research_batches.starting_claims
                WHERE id = %s AND batch_id = %s AND fence = %s
                """,
                (claim.attempt_id, claim.batch_id, claim.fence),
            )
            if deleted.rowcount != 1:
                raise RuntimeError("Interrupted Batch starting claim was fenced")
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )
            updated = transaction.execute(
                """
                UPDATE research_batches.batches
                SET status = %s, updated_at = now()
                WHERE id = %s AND status = 'running' AND execution_fence = %s
                """,
                (batch_status, claim.batch_id, claim.fence),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Interrupted Batch starting recovery was fenced")
            return True

    def _finish_interrupted_factor_attempt(
        self,
        claim: _ResearchBatchClaim,
        error: Exception,
    ) -> None:
        policy = _factor_task_failure_policy(error)
        attempt_diagnostic = _exception_diagnostic(error)
        with self._database.transaction() as transaction:
            self._authorize_claim_in_transaction(transaction, claim)
            child = transaction.execute(
                """
                SELECT child_control_path, child_exited_at
                FROM research_batches.attempts
                WHERE id = %s AND batch_id = %s AND fence = %s
                FOR UPDATE
                """,
                (claim.attempt_id, claim.batch_id, claim.fence),
            ).fetchone()
            if (
                child is None
                or child["child_exited_at"] is None
                or not _confirm_child_exited(str(child["child_control_path"]))
            ):
                raise RuntimeError("Interrupted Factor child exit is not confirmed")
            self._close_factor_attempt_in_transaction(
                transaction,
                batch_id=claim.batch_id,
                attempt_id=claim.attempt_id,
                fence=claim.fence,
                generation_pin_id=claim.generation_pin_id,
                policy=policy,
                diagnostic=attempt_diagnostic,
                require_expired=False,
            )

    def _close_factor_attempt_in_transaction(
        self,
        transaction: PostgresTransaction,
        *,
        batch_id: str,
        attempt_id: str,
        fence: int,
        generation_pin_id: str,
        policy: _FactorTaskFailurePolicy,
        diagnostic: ResearchBatchDiagnostic,
        require_expired: bool,
    ) -> None:
        task_attempt = transaction.execute(
            """
            SELECT id, item_ordinal, ordinal
            FROM research_batches.task_attempts
            WHERE batch_id = %s AND batch_attempt_id = %s
              AND fence = %s AND status = 'running'
            FOR UPDATE
            """,
            (batch_id, attempt_id, fence),
        ).fetchone()
        if task_attempt is not None:
            closed_task = transaction.execute(
                """
                UPDATE research_batches.task_attempts
                SET status = 'failed', finished_at = now(),
                    failure_reason = %s, failure_diagnostic = %s
                WHERE id = %s AND status = 'running'
                """,
                (
                    policy.attempt_reason,
                    Jsonb(diagnostic.model_dump(mode="json")),
                    task_attempt["id"],
                ),
            )
            if closed_task.rowcount != 1:
                raise RuntimeError("Factor task Attempt closure was fenced")
        closed_attempt = transaction.execute(
            """
            UPDATE research_batches.attempts
            SET status = 'failed', heartbeat_at = now(), lease_expires_at = now(),
                finished_at = now(), failure_reason = %s,
                failure_diagnostic = %s,
                current_task_role = NULL, current_item_key = NULL,
                current_phase = NULL, completed_research_sessions = NULL,
                total_research_sessions = NULL, task_started_at = NULL,
                live_progress_updated_at = NULL
            WHERE id = %s AND batch_id = %s AND fence = %s
              AND status = 'running'
              AND (%s = false OR lease_expires_at <= now())
            """,
            (
                policy.attempt_reason,
                Jsonb(diagnostic.model_dump(mode="json")),
                attempt_id,
                batch_id,
                fence,
                require_expired,
            ),
        )
        if closed_attempt.rowcount != 1:
            raise RuntimeError("Factor Batch Attempt closure was fenced")
        incomplete = transaction.execute(
            """
            SELECT ordinal, research_run_id
            FROM research_batches.items
            WHERE batch_id = %s AND outcome IS NULL
            ORDER BY ordinal
            FOR UPDATE
            """,
            (batch_id,),
        ).fetchall()
        self._research_runs.reset_incomplete_batch_owned_executions_in_transaction(
            transaction,
            [str(item["research_run_id"]) for item in incomplete],
        )
        terminal_task = task_attempt is not None and (
            not policy.retryable
            or int(task_attempt["ordinal"]) >= MAX_FACTOR_TASK_ATTEMPTS
        )
        if terminal_task:
            selected = next(
                (
                    item
                    for item in incomplete
                    if int(item["ordinal"]) == int(task_attempt["item_ordinal"])
                ),
                None,
            )
            if selected is not None:
                exhausted = (
                    policy.retryable
                    and int(task_attempt["ordinal"]) >= MAX_FACTOR_TASK_ATTEMPTS
                )
                self._fail_recovered_factor_item_in_transaction(
                    transaction,
                    batch_id=batch_id,
                    item_ordinal=int(selected["ordinal"]),
                    run_id=str(selected["research_run_id"]),
                    diagnostic=ResearchBatchDiagnostic(
                        code=(
                            "FACTOR_TASK_RETRY_EXHAUSTED"
                            if exhausted
                            else "FACTOR_TASK_PERMANENT_FAILURE"
                        ),
                        category=("infrastructure" if exhausted else "execution"),
                        message=(
                            FACTOR_TASK_INFRASTRUCTURE_PUBLIC_REASON
                            if exhausted
                            else policy.public_reason
                        ),
                    ),
                )
        self._dataset_lifecycle.release_pin_in_transaction(
            transaction,
            generation_pin_id,
            owner_id=attempt_id,
        )
        remaining = transaction.execute(
            """
            SELECT count(*) AS count
            FROM research_batches.items
            WHERE batch_id = %s AND outcome IS NULL
            """,
            (batch_id,),
        ).fetchone()
        assert remaining is not None
        status = (
            "queued"
            if int(remaining["count"]) > 0
            else self._terminal_status_from_items_in_transaction(transaction, batch_id)
        )
        updated = transaction.execute(
            """
            UPDATE research_batches.batches
            SET status = %s, updated_at = now()
            WHERE id = %s AND status = 'running' AND execution_fence = %s
            """,
            (status, batch_id, fence),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Factor Batch recovery was fenced")

    def _finish_attempt(
        self,
        claim: _ResearchBatchClaim,
        *,
        failed: bool,
        error: Exception | None = None,
    ) -> None:
        with self._database.transaction() as transaction:
            child = transaction.execute(
                """
                SELECT child_control_path, child_exited_at, child_acknowledged
                FROM research_batches.attempts
                WHERE id = %s AND batch_id = %s AND fence = %s
                FOR UPDATE
                """,
                (claim.attempt_id, claim.batch_id, claim.fence),
            ).fetchone()
            if (
                child is None
                or child["child_exited_at"] is None
                or child["child_acknowledged"] is not True
                or not _confirm_child_exited(str(child["child_control_path"]))
            ):
                raise RuntimeError("Research Batch acknowledged child exit is not confirmed")
            item_rows = transaction.execute(
                """
                SELECT research_run_id
                FROM research_batches.items
                WHERE batch_id = %s
                ORDER BY ordinal
                """,
                (claim.batch_id,),
            ).fetchall()
            run_ids = [str(row["research_run_id"]) for row in item_rows]
            child_statuses = self._research_runs.project_child_statuses_in_transaction(
                transaction,
                run_ids,
            )
            statuses = [child_statuses[run_id] for run_id in run_ids]
            succeeded = sum(status == "succeeded" for status in statuses)
            terminal = sum(status in {"succeeded", "failed", "cancelled"} for status in statuses)
            if terminal != len(statuses):
                raise RuntimeError(
                    "Research Batch Attempt cannot finish before every child is terminal"
                )
            if succeeded == len(statuses):
                batch_status = "succeeded"
            elif succeeded:
                batch_status = "completed_with_failures"
            else:
                batch_status = "failed"
            finished_attempt = transaction.execute(
                """
                UPDATE research_batches.attempts
                SET status = %s, heartbeat_at = now(), lease_expires_at = now(),
                    finished_at = now(), failure_reason = %s,
                    failure_diagnostic = %s,
                    current_task_role = NULL, current_item_key = NULL,
                    current_phase = NULL, completed_research_sessions = NULL,
                    total_research_sessions = NULL, task_started_at = NULL,
                    live_progress_updated_at = NULL
                WHERE id = %s AND batch_id = %s AND fence = %s
                  AND status = 'running'
                """,
                (
                    "failed" if failed else "succeeded",
                    None if error is None else type(error).__name__,
                    (
                        None
                        if error is None
                        else Jsonb(_exception_diagnostic(error).model_dump(mode="json"))
                    ),
                    claim.attempt_id,
                    claim.batch_id,
                    claim.fence,
                ),
            )
            if finished_attempt.rowcount != 1:
                raise RuntimeError("Research Batch Attempt completion was fenced")
            finished_batch = transaction.execute(
                """
                UPDATE research_batches.batches
                SET status = %s, updated_at = now()
                WHERE id = %s AND execution_fence = %s AND status = 'running'
                """,
                (batch_status, claim.batch_id, claim.fence),
            )
            if finished_batch.rowcount != 1:
                raise RuntimeError("Research Batch completion was fenced")
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )
            _refresh_progress_in_transaction(
                transaction,
                claim.batch_id,
            )

    def _locked_receipt(
        self,
        request_id: str,
        fingerprint: str,
    ) -> ResearchBatchDetail | None:
        with self._database.transaction() as transaction:
            _lock_admission(transaction, request_id)
            receipt = _receipt(transaction, request_id)
            return None if receipt is None else _replayed_receipt(receipt, fingerprint)


def _child_commands(
    command: ResearchBatchAdmissionCommand,
) -> list[tuple[str, ResearchRunAdmissionCommand]]:
    common = {
        "folder_id": BATCH_RESEARCH_FOLDER_ID,
        "start_date": command.start_date,
        "end_date": command.end_date,
        "universe": command.universe,
        "neutralization": command.neutralization,
    }
    if isinstance(command, FactorEvaluationBatchAdmissionCommand):
        return [
            (
                item.item_key,
                FactorEvaluationAdmissionCommand(
                    request_id=f"batch-factor-{ordinal}",
                    research_kind="factor_evaluation",
                    name=item.name,
                    formula=item.formula,
                    hypothesis=item.hypothesis,
                    **common,
                ),
            )
            for ordinal, item in enumerate(command.factors, start=1)
        ]
    assert isinstance(command, StrategySweepBatchAdmissionCommand)
    return [
        (
            item.item_key,
            StrategyBacktestAdmissionCommand(
                request_id=f"batch-strategy-{ordinal}",
                research_kind="strategy_backtest",
                name=item.name,
                formula=command.alpha.formula,
                hypothesis=command.alpha.hypothesis,
                holdings_count=item.holdings_count,
                rebalance_every_sessions=item.rebalance_every_sessions,
                **common,
            ),
        )
        for ordinal, item in enumerate(command.strategies, start=1)
    ]


def _validate_unique_item_keys(command: ResearchBatchAdmissionCommand) -> None:
    items = (
        command.factors
        if isinstance(command, FactorEvaluationBatchAdmissionCommand)
        else command.strategies
    )
    seen: dict[str, int] = {}
    for ordinal, item in enumerate(items, start=1):
        previous = seen.get(item.item_key)
        if previous is not None:
            raise ResearchBatchAdmissionRejected(
                [
                    ResearchBatchAdmissionIssue(
                        code="DUPLICATE_ITEM_KEY",
                        field=f"items[{ordinal - 1}].item_key",
                        item_key=item.item_key,
                        message=(f"item_key conflicts with ordinal {previous}: {item.item_key}"),
                    )
                ]
            )
        seen[item.item_key] = ordinal


def _validate_duplicate_computation(
    command: ResearchBatchAdmissionCommand,
    prepared: Sequence[PreparedResearchRunAdmission],
) -> None:
    if isinstance(command, FactorEvaluationBatchAdmissionCommand):
        seen: dict[bytes, str] = {}
        for item, child in zip(command.factors, prepared, strict=True):
            identity = canonical_json_bytes(child.immutable_input.alpha_expression)
            conflicting = seen.get(identity)
            if conflicting is not None:
                raise ResearchBatchAdmissionRejected(
                    [
                        ResearchBatchAdmissionIssue(
                            code="DUPLICATE_FACTOR_EXPRESSION",
                            field="factors",
                            item_key=item.item_key,
                            message=(
                                "Canonical Factor Expression duplicates "
                                f"item_key {conflicting} and {item.item_key}"
                            ),
                        )
                    ]
                )
            seen[identity] = item.item_key
        return
    assert isinstance(command, StrategySweepBatchAdmissionCommand)
    seen_strategy: dict[tuple[int, int], str] = {}
    for item in command.strategies:
        identity = (item.holdings_count, item.rebalance_every_sessions)
        conflicting = seen_strategy.get(identity)
        if conflicting is not None:
            raise ResearchBatchAdmissionRejected(
                [
                    ResearchBatchAdmissionIssue(
                        code="DUPLICATE_STRATEGY_PARAMETERS",
                        field="strategies",
                        item_key=item.item_key,
                        message=(
                            "Strategy parameters duplicate "
                            f"item_key {conflicting} and {item.item_key}"
                        ),
                    )
                ]
            )
        seen_strategy[identity] = item.item_key


def _child_issues(
    command: ResearchBatchAdmissionCommand,
    ordinal: int,
    item_key: str,
    error: ResearchRunAdmissionRejected,
) -> list[ResearchBatchAdmissionIssue]:
    if isinstance(command, FactorEvaluationBatchAdmissionCommand):
        prefix = f"factors[{ordinal - 1}]"
    elif any(issue.field == "formula" for issue in error.issues):
        prefix = "alpha"
    else:
        prefix = f"strategies[{ordinal - 1}]"
    return [
        ResearchBatchAdmissionIssue(
            code=issue.code,
            field=f"{prefix}.{issue.field}",
            item_key=(item_key if prefix.startswith("factors") else None),
            message=issue.message,
            range=issue.range,
            details=issue.details,
        )
        for issue in error.issues
    ]


def _deduplicated_issues(
    issues: Sequence[ResearchBatchAdmissionIssue],
) -> list[ResearchBatchAdmissionIssue]:
    unique: dict[bytes, ResearchBatchAdmissionIssue] = {}
    for issue in issues:
        identity = canonical_json_bytes(issue.model_dump(mode="json"))
        unique.setdefault(identity, issue)
    return list(unique.values())


def _scope(children: Sequence[PreparedResearchRunAdmission]) -> ResearchBatchScope:
    if not children:
        raise ValueError("Research Batch requires child Runs")
    frozen = children[0].immutable_input
    return ResearchBatchScope(
        start_date=frozen.requested_start_date,
        end_date=frozen.requested_end_date,
        universe=frozen.universe,
        neutralization=frozen.neutralization,
        numeric_execution_contract=frozen.numeric_execution_contract,
        semantic_versions=frozen.semantic_versions,
        data_generation_id=frozen.data_admission.generation_manifest_sha256,
        data_through_session=frozen.data_admission.data_through_session,
    )


def _admission_fingerprint(command: ResearchBatchAdmissionCommand) -> str:
    value = {
        "action": "research-batches.admit/v1",
        "command": command.model_dump(mode="json", exclude={"request_id"}),
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _lock_admission(transaction: PostgresTransaction, request_id: str) -> None:
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"research_batches.admit:{request_id}",),
    ).fetchone()


def _receipt(
    transaction: PostgresTransaction,
    request_id: str,
) -> Mapping[str, object] | None:
    return transaction.execute(
        """
        SELECT request_fingerprint, outcome
        FROM research_batches.admission_receipts
        WHERE request_id = %s
        """,
        (request_id,),
    ).fetchone()


def _replayed_receipt(
    receipt: Mapping[str, object],
    fingerprint: str,
) -> ResearchBatchDetail:
    if receipt["request_fingerprint"] != fingerprint:
        raise ResearchBatchAdmissionConflict("Research Batch request_id conflicts")
    return ResearchBatchDetail.model_validate(receipt["outcome"])


def _summary_in_transaction(
    transaction: PostgresTransaction,
    batch_id: str,
) -> ResearchBatchSummary:
    row = _batch_projection_row(transaction, batch_id)
    if row is None:
        raise RuntimeError("Research Batch projection is missing")
    return _summary_from_row(row)


def _summary_from_row(row: Mapping[str, object]) -> ResearchBatchSummary:
    return ResearchBatchSummary(
        id=str(row["id"]),
        batch_kind=str(row["batch_kind"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        scope=ResearchBatchScope.model_validate(row["scope"]),
        progress=_public_progress(row),
        execution_timing=_execution_timing(row),
    )


def _detail_in_transaction(
    transaction: PostgresTransaction,
    batch_id: str,
    *,
    research_runs: ResearchRunService,
) -> ResearchBatchDetail:
    row = _batch_projection_row(transaction, batch_id)
    if row is None:
        raise RuntimeError("Research Batch projection is missing")
    item_rows = transaction.execute(
        """
        SELECT item.ordinal, item.item_key, item.research_run_id,
               item.dependency_role, item.outcome, item.diagnostic,
               item.run_deleted_at AS deleted_at,
               (
                   SELECT count(*)
                   FROM research_batches.task_attempts AS task_attempt
                   WHERE task_attempt.batch_id = item.batch_id
                     AND task_attempt.item_ordinal = item.ordinal
               ) AS task_attempt_count
        FROM research_batches.items AS item
        WHERE item.batch_id = %s
        ORDER BY item.ordinal
        """,
        (batch_id,),
    ).fetchall()
    run_ids = [str(item["research_run_id"]) for item in item_rows]
    child_statuses = research_runs.project_child_statuses_in_transaction(
        transaction,
        run_ids,
    )
    attempt_row = transaction.execute(
        """
        SELECT id, ordinal, status, started_at, heartbeat_at, lease_expires_at,
               finished_at,
               failure_diagnostic, current_task_role, current_item_key,
               current_phase, completed_research_sessions,
               total_research_sessions, task_started_at,
               live_progress_updated_at,
               CURRENT_TIMESTAMP AS observed_at
        FROM research_batches.attempts
        WHERE batch_id = %s
        ORDER BY ordinal DESC
        LIMIT 1
        """,
        (batch_id,),
    ).fetchone()
    summary = _summary_in_transaction(transaction, batch_id)
    return ResearchBatchDetail(
        **summary.model_dump(),
        attempt=_attempt_summary(attempt_row),
        live_progress=_live_progress(attempt_row, str(row["status"])),
        items=[
            ResearchBatchItemSummary.model_validate(
                {
                    **item,
                    "status": child_statuses[str(item["research_run_id"])],
                    "run_availability": (
                        "deleted" if item["deleted_at"] is not None else "available"
                    ),
                }
            )
            for item in item_rows
        ],
    )


def _batch_projection_row(
    transaction: PostgresTransaction,
    batch_id: str,
) -> Mapping[str, object] | None:
    return transaction.execute(
        """
        SELECT batch.id, batch.batch_kind, batch.status, batch.scope,
               batch.created_at, progress.completed_items, progress.total_items,
               progress.shared_alpha_factor_status,
               timing.execution_started_at, timing.execution_finished_at,
               CURRENT_TIMESTAMP AS execution_observed_at
        FROM research_batches.batches AS batch
        JOIN research_batches.progress AS progress ON progress.batch_id = batch.id
        LEFT JOIN LATERAL (
            SELECT min(attempt.started_at) AS execution_started_at,
                   max(attempt.finished_at) AS execution_finished_at
            FROM research_batches.attempts AS attempt
            WHERE attempt.batch_id = batch.id
        ) AS timing ON true
        WHERE batch.id = %s
        """,
        (batch_id,),
    ).fetchone()


def _public_progress(
    row: Mapping[str, object],
) -> FactorEvaluationBatchProgress | StrategySweepBatchProgress:
    if row["batch_kind"] == "factor_evaluation":
        return FactorEvaluationBatchProgress(
            completed_factor_tasks=int(row["completed_items"]),
            total_factor_tasks=int(row["total_items"]),
        )
    if row["batch_kind"] == "strategy_sweep":
        return StrategySweepBatchProgress(
            shared_alpha_factor_status=str(row["shared_alpha_factor_status"]),
            completed_strategy_tasks=int(row["completed_items"]),
            total_strategy_tasks=int(row["total_items"]),
        )
    raise RuntimeError("Research Batch Kind is invalid")


def _execution_timing(row: Mapping[str, object]) -> ResearchBatchExecutionTiming:
    started = row["execution_started_at"]
    status = str(row["status"])
    terminal = status in {"succeeded", "completed_with_failures", "failed", "cancelled"}
    finished = row["execution_finished_at"] if terminal else None
    observed = row["execution_observed_at"]
    elapsed = None
    if isinstance(started, datetime):
        boundary = finished if isinstance(finished, datetime) else observed
        if isinstance(boundary, datetime):
            elapsed = max(0.0, (boundary - started).total_seconds())
    return ResearchBatchExecutionTiming(
        started_at=started if isinstance(started, datetime) else None,
        finished_at=finished if isinstance(finished, datetime) else None,
        elapsed_seconds=elapsed,
        is_final=terminal,
    )


def _attempt_summary(
    row: Mapping[str, object] | None,
) -> ResearchBatchAttemptSummary | None:
    if row is None:
        return None
    diagnostic = row["failure_diagnostic"]
    return ResearchBatchAttemptSummary(
        id=str(row["id"]),
        number=int(row["ordinal"]),
        status=str(row["status"]),
        started_at=row["started_at"],
        finished_at=(row["finished_at"] if isinstance(row["finished_at"], datetime) else None),
        diagnostic=(
            ResearchBatchDiagnostic.model_validate(diagnostic)
            if isinstance(diagnostic, Mapping)
            else None
        ),
    )


def _live_progress(
    row: Mapping[str, object] | None,
    batch_status: str,
) -> ResearchBatchLiveProgress | None:
    if (
        row is None
        or batch_status not in {"running", "cancelling"}
        or row["status"] != "running"
        or not isinstance(row["current_task_role"], str)
        or not isinstance(row["current_phase"], str)
        or not isinstance(row["task_started_at"], datetime)
        or not isinstance(row["live_progress_updated_at"], datetime)
        or not isinstance(row["observed_at"], datetime)
        or not isinstance(row["lease_expires_at"], datetime)
        or row["lease_expires_at"] <= row["observed_at"]
    ):
        return None
    completed = row["completed_research_sessions"]
    total = row["total_research_sessions"]
    elapsed = max(0.0, (row["observed_at"] - row["task_started_at"]).total_seconds())
    percentage = 0.0
    remaining: int | None = None
    if isinstance(completed, int) and isinstance(total, int) and total > 0:
        percentage = min(100.0, max(0.0, completed / total * 100.0))
        if 0 < completed < total and elapsed > 0:
            remaining = max(1, math.ceil(elapsed / completed * (total - completed)))
    elif row["current_phase"] == "finalizing":
        percentage = 100.0
    return ResearchBatchLiveProgress(
        attempt_number=int(row["ordinal"]),
        task_role=str(row["current_task_role"]),
        item_key=(
            str(row["current_item_key"]) if isinstance(row["current_item_key"], str) else None
        ),
        phase=str(row["current_phase"]),
        completed_research_sessions=(completed if isinstance(completed, int) else None),
        total_research_sessions=total if isinstance(total, int) else None,
        estimated_percentage=percentage,
        elapsed_seconds=elapsed,
        remaining_duration_estimate_seconds=remaining,
        observed_at=row["live_progress_updated_at"],
    )


def _refresh_progress_in_transaction(
    transaction: PostgresTransaction,
    batch_id: str,
) -> None:
    rows = transaction.execute(
        """
        SELECT outcome
        FROM research_batches.items
        WHERE batch_id = %s
        ORDER BY ordinal
        """,
        (batch_id,),
    ).fetchall()
    completed = sum(row["outcome"] is not None for row in rows)
    progress = transaction.execute(
        """
        SELECT completed_items, total_items
        FROM research_batches.progress
        WHERE batch_id = %s
        FOR UPDATE
        """,
        (batch_id,),
    ).fetchone()
    if (
        progress is None
        or completed != int(progress["completed_items"])
        or len(rows) != int(progress["total_items"])
    ):
        raise RuntimeError("Research Batch durable progress is inconsistent")
    transaction.execute(
        """
        UPDATE research_batches.progress
        SET updated_at = now()
        WHERE batch_id = %s
        """,
        (batch_id,),
    )


def _live_session_counts(
    event: Mapping[str, object],
) -> tuple[int | None, int | None]:
    completed = event.get("completed_research_sessions")
    total = event.get("total_research_sessions")
    if completed is None and total is None:
        return None, None
    if (
        not isinstance(completed, int)
        or isinstance(completed, bool)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total <= 0
        or completed < 0
        or completed > total
    ):
        raise RuntimeError("Research Batch live session progress is invalid")
    return completed, total


def _message_diagnostic(message: Mapping[str, object]) -> ResearchBatchDiagnostic:
    category = str(message.get("category"))
    public_messages = {
        "Factor item calculation failed.",
        "Strategy item calculation failed.",
        "Shared Alpha-and-Factor calculation failed.",
    }
    candidate = str(message.get("message"))
    public_message = (
        candidate if candidate in public_messages else "Research Batch item execution failed."
    )
    return ResearchBatchDiagnostic(
        code=(
            "RESEARCH_ITEM_CALCULATION_FAILED"
            if category == "calculation"
            else "RESEARCH_ITEM_EXECUTION_FAILED"
        ),
        category="calculation" if category == "calculation" else "execution",
        message=public_message,
    )


def _factor_task_failure_policy(error: Exception) -> _FactorTaskFailurePolicy:
    if isinstance(
        error,
        (
            ResearchBatchChildLost,
            PublicationUnavailableError,
            OperationalError,
            PoolTimeout,
            ConnectionError,
            TimeoutError,
        ),
    ):
        return _FactorTaskFailurePolicy(
            attempt_reason=FACTOR_TASK_INFRASTRUCTURE_FAILURE,
            public_reason=FACTOR_TASK_INFRASTRUCTURE_PUBLIC_REASON,
            retryable=True,
        )
    return _FactorTaskFailurePolicy(
        attempt_reason=FACTOR_TASK_PERMANENT_FAILURE,
        public_reason=FACTOR_TASK_PERMANENT_PUBLIC_REASON,
        retryable=False,
    )


def _exception_diagnostic(error: Exception) -> ResearchBatchDiagnostic:
    if _factor_task_failure_policy(error).retryable:
        return ResearchBatchDiagnostic(
            code="RESEARCH_BATCH_INFRASTRUCTURE_UNAVAILABLE",
            category="infrastructure",
            message="Research Batch execution lost required infrastructure.",
        )
    if isinstance(error, MemoryError):
        return ResearchBatchDiagnostic(
            code="RESEARCH_BATCH_RESOURCE_EXHAUSTED",
            category="resource_exhausted",
            message="Research Batch execution exceeded its resource limit.",
        )
    return ResearchBatchDiagnostic(
        code="RESEARCH_BATCH_EXECUTION_FAILED",
        category="execution",
        message="Research Batch execution failed.",
    )


def _encode_cursor(summary: ResearchBatchSummary) -> str:
    payload = json.dumps(
        {"created_at": summary.created_at.isoformat(), "id": summary.id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(urlsafe_b64decode(padded).decode())
        if (
            set(value) != {"created_at", "id"}
            or not isinstance(value["id"], str)
            or not value["id"]
        ):
            raise ValueError
        created_at = datetime.fromisoformat(value["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, value["id"]
    except (Base64DecodeError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise ValueError("Research Batch cursor is invalid") from None
