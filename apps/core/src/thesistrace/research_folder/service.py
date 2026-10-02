from typing import Literal
from uuid import UUID, uuid4

from psycopg import OperationalError
from psycopg.errors import ForeignKeyViolation
from psycopg_pool import PoolTimeout

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.research_folder.models import (
    CreateResearchFolder,
    RenameResearchFolder,
    ResearchFolderList,
    ResearchFolderSummary,
)

DEFAULT_FOLDER_ID = "folder_default"
BATCH_RESEARCH_FOLDER_ID = "folder_batch_research"


class ResearchFolderConflict(RuntimeError):
    def __init__(self, code: Literal[
        "SYSTEM_FOLDER_RENAME_FORBIDDEN", "SYSTEM_FOLDER_DELETE_FORBIDDEN", "FOLDER_NOT_EMPTY",
        "FOLDER_NAME_EXISTS",
    ]) -> None:
        self.code = code
        super().__init__(code)


class ResearchFolderTemporarilyUnavailable(RuntimeError):
    pass


class ResearchFolderService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def list(self, researcher_id: UUID) -> ResearchFolderList:
        try:
            with self._database.transaction() as transaction:
                rows = transaction.execute(
                    """
                    SELECT id, name, is_default, created_at
                    FROM research_folders.folders
                    WHERE researcher_id = %s
                    ORDER BY is_default DESC, created_at, id
                    """,
                    (researcher_id,),
                ).fetchall()
        except (OperationalError, PoolTimeout) as error:
            raise ResearchFolderTemporarilyUnavailable(
                "Research Folders are unavailable",
            ) from error
        return ResearchFolderList(
            items=[ResearchFolderSummary.model_validate(row) for row in rows]
        )

    def create(
        self,
        researcher_id: UUID,
        command: CreateResearchFolder,
    ) -> ResearchFolderSummary:
        folder_id = f"folder_{uuid4().hex[:20]}"
        with self._database.transaction() as transaction:
            _require_available_name(transaction, researcher_id, folder_id, command.name)
            row = transaction.execute(
                """
                INSERT INTO research_folders.folders (
                    researcher_id, id, name, is_default
                ) VALUES (%s, %s, %s, false)
                RETURNING id, name, is_default, created_at
                """,
                (researcher_id, folder_id, command.name),
            ).fetchone()
        assert row is not None
        return ResearchFolderSummary.model_validate(row)

    def rename(
        self,
        researcher_id: UUID,
        folder_id: str,
        command: RenameResearchFolder,
    ) -> ResearchFolderSummary | None:
        with self._database.transaction() as transaction:
            current = transaction.execute(
                """
                SELECT is_default
                FROM research_folders.folders
                WHERE researcher_id = %s AND id = %s
                FOR UPDATE
                """,
                (researcher_id, folder_id),
            ).fetchone()
            if current is None:
                return None
            if current["is_default"] or folder_id == BATCH_RESEARCH_FOLDER_ID:
                raise ResearchFolderConflict("SYSTEM_FOLDER_RENAME_FORBIDDEN")
            _require_available_name(transaction, researcher_id, folder_id, command.name)
            row = transaction.execute(
                """
                UPDATE research_folders.folders
                SET name = %s, updated_at = now()
                WHERE researcher_id = %s AND id = %s AND NOT is_default
                RETURNING id, name, is_default, created_at
                """,
                (command.name, researcher_id, folder_id),
            ).fetchone()
        return None if row is None else ResearchFolderSummary.model_validate(row)

    def delete(self, researcher_id: UUID, folder_id: str) -> bool:
        try:
            with self._database.transaction() as transaction:
                current = transaction.execute(
                    """
                    SELECT is_default
                    FROM research_folders.folders
                    WHERE researcher_id = %s AND id = %s
                    FOR UPDATE
                    """,
                    (researcher_id, folder_id),
                ).fetchone()
                if current is None:
                    return False
                if current["is_default"] or folder_id == BATCH_RESEARCH_FOLDER_ID:
                    raise ResearchFolderConflict(
                        "SYSTEM_FOLDER_DELETE_FORBIDDEN"
                    )
                row = transaction.execute(
                    """
                    DELETE FROM research_folders.folders
                    WHERE researcher_id = %s AND id = %s AND NOT is_default
                    RETURNING id
                    """,
                    (researcher_id, folder_id),
                ).fetchone()
        except ForeignKeyViolation as error:
            raise ResearchFolderConflict("FOLDER_NOT_EMPTY") from error
        return row is not None


def _require_available_name(
    transaction: PostgresTransaction,
    researcher_id: UUID,
    folder_id: str,
    name: str,
) -> None:
    # Serialize name checks and writes across API processes for this Researcher.
    transaction.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"research-folder-names:{researcher_id}",),
    )
    duplicate = transaction.execute(
        """
        SELECT 1 FROM research_folders.folders
        WHERE researcher_id = %s AND id <> %s AND lower(name) = lower(%s)
        LIMIT 1
        """,
        (researcher_id, folder_id, name),
    ).fetchone()
    if duplicate is not None:
        raise ResearchFolderConflict("FOLDER_NAME_EXISTS")
