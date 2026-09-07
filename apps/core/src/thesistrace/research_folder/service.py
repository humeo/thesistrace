from uuid import UUID, uuid4

from psycopg.errors import ForeignKeyViolation

from thesistrace._postgres import PostgresDatabase
from thesistrace.research_folder.models import (
    CreateResearchFolder,
    RenameResearchFolder,
    ResearchFolderList,
    ResearchFolderSummary,
)

DEFAULT_FOLDER_ID = "folder_default"
BATCH_RESEARCH_FOLDER_ID = "folder_batch_research"


class ResearchFolderConflict(RuntimeError):
    pass


class ResearchFolderService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def list(self, researcher_id: UUID) -> ResearchFolderList:
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
                raise ResearchFolderConflict("System Research Folder cannot be renamed")
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
                        "System Research Folder cannot be deleted"
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
            raise ResearchFolderConflict("A nonempty Folder cannot be deleted") from error
        return row is not None
