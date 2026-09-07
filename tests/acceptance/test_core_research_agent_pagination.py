from pathlib import Path

import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas, isolated_core_settings

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_agent.models import ResearchContextFolders
from thesistrace.research_agent.pagination import InvalidPageCursor, ResearchAgentPagination
from thesistrace.research_folder.models import CreateResearchFolder, RenameResearchFolder
from thesistrace.research_folder.service import ResearchFolderService
from thesistrace.researcher import ResearcherService


def test_persisted_cursor_key_and_folder_version_survive_connection_restart(tmp_path: Path) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        ResearcherService(database).bootstrap(TEST_RESEARCHER)
        folders = ResearchFolderService(database)
        for i in range(55):
            folders.create(TEST_RESEARCHER.researcher_id, CreateResearchFolder(name=f"研究-{i:03}"))
        records = folders.list(TEST_RESEARCHER.researcher_id).items
        args = dict(
            identity=str(TEST_RESEARCHER.researcher_id),
            query={"tool": "folders"},
            limit=20,
            build=lambda kept, next_cursor: ResearchContextFolders(
                items=kept, next_cursor=next_cursor
            ),
        )
        first = ResearchAgentPagination.from_database(database).page(records, cursor=None, **args)
        assert first.next_cursor is not None
        database.close()
        database = PostgresDatabase(settings.database_url)
        database.open()
        folders = ResearchFolderService(database)
        paginator = ResearchAgentPagination.from_database(database)
        seen = list(first.items)
        cursor = first.next_cursor
        while cursor is not None:
            page = paginator.page(
                folders.list(TEST_RESEARCHER.researcher_id).items, cursor=cursor, **args
            )
            assert len(page.model_dump_json().encode("utf-8")) <= 32 * 1024
            seen.extend(page.items)
            cursor = page.next_cursor
        assert seen == records
        with pytest.raises(InvalidPageCursor):
            paginator.page(
                records, cursor=first.next_cursor, **(args | {"identity": "another-owner"})
            )
        changed = next(item for item in records if item.name == "研究-000")
        folders.rename(
            TEST_RESEARCHER.researcher_id, changed.id, RenameResearchFolder(name="Changed")
        )
        with pytest.raises(InvalidPageCursor):
            paginator.page(
                folders.list(TEST_RESEARCHER.researcher_id).items, cursor=first.next_cursor, **args
            )
    finally:
        database.close()
        drop_product_schemas(settings)
