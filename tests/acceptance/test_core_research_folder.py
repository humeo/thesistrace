from datetime import date

import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionSnapshot
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_folder import BATCH_RESEARCH_FOLDER_ID, DEFAULT_FOLDER_ID
from thesistrace.research_run import ImmutableRunInput, ResearchRunService
from thesistrace.research_run.models import ResearchRunAdmissionCommand


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fresh_core_has_both_deterministic_system_folders_and_public_read_contract() -> None:
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
                },
                {
                    "id": BATCH_RESEARCH_FOLDER_ID,
                    "name": "Batch Research",
                    "is_default": False,
                    "created_at": response.json()["items"][1]["created_at"],
                },
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
                       count(*) FILTER (
                           WHERE id = 'folder_batch_research'
                       ) AS batch_folder_count
                FROM research_folders.folders
                """
            ).fetchone()
        assert row == {"count": 2, "default_count": 1, "batch_folder_count": 1}
    finally:
        database.close()

    with TestClient(create_app(settings)) as restarted:
        folders = restarted.get("/api/research-folders").json()["items"]
        assert [(folder["id"], folder["is_default"]) for folder in folders] == [
            (DEFAULT_FOLDER_ID, True),
            (BATCH_RESEARCH_FOLDER_ID, False),
        ]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_custom_folder_mutations_and_database_guards_are_transactional() -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        blank = client.post("/api/research-folders", json={"name": "   "})
        assert blank.status_code == 422
        nested = client.post(
            "/api/research-folders",
            json={"name": "Momentum", "parent_id": DEFAULT_FOLDER_ID},
        )
        assert nested.status_code == 422

        created = client.post("/api/research-folders", json={"name": "  Momentum  "})
        assert created.status_code == 201
        folder = created.json()
        assert folder["name"] == "Momentum"
        assert folder["is_default"] is False
        assert client.get("/api/research-folders").json()["items"][-1] == folder

        renamed = client.patch(
            f"/api/research-folders/{folder['id']}",
            json={"name": "Signals"},
        )
        assert renamed.status_code == 200
        assert renamed.json() == {**folder, "name": "Signals"}
        assert client.patch(
            f"/api/research-folders/{DEFAULT_FOLDER_ID}",
            json={"name": "Other"},
        ).status_code == 409
        assert client.delete(f"/api/research-folders/{DEFAULT_FOLDER_ID}").status_code == 409

        sessions = (date(2026, 8, 3), date(2026, 8, 4))
        snapshot = DatasetAdmissionSnapshot(
            generation_manifest_sha256="a" * 64,
            data_through_session=sessions[-1],
            coverage_start=sessions[0],
            coverage_end=sessions[-1],
            research_sessions=sessions,
            available_field_ids=frozenset({"price.close.adjusted"}),
            maximum_universe_cardinality=lambda _universe, _start, _end: 1,
            financial_research_readiness="not_ready",
        )
        admitted = ResearchRunService(
            client.app.state.core_runtime.database,
            compile_formula=alpha_language.compile,
            current_dataset=lambda: snapshot,
        ).admit(
            TEST_RESEARCHER.researcher_id,
            TypeAdapter(ResearchRunAdmissionCommand).validate_python(
                {
                    "request_id": "folder-guard",
                    "folder_id": folder["id"],
                    "name": "Folder guard",
                    "formula": "close",
                    "start_date": sessions[0].isoformat(),
                    "end_date": sessions[-1].isoformat(),
                    "universe": "top300",
                    "neutralization": "none",
                    "research_kind": "factor_evaluation",
                }
            )
        )
        assert admitted.status == "queued"

        nonempty = client.delete(f"/api/research-folders/{folder['id']}")
        assert nonempty.status_code == 409
        assert nonempty.json() == {"detail": "A nonempty Folder cannot be deleted"}
        assert client.get("/api/research-folders").json()["items"][-1]["name"] == "Signals"

        second = client.post("/api/research-folders", json={"name": "Disposable"}).json()
        deleted = client.delete(f"/api/research-folders/{second['id']}")
        assert deleted.status_code == 204
        assert client.delete(f"/api/research-folders/{second['id']}").status_code == 404

        database = PostgresDatabase(settings.database_url)
        database.open()
        try:
            with database.transaction() as transaction:
                columns = transaction.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'research_folders' AND table_name = 'folders'
                    ORDER BY ordinal_position
                    """
                ).fetchall()
                stored_run = transaction.execute(
                    """
                    SELECT folder_id, status, immutable_input
                    FROM research_runs.runs
                    WHERE id = %s
                    """,
                    (admitted.id,),
                ).fetchone()
            assert [row["column_name"] for row in columns] == [
                "researcher_id",
                "id",
                "name",
                "is_default",
                "created_at",
                "updated_at",
            ]
            assert stored_run is not None
            assert stored_run["folder_id"] == folder["id"]
            assert stored_run["status"] == "queued"
            immutable_input = ImmutableRunInput.model_validate(
                stored_run["immutable_input"]
            )
            assert immutable_input.research_kind == "factor_evaluation"
            assert immutable_input.canonical_value() == stored_run["immutable_input"]
        finally:
            database.close()
