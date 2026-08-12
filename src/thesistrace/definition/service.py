from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import date
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data import (
    DatasetAdmissionSnapshot,
    FieldDefinition,
    alpha_identifier_by_field_id,
)
from thesistrace.definition.models import (
    AuthorableFieldOption,
    DefinitionAuthoringOptions,
    DefinitionDetail,
    DefinitionList,
    DefinitionRunCommand,
    DefinitionRunOutcome,
    DefinitionSaveCommand,
    DefinitionSummary,
    IntegerBounds,
    OperatorOption,
    RunValidationIssue,
)
from thesistrace.research_kernel.alpha_expression import ParsedAlpha
from thesistrace.research_kernel.numeric import NUMERIC_CONTRACT_ID
from thesistrace.research_run import ImmutableRunInput, ResearchRunSummary

CONTENT_FIELDS = (
    "name",
    "hypothesis",
    "alpha",
    "universe",
    "neutralization",
    "holdings_count",
    "rebalance_every_sessions",
    "start_date",
    "end_date",
)

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
    "alpha": "alpha-v1",
    "factor": "factor-v1",
    "strategy": "strategy-v1",
    "kernel": "kernel-v1",
}
CurrentDataset = Callable[[], DatasetAdmissionSnapshot | None]


class DefinitionConflict(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("Research Definition revision conflicts")
        self.current_revision = current_revision


class DefinitionRunConflict(RuntimeError):
    pass


class DefinitionService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        alpha_fields: Callable[[], tuple[FieldDefinition, ...]],
        operator_catalog: Callable[[], dict[str, object]],
        validate_alpha: Callable[..., object],
        current_dataset: CurrentDataset,
        admit_run: Callable[[PostgresTransaction, ImmutableRunInput], ResearchRunSummary],
    ) -> None:
        self._database = database
        self._alpha_fields = alpha_fields
        self._operator_catalog = operator_catalog
        self._validate_alpha = validate_alpha
        self._current_dataset = current_dataset
        self._alpha_identifier_by_field_id = alpha_identifier_by_field_id()
        self._admit_run = admit_run

    def authoring_options(self) -> DefinitionAuthoringOptions:
        catalog = self._operator_catalog()
        raw_operators = catalog.get("operators")
        if not isinstance(raw_operators, list):
            raise RuntimeError("Research Kernel operator catalog is malformed")
        return DefinitionAuthoringOptions(
            fields=[
                AuthorableFieldOption(
                    field_id=field.field_id,
                    definition=field.description,
                    unit=field.unit,
                )
                for field in self._alpha_fields()
            ],
            operators=[OperatorOption.model_validate(item) for item in raw_operators],
            universes=["top300", "top1000", "top2000", "top3000"],
            neutralizations=["none", "industry"],
            holdings_count=IntegerBounds(minimum=1, maximum=100),
            rebalance_every_sessions=IntegerBounds(minimum=1, maximum=20),
        )

    def list(self) -> DefinitionList:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, revision, content
                FROM definitions.records
                ORDER BY updated_at DESC, id
                """
            ).fetchall()
        return DefinitionList(
            items=[_summary(row) for row in rows],
            next_cursor=None,
        )

    def get(self, definition_id: str) -> DefinitionDetail | None:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT id, revision, content
                FROM definitions.records
                WHERE id = %s
                """,
                (definition_id,),
            ).fetchone()
        return None if row is None else _detail(row)

    def create(self, command: DefinitionSaveCommand) -> DefinitionDetail:
        if command.expected_revision is not None:
            raise ValueError("Creating a Research Definition takes no expected revision")
        self._validate_structure(command)
        definition_id = f"def_{uuid4().hex[:20]}"
        content = _command_content(command)
        name = str(content["name"] or "").strip()
        content["name"] = name or _generated_name(definition_id)
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                INSERT INTO definitions.records (id, revision, content)
                VALUES (%s, 1, %s)
                RETURNING id, revision, content
                """,
                (definition_id, Jsonb(content)),
            ).fetchone()
        assert row is not None
        return _detail(row)

    def save(
        self,
        definition_id: str,
        command: DefinitionSaveCommand,
    ) -> DefinitionDetail | None:
        if command.expected_revision is None:
            raise ValueError("Updating a Research Definition requires expected revision")
        self._validate_structure(command)
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT id, revision, content
                FROM definitions.records
                WHERE id = %s
                FOR UPDATE
                """,
                (definition_id,),
            ).fetchone()
            if current is None:
                return None
            if int(current["revision"]) != command.expected_revision:
                raise DefinitionConflict(int(current["revision"]))
            content = dict(current["content"])
            submitted = command.model_dump(mode="json")
            for field in CONTENT_FIELDS:
                if field in command.model_fields_set:
                    content[field] = submitted[field]
            submitted_name = str(content.get("name") or "").strip()
            if submitted_name:
                content["name"] = submitted_name
            else:
                content["name"] = str(current["content"]["name"])
            row = transaction.execute(
                """
                UPDATE definitions.records
                SET revision = revision + 1,
                    content = %s,
                    updated_at = now()
                WHERE id = %s AND revision = %s
                RETURNING id, revision, content
                """,
                (Jsonb(content), definition_id, command.expected_revision),
            ).fetchone()
            if row is None:
                raise DefinitionConflict(int(current["revision"]))
        return _detail(row)

    def run(
        self,
        definition_id: str | None,
        command: DefinitionRunCommand,
    ) -> DefinitionRunOutcome:
        request_id = command.request_id.strip()
        if not request_id:
            raise ValueError("Run request_id is required")
        self._validate_run_structure(command)
        fingerprint = _run_fingerprint(definition_id, command)
        content = _command_content(command)

        with self._database.transaction() as transaction:
            transaction.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"definitions.run:{request_id}",),
            ).fetchone()
            receipt = transaction.execute(
                """
                SELECT request_fingerprint, definition_id, saved_revision,
                       saved_content, outcome, issues, research_run_id
                FROM definitions.run_receipts
                WHERE request_id = %s
                """,
                (request_id,),
            ).fetchone()
            if receipt is not None:
                if receipt["request_fingerprint"] != fingerprint:
                    raise DefinitionRunConflict("Definition Run request_id conflicts")
                return _run_outcome_from_receipt(receipt)

            if definition_id is None:
                if command.expected_revision is not None:
                    raise ValueError("Running a new Definition takes no expected revision")
                saved_id = f"def_{uuid4().hex[:20]}"
                submitted_name = str(content.get("name") or "").strip()
                content["name"] = submitted_name or _generated_name(saved_id)
                saved_revision = 1
                transaction.execute(
                    """
                    INSERT INTO definitions.records (id, revision, content)
                    VALUES (%s, %s, %s)
                    """,
                    (saved_id, saved_revision, Jsonb(content)),
                )
            else:
                if command.expected_revision is None:
                    raise ValueError("Running an existing Definition requires expected revision")
                current = transaction.execute(
                    """
                    SELECT id, revision, content
                    FROM definitions.records
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (definition_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(definition_id)
                if int(current["revision"]) != command.expected_revision:
                    raise DefinitionConflict(int(current["revision"]))
                saved_id = definition_id
                saved_revision = command.expected_revision + 1
                submitted_name = str(content.get("name") or "").strip()
                content["name"] = submitted_name or str(current["content"]["name"])
                transaction.execute(
                    """
                    UPDATE definitions.records
                    SET revision = %s, content = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (saved_revision, Jsonb(content), saved_id),
                )

            issues = _runnability_issues(content)
            snapshot = None if issues else self._current_dataset()
            parsed_alpha: ParsedAlpha | None = None
            if not issues:
                if snapshot is None:
                    issues.append(
                        RunValidationIssue(
                            code="DATA_NOT_READY",
                            field="data",
                            message="Current Dataset is not ready",
                        )
                    )
                else:
                    parsed_alpha = self._parsed_alpha(content)
                    issues.extend(
                        _dataset_issues(
                            content,
                            snapshot=snapshot,
                            parsed_alpha=parsed_alpha,
                        )
                    )
            serialized_issues = [issue.model_dump(mode="json") for issue in issues]
            if issues:
                transaction.execute(
                    """
                    INSERT INTO definitions.run_receipts (
                        request_id, request_fingerprint, definition_id,
                        saved_revision, saved_content, outcome, issues
                    ) VALUES (%s, %s, %s, %s, %s, 'rejected', %s)
                    """,
                    (
                        request_id,
                        fingerprint,
                        saved_id,
                        saved_revision,
                        Jsonb(content),
                        Jsonb(serialized_issues),
                    ),
                )
                return DefinitionRunOutcome(
                    outcome="rejected",
                    definition=_detail_from_values(saved_id, saved_revision, content),
                    issues=issues,
                )

            assert parsed_alpha is not None
            immutable_input = _immutable_run_input(
                definition_id=saved_id,
                definition_revision=saved_revision,
                content=content,
                field_bindings={
                    field_id: self._alpha_identifier_by_field_id[field_id]
                    for field_id in parsed_alpha.field_ids
                },
                operator_catalog=self._operator_catalog(),
            )
            run = self._admit_run(transaction, immutable_input)
            transaction.execute(
                """
                    INSERT INTO definitions.run_receipts (
                        request_id, request_fingerprint, definition_id,
                        saved_revision, saved_content, outcome, issues,
                        research_run_id
                    ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s, %s)
                """,
                (
                    request_id,
                    fingerprint,
                    saved_id,
                    saved_revision,
                    Jsonb(content),
                    Jsonb(serialized_issues),
                    run.id,
                ),
            )
        return DefinitionRunOutcome(
            outcome="accepted",
            definition=_detail_from_values(saved_id, saved_revision, content),
            issues=issues,
            run=run,
        )

    def _validate_structure(self, command: DefinitionSaveCommand) -> None:
        if command.alpha is not None:
            self._validate_alpha(
                command.alpha,
                field_bindings=self._alpha_identifier_by_field_id,
            )

    def _validate_run_structure(self, command: DefinitionRunCommand) -> None:
        if command.alpha is not None:
            self._validate_alpha(
                command.alpha,
                field_bindings=self._alpha_identifier_by_field_id,
            )

    def _parsed_alpha(self, content: dict[str, object]) -> ParsedAlpha:
        alpha = content["alpha"]
        assert isinstance(alpha, Mapping)
        parsed = self._validate_alpha(
            alpha,
            field_bindings=self._alpha_identifier_by_field_id,
        )
        assert isinstance(parsed, ParsedAlpha)
        return parsed


