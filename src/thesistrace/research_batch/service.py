from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data import DatasetLifecycle
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_batch.models import (
    FactorEvaluationBatchAdmissionCommand,
    ResearchBatchAdmissionCommand,
    ResearchBatchAdmissionIssue,
    ResearchBatchItemSummary,
    ResearchBatchList,
    ResearchBatchProgress,
    ResearchBatchScope,
    ResearchBatchSummary,
    StrategySweepBatchAdmissionCommand,
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
    ResearchRunService,
)

BATCH_ADMISSION_RETENTION_SECONDS = 15 * 60


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
        retention_seconds: float = BATCH_ADMISSION_RETENTION_SECONDS,
    ) -> None:
        if retention_seconds <= 0:
            raise ValueError("Research Batch retention duration must be positive")
        self._database = database
        self._research_runs = research_runs
        self._dataset_lifecycle = dataset_lifecycle
        self._retention_seconds = retention_seconds

    def admit(self, command: ResearchBatchAdmissionCommand) -> ResearchBatchSummary:
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
                issues.extend(
                    _child_issues(command, ordinal, item_key, error)
                )
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
                    batch_id, completed_items, total_items
                ) VALUES (%s, 0, %s)
                """,
                (batch_id, len(prepared)),
            )
            self._dataset_lifecycle.retain_generation_in_transaction(
                transaction,
                retention_id=f"research-batch:{batch_id}",
                generation_manifest_sha256=scope.data_generation_id,
                lease_seconds=self._retention_seconds,
            )
            outcome = _summary_in_transaction(
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
                SELECT id
                FROM research_batches.batches
                WHERE (
                    %s::timestamptz IS NULL
                    OR created_at < %s::timestamptz
                    OR (created_at = %s::timestamptz AND id > %s::text)
                )
                ORDER BY created_at DESC, id
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
            selected = rows[:limit]
            summaries = [
                _summary_in_transaction(
                    transaction,
                    str(row["id"]),
                    research_runs=self._research_runs,
                )
                for row in selected
            ]
        return ResearchBatchList(
            items=summaries,
            next_cursor=(
                _encode_cursor(summaries[-1]) if len(rows) > limit else None
            ),
        )

    def get(self, batch_id: str) -> ResearchBatchSummary | None:
        with self._database.transaction() as transaction:
            exists = transaction.execute(
                "SELECT id FROM research_batches.batches WHERE id = %s",
                (batch_id,),
            ).fetchone()
            if exists is None:
                return None
            return _summary_in_transaction(
                transaction,
                batch_id,
                research_runs=self._research_runs,
            )

    def _locked_receipt(
        self,
        request_id: str,
        fingerprint: str,
    ) -> ResearchBatchSummary | None:
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
                        message=(
                            f"item_key conflicts with ordinal {previous}: {item.item_key}"
                        ),
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
) -> ResearchBatchSummary:
    if receipt["request_fingerprint"] != fingerprint:
        raise ResearchBatchAdmissionConflict("Research Batch request_id conflicts")
    return ResearchBatchSummary.model_validate(receipt["outcome"])


def _summary_in_transaction(
    transaction: PostgresTransaction,
    batch_id: str,
    *,
    research_runs: ResearchRunService,
) -> ResearchBatchSummary:
    row = transaction.execute(
        """
        SELECT batch.id, batch.batch_kind, batch.status, batch.scope,
               batch.created_at, progress.completed_items, progress.total_items
        FROM research_batches.batches AS batch
        JOIN research_batches.progress AS progress ON progress.batch_id = batch.id
        WHERE batch.id = %s
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Research Batch projection is missing")
    item_rows = transaction.execute(
        """
        SELECT item.ordinal, item.item_key, item.research_run_id,
               item.dependency_role
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
    return ResearchBatchSummary(
        id=str(row["id"]),
        batch_kind=str(row["batch_kind"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        scope=ResearchBatchScope.model_validate(row["scope"]),
        progress=ResearchBatchProgress(
            completed_items=int(row["completed_items"]),
            total_items=int(row["total_items"]),
        ),
        items=[
            ResearchBatchItemSummary.model_validate(
                {**item, "status": child_statuses[str(item["research_run_id"])]}
            )
            for item in item_rows
        ],
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
        if set(value) != {"created_at", "id"} or not isinstance(value["id"], str):
            raise ValueError
        created_at = datetime.fromisoformat(value["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, value["id"]
    except (Base64DecodeError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise ValueError("Research Batch cursor is invalid") from None
