from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import AuthorableField
from thesistrace.definition.models import (
    AuthorableFieldOption,
    DefinitionAuthoringOptions,
    DefinitionDetail,
    DefinitionList,
    DefinitionSaveCommand,
    DefinitionSummary,
    IntegerBounds,
    OperatorOption,
)

CONTENT_FIELDS = (
    "name",
    "hypothesis",
    "alpha",
    "universe",
    "neutralization",
    "holdings_count",
    "rebalance_every_sessions",
)


class DefinitionConflict(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("Research Definition revision conflicts")
        self.current_revision = current_revision


class DefinitionService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        authorable_fields: Callable[[], tuple[AuthorableField, ...]],
        operator_catalog: Callable[[], dict[str, object]],
    ) -> None:
        self._database = database
        self._authorable_fields = authorable_fields
        self._operator_catalog = operator_catalog

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
        definition_id = f"def_{uuid4().hex[:20]}"
        content = {field: getattr(command, field) for field in CONTENT_FIELDS}
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
            for field in CONTENT_FIELDS:
                if field in command.model_fields_set:
                    content[field] = getattr(command, field)
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


def _generated_name(definition_id: str) -> str:
    return f"Research {definition_id[-8:].upper()}"


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
