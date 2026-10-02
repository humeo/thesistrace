import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from core_runtime import TEST_RESEARCHER, drop_product_schemas
from core_runtime import create_initialized_test_app as create_app
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from thesistrace._postgres import PostgresDatabase
from thesistrace.alpha_language import alpha_language
from thesistrace.data import DatasetAdmissionSnapshot
from thesistrace.data.models import DatasetCoverage
from thesistrace.entrypoints.quota_policy import quota_policy_lookup
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_folder import (
    BATCH_RESEARCH_FOLDER_ID,
    DEFAULT_FOLDER_ID,
    CreateResearchFolder,
    ResearchFolderService,
)
from thesistrace.research_run import ImmutableRunInput, ResearchRunService
from thesistrace.research_run.models import ResearchRunAdmissionCommand
from thesistrace.researcher import ResearcherService


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_folder_names_are_unique_per_researcher_after_trimming_and_ignoring_case() -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        created = client.post("/api/research-folders", json={"name": "Signals"})
        assert created.status_code == 201
        before = client.get("/api/research-folders").json()

        for name in ("Signals", "  Signals  ", "signals"):
            duplicate = client.post("/api/research-folders", json={"name": name})
            assert duplicate.status_code == 409
            assert duplicate.json() == {"detail": {"code": "FOLDER_NAME_EXISTS"}}
            assert client.get("/api/research-folders").json() == before

        second = client.post("/api/research-folders", json={"name": "Momentum"}).json()
        before_rename = client.get("/api/research-folders").json()
        duplicate_rename = client.patch(
            f"/api/research-folders/{second['id']}", json={"name": "  SIGNALS  "},
        )
        assert duplicate_rename.status_code == 409
        assert duplicate_rename.json() == {"detail": {"code": "FOLDER_NAME_EXISTS"}}
        assert client.get("/api/research-folders").json() == before_rename
        unchanged = client.patch(
            f"/api/research-folders/{created.json()['id']}", json={"name": "Signals"},
        )
        assert unchanged.status_code == 200
        assert unchanged.json() == created.json()

        for system_name in ("default", "Batch Research"):
            duplicate = client.post("/api/research-folders", json={"name": system_name})
            assert duplicate.status_code == 409
            assert duplicate.json() == {"detail": {"code": "FOLDER_NAME_EXISTS"}}

        database = client.app.state.core_runtime.database
        other = TEST_RESEARCHER.model_copy(update={"researcher_id": uuid4()})
        ResearcherService(database).bootstrap(other)
        service = ResearchFolderService(database)
        other_folder = service.create(other.researcher_id, CreateResearchFolder(name="Signals"))
        assert other_folder.name == "Signals"
        assert other_folder.id != created.json()["id"]
        assert client.get("/api/research-folders").json() == before_rename


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "operations", [("create", "create"), ("rename", "rename"), ("create", "rename")],
)
def test_concurrent_folder_mutations_accept_only_one_owner_of_a_name(operations) -> None:
    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        originals = [
            client.post("/api/research-folders", json={"name": name}).json()
            for name in ("First", "Second")
        ]
        barrier = Barrier(2, timeout=10)

        def submit(index):
            barrier.wait()
            name = "Concurrent Signals" if index == 0 else "  concurrent signals  "
            if operations[index] == "create":
                return client.post("/api/research-folders", json={"name": name})
            return client.patch(
                f"/api/research-folders/{originals[index]['id']}", json={"name": name},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = [executor.submit(submit, index) for index in range(2)]
            responses = [future.result(timeout=20) for future in pending]
        assert sum(response.status_code in {200, 201} for response in responses) == 1
        rejection = next(response for response in responses if response.status_code == 409)
        assert rejection.json() == {"detail": {"code": "FOLDER_NAME_EXISTS"}}
        stored = client.get("/api/research-folders").json()["items"]
        assert sum(folder["name"].lower() == "concurrent signals" for folder in stored) == 1
        for original, operation, response in zip(originals, operations, responses, strict=True):
            if operation == "create" or response.status_code == 409:
                assert original in stored


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
        for system_id in (DEFAULT_FOLDER_ID, BATCH_RESEARCH_FOLDER_ID):
            rename_system = client.patch(
                f"/api/research-folders/{system_id}", json={"name": "Other"},
            )
            assert rename_system.status_code == 409
            assert rename_system.json() == {"detail": {"code": "SYSTEM_FOLDER_RENAME_FORBIDDEN"}}
            delete_system = client.delete(f"/api/research-folders/{system_id}")
            assert delete_system.status_code == 409
            assert delete_system.json() == {"detail": {"code": "SYSTEM_FOLDER_DELETE_FORBIDDEN"}}

        sessions = (date(2026, 8, 3), date(2026, 8, 4))
        snapshot = DatasetAdmissionSnapshot(
        family_coverage={
            "equity.eod_price": DatasetCoverage(start=sessions[0], end=sessions[-1]),
        },
            generation_manifest_sha256="a" * 64,
            data_through_session=sessions[-1],
            coverage_start=sessions[0],
            coverage_end=sessions[-1],
            research_sessions=sessions,
            available_field_ids=frozenset({"price.close.adjusted"}),
            maximum_universe_cardinality=lambda _universe, _start, _end: 1,
            universe_member_union_cardinalities=lambda _universe, windows: tuple(
                1 for _ in windows
            ),
            financial_research_readiness="not_ready",
        )
        admitted = ResearchRunService(
            client.app.state.core_runtime.database,
            quota_policy=quota_policy_lookup(os.environ["THESISTRACE_AUTH_INTERNAL_ORIGIN"]),
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
            ),
        )
        assert admitted.status == "queued"

        nonempty = client.delete(f"/api/research-folders/{folder['id']}")
        assert nonempty.status_code == 409
        assert nonempty.json() == {"detail": {"code": "FOLDER_NOT_EMPTY"}}
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
