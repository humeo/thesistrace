from thesistrace._postgres import PostgresDatabase
from thesistrace.research_folder.service import (
    BATCH_RESEARCH_FOLDER_ID,
    DEFAULT_FOLDER_ID,
)
from thesistrace.researcher.models import (
    ResearcherBootstrapResult,
    ResearcherIdentity,
    SystemResearchFolders,
)


class ResearcherService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def bootstrap(self, identity: ResearcherIdentity) -> ResearcherBootstrapResult:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO researchers.researchers (id)
                VALUES (%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (identity.researcher_id,),
            )
            transaction.execute(
                """
                INSERT INTO research_folders.folders (
                    researcher_id, id, name, is_default
                ) VALUES
                    (%s, %s, 'Default', true),
                    (%s, %s, 'Batch Research', false)
                ON CONFLICT (researcher_id, id) DO NOTHING
                """,
                (
                    identity.researcher_id,
                    DEFAULT_FOLDER_ID,
                    identity.researcher_id,
                    BATCH_RESEARCH_FOLDER_ID,
                ),
            )
        return ResearcherBootstrapResult(
            researcher_id=identity.researcher_id,
            system_folders=SystemResearchFolders(
                default=DEFAULT_FOLDER_ID,
                batch_research=BATCH_RESEARCH_FOLDER_ID,
            ),
        )


__all__ = ("ResearcherService",)
