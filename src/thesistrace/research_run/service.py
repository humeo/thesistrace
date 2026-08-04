from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.publication import JsonPayload, PreparedPublication, Publication
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)
from thesistrace.research_kernel.kernel_run import RunInput, RunOutput
from thesistrace.research_kernel.kernel_run import run as run_kernel
from thesistrace.research_run.models import (
    ImmutableRunInput,
    ResearchRunList,
    ResearchRunSummary,
)
from thesistrace.research_run.result import build_result_payload

logger = logging.getLogger(__name__)
MAX_RESULT_BUNDLE_BYTES = 1_048_576
LoadCanonical = Callable[[str], dict[str, object]]
ExecuteKernel = Callable[[RunInput], RunOutput]
Progress = Callable[[str, str], None]


class ResearchRunFenced(RuntimeError):
    pass


@dataclass(frozen=True)
class _ExecutionClaim:
    run_id: str
    attempt_id: str
    fence: int
    immutable_input: ImmutableRunInput


class ResearchRunService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        load_canonical: LoadCanonical | None = None,
        publication: Publication | None = None,
        execute_kernel: ExecuteKernel = run_kernel,
        progress: Progress | None = None,
    ) -> None:
        self._database = database
        self._load_canonical = load_canonical
        self._publication = publication
        self._execute_kernel = execute_kernel
        self._progress = progress or (lambda _stage, _run_id: None)

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
                dataset_release_id, status, immutable_input
            ) VALUES (%s, %s, %s, %s, 'queued', %s)
            RETURNING id, status, definition_id, definition_revision,
                      dataset_release_id
            """,
            (
                run_id,
                str(definition["id"]),
                int(definition["revision"]),
                immutable_input.dataset_release_id,
                Jsonb(immutable_input.model_dump(mode="json")),
            ),
        ).fetchone()
        assert row is not None
        return _summary(row)

    def process_next(self) -> bool:
        self._require_execution_dependencies()
        claim = self._claim_next()
        if claim is None:
            return False
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
            self._record_failure(claim, type(error).__name__)
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
                       dataset_release_id
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
                       dataset_release_id
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
        return None if row is None else _summary(row)

    def _require_execution_dependencies(self) -> None:
        if self._load_canonical is None or self._publication is None:
            raise RuntimeError("ResearchRun execution dependencies are not configured")

    def _claim_next(self) -> _ExecutionClaim | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, immutable_input, execution_fence
                FROM research_runs.runs
                WHERE status = 'queued'
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            run_id = str(row["id"])
            fence = int(row["execution_fence"]) + 1
            ordinal_row = transaction.execute(
                """
                SELECT count(*) + 1 AS ordinal
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
                SET status = 'running', execution_fence = %s, updated_at = now()
                WHERE id = %s
                """,
                (fence, run_id),
            )
            transaction.execute(
                """
                INSERT INTO research_runs.attempts (
                    id, run_id, ordinal, fence, status, lease_expires_at
                ) VALUES (%s, %s, %s, %s, 'running', now() + interval '15 minutes')
                """,
                (attempt_id, run_id, int(ordinal_row["ordinal"]), fence),
            )
        return _ExecutionClaim(
            run_id=run_id,
            attempt_id=attempt_id,
            fence=fence,
            immutable_input=ImmutableRunInput.model_validate(row["immutable_input"]),
        )

    def _execute(
        self,
        claim: _ExecutionClaim,
    ) -> tuple[PreparedPublication, dict[str, object]]:
        assert self._load_canonical is not None
        assert self._publication is not None
        immutable_input = claim.immutable_input
        canonical = self._load_canonical(immutable_input.dataset_release_id)
        canonical = _research_input_history(canonical)
        self._progress("inputs_loaded", claim.run_id)
        kernel_input = _kernel_input(immutable_input, canonical)
        output = self._execute_kernel(kernel_input)
        self._progress("calculated", claim.run_id)
        result = build_result_payload(
            output,
            rebalance_interval=int(immutable_input.strategy["rebalance_every_sessions"]),
        )
        provenance = _result_provenance(claim.run_id, immutable_input)
        prepared = self._publication.prepare(
            kind="research.result",
            payloads={"result": JsonPayload(result)},
            provenance=provenance,
        )
        if prepared.exact_bytes > MAX_RESULT_BUNDLE_BYTES:
            raise RuntimeError("complete Result Bundle exceeds 1,048,576 exact bytes")
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
                    result_provenance = %s, updated_at = now()
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

    def _record_failure(self, claim: _ExecutionClaim, reason: str) -> None:
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
            transaction.execute(
                """
                UPDATE research_runs.attempts
                SET status = 'failed', heartbeat_at = now(), finished_at = now(),
                    failure_reason = %s
                WHERE id = %s AND run_id = %s AND fence = %s AND status = 'running'
                """,
                (reason, claim.attempt_id, claim.run_id, claim.fence),
            )
            transaction.execute(
                """
                UPDATE research_runs.runs
                SET status = 'failed', updated_at = now()
                WHERE id = %s AND status = 'running' AND execution_fence = %s
                """,
                (claim.run_id, claim.fence),
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
        "dataset_release_id": immutable_input.dataset_release_id,
        "calculation_contracts": {
            "strategy": value["strategy"],
            "costs": value["costs"],
            "risk_free_rate": value["risk_free_rate"],
            "numeric_execution_contract": value["numeric_execution_contract"],
        },
        "semantic_versions": value["semantic_versions"],
    }


def _summary(row: object) -> ResearchRunSummary:
    assert isinstance(row, dict)
    return ResearchRunSummary.model_validate(row)
