from uuid import uuid4

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

    def list(self) -> ResearchFolderList:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT id, name, is_default, created_at
                FROM research_folders.folders
                ORDER BY is_default DESC, created_at, id
                """
            ).fetchall()
        return ResearchFolderList(
            items=[ResearchFolderSummary.model_validate(row) for row in rows]
        )

    def create(self, command: CreateResearchFolder) -> ResearchFolderSummary:
        folder_id = f"folder_{uuid4().hex[:20]}"
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                INSERT INTO research_folders.folders (id, name, is_default)
                VALUES (%s, %s, false)
                RETURNING id, name, is_default, created_at
                """,
                (folder_id, command.name),
            ).fetchone()
        assert row is not None
        return ResearchFolderSummary.model_validate(row)

    def rename(
        self,
        folder_id: str,
        command: RenameResearchFolder,
    ) -> ResearchFolderSummary | None:
        if folder_id == DEFAULT_FOLDER_ID:
            raise ResearchFolderConflict("Default Folder cannot be renamed")
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                UPDATE research_folders.folders
                SET name = %s, updated_at = now()
                WHERE id = %s AND NOT is_default
                RETURNING id, name, is_default, created_at
                """,
                (command.name, folder_id),
            ).fetchone()
        return None if row is None else ResearchFolderSummary.model_validate(row)

    def delete(self, folder_id: str) -> bool:
        if folder_id in {DEFAULT_FOLDER_ID, BATCH_RESEARCH_FOLDER_ID}:
            raise ResearchFolderConflict("System Research Folder cannot be deleted")
        try:
            with self._database.transaction() as transaction:
                row = transaction.execute(
                    """
                    DELETE FROM research_folders.folders
                    WHERE id = %s AND NOT is_default
                    RETURNING id
                    """,
                    (folder_id,),
                ).fetchone()
        except ForeignKeyViolation as error:
            raise ResearchFolderConflict("A nonempty Folder cannot be deleted") from error
        return row is not None