def _generated_name(definition_id: str) -> str:
    return f"Research {definition_id[-8:].upper()}"


def _command_content(
    command: DefinitionSaveCommand | DefinitionRunCommand,
) -> dict[str, object]:
    serialized = command.model_dump(mode="json")
    return {field: serialized[field] for field in CONTENT_FIELDS}


def _run_fingerprint(
    definition_id: str | None,
    command: DefinitionRunCommand,
) -> str:
    value = {
        "action": "definitions.run/v1",
        "definition_id": definition_id,
        "command": command.model_dump(mode="json", exclude={"request_id"}),
    }
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def _runnability_issues(content: dict[str, object]) -> list[RunValidationIssue]:
    required = (
        ("start_date", "START_DATE_REQUIRED", "Research start date is required"),
        ("end_date", "END_DATE_REQUIRED", "Research end date is required"),
        ("alpha", "ALPHA_REQUIRED", "Alpha is required"),
        ("universe", "UNIVERSE_REQUIRED", "Universe is required"),
        ("neutralization", "NEUTRALIZATION_REQUIRED", "Neutralization is required"),
        ("holdings_count", "HOLDINGS_COUNT_REQUIRED", "Holdings count is required"),
        (
            "rebalance_every_sessions",
            "REBALANCE_INTERVAL_REQUIRED",
            "Rebalance interval is required",
        ),
    )
    issues = [
        RunValidationIssue(code=code, field=field, message=message)
        for field, code, message in required
        if content.get(field) is None
    ]
    start = _content_date(content.get("start_date"))
    end = _content_date(content.get("end_date"))
    if start is not None and end is not None and start > end:
        issues.append(
            RunValidationIssue(
                code="RESEARCH_DATE_ORDER_INVALID",
                field="end_date",
                message="Research end date must not precede start date",
            )
        )
    return issues


