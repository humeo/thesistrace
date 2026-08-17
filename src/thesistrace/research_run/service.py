from __future__ import annotations

import hashlib
import json
import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from uuid import uuid4

from psycopg import OperationalError
from psycopg.errors import OutOfMemory
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout
from pydantic import ValidationError

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.alpha_language import CompiledAlpha, FormulaCompilationError
from thesistrace.daily_track import DailyTrackSummary, TrackingOrigin
from thesistrace.data import (
    FINANCIAL_FIELDS,
    DatasetAdmissionSnapshot,
    DatasetLifecycle,
    DatasetWarmupUnavailable,
    GenerationStoreError,
    MountedGenerationStore,
)
from thesistrace.publication import (
    PreparedPublication,
    Publication,
    PublicationNotFoundError,
    PublicationPreparationError,
    PublicationUnavailableError,
    PublicationVerificationError,
    PublishedRef,
    lock_publication_mutation,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.alpha_expression import (
    MAX_ALPHA_RUN_ESTIMATED_WORK,
    estimate_alpha_run_work,
)
from thesistrace.research_kernel.kernel_run import (
    InsufficientCalculationWarmupError,
    KernelRunError,
    RunInput,
)
from thesistrace.research_kernel.kernel_run import run as run_kernel
from thesistrace.research_kernel.numeric import (
    NUMERIC_CONTRACT_ID,
    NumericContractError,
    require_current_numeric_contract,
)
from thesistrace.research_run.models import (
    AlphaAdmissionFacts,
    DataAdmissionFacts,
    ImmutableRunInput,
    OrganizeResearchRunCommand,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionIssue,
    ResearchRunAuthorableInput,
    ResearchRunCancelCommand,
    ResearchRunDetail,
    ResearchRunList,
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
from thesistrace.research_series import AlignedResearchData

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
INSUFFICIENT_WARMUP_PUBLIC_REASON = (
    "Selected data does not contain the complete Calculation Warm-up."
)
SELECTED_DATA_INVALID_PUBLIC_REASON = (
    "Current data cannot execute the requested Research Period."
)
RETRYABLE_FAILURES = (
    INFRASTRUCTURE_FAILURE,
    RESOURCE_EXHAUSTED_FAILURE,
    WORKER_LOST_FAILURE,
)
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
    "kernel": "kernel-v1",
}


@dataclass(frozen=True)
class _ExecutionClaim:
    run_id: str
    attempt_id: str
    fence: int
    generation_pin_id: str
    data_generation_id: str
    data_through_session: str
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
                    raise ResearchRunAdmissionConflict(
                        "ResearchRun request_id conflicts"
                    )
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
        immutable_input = _admitted_input(command, compiled, snapshot)
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
                    raise ResearchRunAdmissionConflict(
                        "ResearchRun request_id conflicts"
                    )
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
                    Jsonb(immutable_input.model_dump(mode="json")),
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
    ) -> bool:
        self._require_execution_dependencies()
        claim = self._claim_next()
        if claim is None:
            return False
        if on_claim is not None:
            on_claim(claim.run_id, claim.attempt_id)
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

    def list(
        self,
        *,
        folder_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ResearchRunList:
        cursor_created_at, cursor_id = _decode_list_cursor(cursor)
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, name, folder_id, status, requested_start_date,
                       requested_end_date, created_at, immutable_input,
                       failure_reason
                FROM research_runs.runs
                WHERE (%s::text IS NULL OR folder_id = %s::text)
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
                       failure_reason
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
                    raise ResearchRunOrganizationConflict(
                        "Research Folder does not exist"
                    )
            row = transaction.execute(
                """
                UPDATE research_runs.runs
                SET name = CASE WHEN %s THEN %s ELSE name END,
                    folder_id = CASE WHEN %s THEN %s ELSE folder_id END,
                    updated_at = now()
                WHERE id = %s
                RETURNING id, name, folder_id, status, requested_start_date,
                          requested_end_date, created_at, immutable_input,
                          failure_reason
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
                raise ResearchRunDeleteConflict(
                    "ResearchRun deletion requires terminal status"
                )
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
        _collect_publication_deletions(self._publication)
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
            if row["status"] in {"queued", "running"}:
                cancelled_attempt = transaction.execute(
                    """
                    UPDATE research_runs.attempts
                    SET status = 'cancelled', heartbeat_at = now(),
                        lease_expires_at = now(), finished_at = now(),
                        failure_reason = 'UserCancelled'
                    WHERE run_id = %s AND status = 'running'
                    RETURNING id, generation_pin_id
                    """,
                    (run_id,),
                ).fetchone()
                if cancelled_attempt is not None:
                    assert self._dataset_lifecycle is not None
                    self._dataset_lifecycle.release_pin_in_transaction(
                        transaction,
                        str(cancelled_attempt["generation_pin_id"]),
                        owner_id=str(cancelled_attempt["id"]),
                    )
                updated = transaction.execute(
                    """
                    UPDATE research_runs.runs
                    SET status = 'cancelled',
                        execution_fence = execution_fence + 1,
                        failure_reason = NULL, updated_at = now()
                    WHERE id = %s AND status IN ('queued', 'running')
                    RETURNING id, name, folder_id, status,
                              requested_start_date, requested_end_date,
                              created_at, immutable_input, failure_reason
                    """,
                    (run_id,),
                ).fetchone()
                if updated is None:
                    raise ResearchRunFenced
                row = updated
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
                SELECT id, name, folder_id, status, requested_start_date,
                       requested_end_date, created_at, immutable_input,
                       result_manifest_sha256, result_provenance, failure_reason
                FROM research_runs.runs
                WHERE id = %s
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
            stored_result = read_result_bundle(bundle)
            result = _public_result(stored_result, dict(provenance))
        except Exception as error:
            logger.error(
                "ResearchRun Result read failed",
                extra={"run_id": run_id, "error_type": type(error).__name__},
            )
            raise ResearchRunResultUnavailable from error
        return ResearchRunDetail(
            **summary.model_dump(),
            input=authorable_input,
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
        try:
            require_current_numeric_contract(
                immutable_input.numeric_execution_contract
            )
        except NumericContractError as error:
            raise ResearchRunTrackingUnavailable from error
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
            immutable_input=immutable_input.model_dump(mode="json"),
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
        if (
            self._dataset_lifecycle is None
            or self._generation_store is None
            or self._publication is None
        ):
            raise RuntimeError("ResearchRun execution dependencies are not configured")

    def _claim_next(self) -> _ExecutionClaim | None:
        assert self._dataset_lifecycle is not None
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT run.id, run.status, run.immutable_input,
                       run.execution_fence,
                       attempt.id AS latest_attempt_id,
                       attempt.ordinal AS latest_attempt_ordinal,
                       attempt.status AS latest_attempt_status,
                       attempt.generation_pin_id AS latest_generation_pin_id,
                       EXISTS (
                           SELECT 1
                           FROM research_runs.attempts AS exhausted
                           WHERE exhausted.run_id = run.id
                             AND exhausted.failure_reason = %s
                       ) AS resource_exhausted_seen
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
                self._dataset_lifecycle.release_pin_in_transaction(
                    transaction,
                    str(row["latest_generation_pin_id"]),
                    owner_id=str(row["latest_attempt_id"]),
                )
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
        return _ExecutionClaim(
            run_id=run_id,
            attempt_id=attempt_id,
            fence=fence,
            generation_pin_id=pin.id,
            data_generation_id=generation.manifest_sha256,
            data_through_session=generation.data_through_session,
            immutable_input=immutable_input,
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
        assert self._generation_store is not None
        assert self._publication is not None
        immutable_input = claim.immutable_input
        require_current_numeric_contract(
            immutable_input.numeric_execution_contract
        )
        try:
            admission = self._generation_store.open_admission(claim.data_generation_id)
        except GenerationStoreError as error:
            raise ResearchRunInputInvalid("selected Data Generation is invalid") from error
        calendar = list(admission.research_calendar)
        start_session, end_session = _selected_research_period(
            immutable_input,
            research_sessions=calendar,
            available_field_ids=frozenset(admission.generation.field_availability),
        )
        start_index = calendar.index(start_session)
        warmup_start = start_index - immutable_input.alpha_admission.effective_lookback
        if warmup_start < 0:
            raise ResearchRunInsufficientWarmup(
                "insufficient Calculation Warm-up for selected Research Period"
            )
        calculation_sessions = calendar[warmup_start : calendar.index(end_session) + 1]
        try:
            generation = self._generation_store.read_composite_slice(
                claim.data_generation_id,
                sessions=calculation_sessions,
                universe_name=immutable_input.universe,
                neutralization=immutable_input.neutralization,
                field_bindings=immutable_input.field_bindings,
            )
        except GenerationStoreError as error:
            raise ResearchRunInputInvalid(
                "selected Data Generation cannot resolve Formula"
            ) from error
        kernel_input = _kernel_input(
            immutable_input,
            generation.research_data,
            research_start_session=start_session,
            research_end_session=end_session,
        )
        try:
            output = run_kernel(kernel_input)
        except InsufficientCalculationWarmupError as error:
            raise ResearchRunInsufficientWarmup(str(error)) from error
        except KernelRunError as error:
            raise ResearchRunInputInvalid(str(error)) from error
        result = build_result_payload(
            output,
            rebalance_interval=int(immutable_input.strategy["rebalance_every_sessions"]),
            universe=immutable_input.universe,
        )
        provenance = _result_provenance(claim)
        prepared = self._publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads(result),
            provenance=provenance,
        )
        observations = result["strategy_daily_observations"]
        if not isinstance(observations, list):
            raise ResearchResultError("Result Strategy Daily Observations are invalid")
        enforce_result_bundle_budget(prepared.exact_bytes, len(observations))
        return prepared, provenance

    def _publish_success(
        self,
        claim: _ExecutionClaim,
        prepared: PreparedPublication,
        provenance: dict[str, object],
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
            self._dataset_lifecycle.release_pin_in_transaction(
                transaction,
                claim.generation_pin_id,
                owner_id=claim.attempt_id,
            )

    def _record_failure(self, claim: _ExecutionClaim, error: Exception) -> None:
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
    if estimated_run_work > MAX_ALPHA_RUN_ESTIMATED_WORK:
        raise ResearchRunAdmissionRejected(
            [
                ResearchRunAdmissionIssue(
                    code="ALPHA_RUN_WORK_EXCEEDS_LIMIT",
                    field="formula",
                    message=(
                        "Alpha Formula, Research Dates, and Universe exceed the Run work budget"
                    ),
                )
            ]
        )
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
        strategy={
            "kind": FIXED_STRATEGY_KIND,
            "holdings_count": command.holdings_count,
            "rebalance_every_sessions": command.rebalance_every_sessions,
            "initial_cash_cny": FIXED_INITIAL_CASH_CNY,
            "execution": FIXED_EXECUTION,
        },
        costs=FIXED_COSTS,
        risk_free_rate="0",
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


def _selected_research_period(
    immutable_input: ImmutableRunInput,
    *,
    research_sessions: list[str],
    available_field_ids: frozenset[str],
) -> tuple[str, str]:
    if not research_sessions:
        raise ResearchRunInputInvalid("selected Data Generation has no Research Sessions")
    sessions = [str(session) for session in research_sessions]
    requested_start = immutable_input.requested_start_date.isoformat()
    requested_end = immutable_input.requested_end_date.isoformat()
    if requested_start < sessions[0] or requested_end > sessions[-1]:
        raise ResearchRunInputInvalid("requested Research Period is outside Dataset Coverage")
    selected = [
        session for session in sessions if requested_start <= session <= requested_end
    ]
    if not selected:
        raise ResearchRunInputInvalid("requested dates contain no Research Session")
    missing_fields = set(immutable_input.field_bindings) - available_field_ids
    if missing_fields:
        raise ResearchRunInputInvalid("selected Data Generation lacks a frozen field")
    return selected[0], selected[-1]


def _kernel_input(
    immutable_input: ImmutableRunInput,
    research_data: AlignedResearchData,
    *,
    research_start_session: str,
    research_end_session: str,
) -> RunInput:
    strategy = immutable_input.strategy
    costs = immutable_input.costs
    return RunInput(
        research_data=research_data,
        alpha_expression=immutable_input.alpha_expression,
        field_bindings=immutable_input.field_bindings,
        effective_alpha_lookback=immutable_input.alpha_admission.effective_lookback,
        universe=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_every_sessions"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
        research_start_session=research_start_session,
        research_end_session=research_end_session,
    )


def _result_provenance(claim: _ExecutionClaim) -> dict[str, object]:
    value = claim.immutable_input.model_dump(mode="json")
    return {
        "schema_version": "research-result-v1",
        "research_run_id": claim.run_id,
        "immutable_input_sha256": hashlib.sha256(
            canonical_json_bytes(value)
        ).hexdigest(),
        "data_generation_id": claim.data_generation_id,
        "data_through_session": claim.data_through_session,
        "calculation_contracts": {
            "strategy": value["strategy"],
            "costs": value["costs"],
            "risk_free_rate": value["risk_free_rate"],
            "numeric_execution_contract": value["numeric_execution_contract"],
        },
        "semantic_versions": value["semantic_versions"],
    }


def _failure_policy(error: Exception) -> _FailurePolicy:
    if isinstance(error, ResearchRunInsufficientWarmup):
        return _FailurePolicy(
            attempt_reason="InsufficientCalculationWarmup",
            public_reason=INSUFFICIENT_WARMUP_PUBLIC_REASON,
            max_attempts=1,
            retryable=False,
        )
    if isinstance(error, ResearchRunInputInvalid):
        return _FailurePolicy(
            attempt_reason="SelectedDataInvalid",
            public_reason=SELECTED_DATA_INVALID_PUBLIC_REASON,
            max_attempts=1,
            retryable=False,
        )
    if isinstance(error, (MemoryError, OutOfMemory)):
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
        compact_formula
        if len(compact_formula) <= 120
        else f"{compact_formula[:117]}..."
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
            "failure_reason": row.get("failure_reason"),
        }
    )


def _authorable_input(row: object) -> ResearchRunAuthorableInput:
    assert isinstance(row, dict)
    immutable_input = ImmutableRunInput.model_validate(row["immutable_input"])
    return ResearchRunAuthorableInput(
        formula=immutable_input.formula_source,
        hypothesis=immutable_input.hypothesis,
        start_date=immutable_input.requested_start_date,
        end_date=immutable_input.requested_end_date,
        universe=immutable_input.universe,
        neutralization=immutable_input.neutralization,
        holdings_count=int(immutable_input.strategy["holdings_count"]),
        rebalance_every_sessions=int(
            immutable_input.strategy["rebalance_every_sessions"]
        ),
    )


def _public_result(
    stored: object,
    provenance: dict[str, object],
) -> ResearchRunResult:
    if not isinstance(stored, Mapping):
        raise ResearchRunResultUnavailable
    factor = stored.get("factor_summary")
    strategy_summary = stored.get("strategy_summary")
    observations = stored.get("strategy_daily_observations")
    terminal_strategy_state = stored.get("terminal_strategy_state")
    if (
        not isinstance(factor, Mapping)
        or not isinstance(strategy_summary, Mapping)
        or not isinstance(observations, list)
        or not isinstance(terminal_strategy_state, Mapping)
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


def _collect_publication_deletions(publication: Publication) -> None:
    try:
        while publication.collect_one_pending_deletion():
            pass
    except (PublicationPreparationError, PublicationUnavailableError) as error:
        logger.warning(
            "ResearchRun publication cleanup remains pending",
            extra={"error_type": type(error).__name__},
        )


def research_run_exists(transaction: PostgresTransaction, run_id: str) -> bool:
    return transaction.execute(
        "SELECT 1 FROM research_runs.runs WHERE id = %s",
        (run_id,),
    ).fetchone() is not None


def research_result_manifest_is_referenced(
    transaction: PostgresTransaction,
    manifest_sha256: str,
) -> bool:
    return transaction.execute(
        """
        SELECT 1
        FROM research_runs.runs
        WHERE result_manifest_sha256 = %s
        LIMIT 1
        """,
        (manifest_sha256,),
    ).fetchone() is not None
