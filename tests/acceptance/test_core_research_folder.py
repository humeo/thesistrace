import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_folder import DEFAULT_FOLDER_ID


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fresh_core_has_exactly_one_deterministic_default_folder_and_public_read_contract() -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/research-folders")
        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {
                    "id": DEFAULT_FOLDER_ID,
                    "name": "Default",
                    "is_default": True,
                    "created_at": response.json()["items"][0]["created_at"],
                }
            ],
            "next_cursor": None,
        }

    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS count,
                       count(*) FILTER (WHERE is_default) AS default_count,
                       min(id) AS only_id
                FROM research_folders.folders
                """
            ).fetchone()
        assert row == {"count": 1, "default_count": 1, "only_id": DEFAULT_FOLDER_ID}
    finally:
        database.close()

    with TestClient(create_app(settings)) as restarted:
        folders = restarted.get("/api/research-folders").json()["items"]
        assert [(folder["id"], folder["is_default"]) for folder in folders] == [
            (DEFAULT_FOLDER_ID, True)
        ]
