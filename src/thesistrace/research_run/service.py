from __future__ import annotations

from uuid import uuid4

from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.research_run.models import (
    ImmutableRunInput,
    ResearchRunList,
    ResearchRunSummary,
)


class ResearchRunService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

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


def _summary(row: object) -> ResearchRunSummary:
    assert isinstance(row, dict)
    return ResearchRunSummary.model_validate(row)