def _dataset_issues(
    content: dict[str, object],
    *,
    snapshot: DatasetAdmissionSnapshot,
    parsed_alpha: ParsedAlpha,
) -> list[RunValidationIssue]:
    start = _content_date(content["start_date"])
    end = _content_date(content["end_date"])
    assert start is not None and end is not None
    issues: list[RunValidationIssue] = []
    if start < snapshot.coverage_start or end > snapshot.coverage_end:
        issues.append(
            RunValidationIssue(
                code="RESEARCH_PERIOD_OUTSIDE_COVERAGE",
                field="start_date",
                message="Requested Research Dates must be inside current Dataset Coverage",
            )
        )
    elif not snapshot.research_period(start, end):
        issues.append(
            RunValidationIssue(
                code="RESEARCH_PERIOD_HAS_NO_SESSIONS",
                field="start_date",
                message="Requested Research Dates contain no Research Session",
            )
        )
    if not set(parsed_alpha.field_ids) <= snapshot.available_field_ids:
        issues.append(
            RunValidationIssue(
                code="FIELD_UNAVAILABLE_IN_CURRENT_DATA",
                field="alpha",
                message="Alpha field is unavailable in current Data",
            )
        )
    return issues


def _content_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    assert isinstance(value, str)
    return date.fromisoformat(value)


