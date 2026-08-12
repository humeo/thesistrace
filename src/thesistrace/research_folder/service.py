from thesistrace._postgres import PostgresDatabase
from thesistrace.research_folder.models import ResearchFolderList, ResearchFolderSummary

DEFAULT_FOLDER_ID = "folder_default"


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
