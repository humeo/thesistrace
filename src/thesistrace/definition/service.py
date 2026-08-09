from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data import AuthorableField
from thesistrace.data.service import ReleaseReference
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
from thesistrace.research_kernel.alpha_expression import AlphaValidationError
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
        authorable_fields: Callable[[], tuple[AuthorableField, ...]],
        operator_catalog: Callable[[], dict[str, object]],
        validate_alpha: Callable[..., object],
        latest_release: Callable[[PostgresTransaction], ReleaseReference | None],
        admit_run: Callable[
            [PostgresTransaction, ImmutableRunInput], ResearchRunSummary
        ],
    ) -> None:
        self._database = database
        self._authorable_fields = authorable_fields
        self._operator_catalog = operator_catalog
        self._validate_alpha = validate_alpha
        self._latest_release = latest_release
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
                    definition=field.definition,
                    unit=field.unit,
                )
                for field in self._authorable_fields()
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
                       saved_content, outcome, issues, research_run_id,
                       dataset_release_id
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

            release = self._latest_release(transaction)
            issues = _runnability_issues(content, has_release=release is not None)
            if release is not None and isinstance(content.get("alpha"), Mapping):
                try:
                    self._validate_alpha(
                        content["alpha"],
                        field_bindings=release.field_bindings,
                    )
                except AlphaValidationError:
                    issues.append(
                        RunValidationIssue(
                            code="FIELD_UNAVAILABLE_IN_RELEASE",
                            field="alpha",
                            message=(
                                "Alpha field is unavailable in the latest "
                                "Dataset Release"
                            ),
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

            assert release is not None
            immutable_input = _immutable_run_input(
                definition_id=saved_id,
                definition_revision=saved_revision,
                content=content,
                release=release,
                operator_catalog=self._operator_catalog(),
            )
            run = self._admit_run(transaction, immutable_input)
            transaction.execute(
                """
                INSERT INTO definitions.run_receipts (
                    request_id, request_fingerprint, definition_id,
                    saved_revision, saved_content, outcome, issues,
                    research_run_id, dataset_release_id
                ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s, %s, %s)
                """,
                (
                    request_id,
                    fingerprint,
                    saved_id,
                    saved_revision,
                    Jsonb(content),
                    Jsonb(serialized_issues),
                    run.id,
                    release.id,
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
            self._validate_alpha(command.alpha)

    def _validate_run_structure(self, command: DefinitionRunCommand) -> None:
        if command.alpha is not None:
            self._validate_alpha(command.alpha)


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


def _runnability_issues(
    content: dict[str, object],
    *,
    has_release: bool,
) -> list[RunValidationIssue]:
    required = (
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
    if not has_release:
        issues.append(
            RunValidationIssue(
                code="DATASET_RELEASE_REQUIRED",
                field="dataset_release",
                message="Publish canonical Data before running research",
            )
        )
    return issues


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
            dataset_release_id=str(row["dataset_release_id"]),
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
    release: ReleaseReference,
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
        dataset_release_id=release.id,
        field_bindings=dict(release.field_bindings),
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
    return DefinitionDetail(
        id=definition_id,
        revision=revision,
        **{field: content.get(field) for field in CONTENT_FIELDS},
    )


def _detail(row: object) -> DefinitionDetail:
    assert isinstance(row, dict)
    content = row["content"]
    assert isinstance(content, dict)
    return DefinitionDetail(
        id=str(row["id"]),
        revision=int(row["revision"]),
        **{field: content.get(field) for field in CONTENT_FIELDS},
    )


def _summary(row: object) -> DefinitionSummary:
    detail = _detail(row)
    return DefinitionSummary(id=detail.id, name=detail.name, revision=detail.revision)