def _run_outcome_from_receipt(row: object) -> DefinitionRunOutcome:
    assert isinstance(row, dict)
    content = row["saved_content"]
    assert isinstance(content, dict)
    run = None
    if row["outcome"] == "accepted":
        run_id = row["research_run_id"]
        assert isinstance(run_id, str)
        run = ResearchRunSummary(
            id=run_id,
            status="queued",
            definition_id=str(row["definition_id"]),
            definition_revision=int(row["saved_revision"]),
            start_date=_content_date(content["start_date"]),
            end_date=_content_date(content["end_date"]),
        )
    return DefinitionRunOutcome(
        outcome=row["outcome"],
        definition=_detail_from_values(
            str(row["definition_id"]),
            int(row["saved_revision"]),
            content,
        ),
        issues=[RunValidationIssue.model_validate(issue) for issue in row["issues"]],
        run=run,
    )


def _immutable_run_input(
    *,
    definition_id: str,
    definition_revision: int,
    content: dict[str, object],
    field_bindings: dict[str, str],
    operator_catalog: dict[str, object],
) -> ImmutableRunInput:
    catalog_version = operator_catalog.get("semantic_version")
    if not isinstance(catalog_version, str):
        raise RuntimeError("Research Kernel operator catalog is malformed")
    return ImmutableRunInput(
        definition={
            "id": definition_id,
            "revision": definition_revision,
            "content": dict(content),
        },
        requested_start_date=_content_date(content["start_date"]),
        requested_end_date=_content_date(content["end_date"]),
        field_bindings=dict(field_bindings),
        strategy={
            "kind": FIXED_STRATEGY_KIND,
            "holdings_count": content["holdings_count"],
            "rebalance_every_sessions": content["rebalance_every_sessions"],
            "initial_cash_cny": FIXED_INITIAL_CASH_CNY,
            "execution": FIXED_EXECUTION,
        },
        costs=FIXED_COSTS,
        risk_free_rate="0",
        numeric_execution_contract=NUMERIC_CONTRACT_ID,
        semantic_versions={
            **SEMANTIC_VERSIONS,
            "operator_catalog": catalog_version,
        },
    )


def _detail_from_values(
    definition_id: str,
    revision: int,
    content: dict[str, object],
) -> DefinitionDetail:
    projected = _complete_content(content)
    return DefinitionDetail(
        id=definition_id,
        revision=revision,
        **projected,
    )


def _detail(row: object) -> DefinitionDetail:
    assert isinstance(row, dict)
    content = row["content"]
    assert isinstance(content, dict)
    projected = _complete_content(content)
    return DefinitionDetail(
        id=str(row["id"]),
        revision=int(row["revision"]),
        **projected,
    )


def _complete_content(content: dict[str, object]) -> dict[str, object]:
    if set(content) != set(CONTENT_FIELDS):
        raise RuntimeError("Research Definition content is incompatible")
    return {field: content[field] for field in CONTENT_FIELDS}


def _summary(row: object) -> DefinitionSummary:
    detail = _detail(row)
    return DefinitionSummary(id=detail.id, name=detail.name, revision=detail.revision)
