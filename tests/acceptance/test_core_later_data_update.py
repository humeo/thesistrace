import json

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.data import DataService
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_later_release_preserves_root_and_orders_release_history() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _request_and_process(settings, "ticket-11-root")
    with open_core_runtime(settings) as runtime:
        root = runtime.data.list_releases().items[0]
        root_canonical = runtime.data.load_canonical(root.id)
        root_metadata = _release_metadata(runtime.database, root.id)
        root_calendar = root_canonical["research_calendar"]
        assert root_metadata["latest_release_id"] == root.id
        assert root_metadata["provenance"]["appended_session_range"] == {
            "start": root_calendar[0],
            "end": root_calendar[-1],
        }
        assert root_metadata["provenance"]["correction_change_set"] == []
    _request_and_process(settings, "ticket-11-direct")

    with open_core_runtime(settings) as runtime:
        releases = runtime.data.list_releases().items
        assert len(releases) == 2
        latest, preserved_root = releases
        assert latest.predecessor_id == root.id
        assert latest.session_count == 757
        assert preserved_root == root
        assert runtime.data.load_canonical(root.id) == root_canonical
        latest_canonical = runtime.data.load_canonical(latest.id)
        latest_calendar = latest_canonical["research_calendar"]
        assert len(latest_calendar) == 757
        latest_metadata = _release_metadata(runtime.database, latest.id)
        assert latest_metadata["latest_release_id"] == latest.id
        assert latest_metadata["provenance"]["appended_session_range"] == {
            "start": latest_calendar[-1],
            "end": latest_calendar[-1],
        }
        assert latest_metadata["provenance"]["correction_change_set"] == []

        with runtime.database.transaction() as transaction:
            transaction.execute(
                "UPDATE data.releases SET created_at = '2099-01-01' WHERE id = %s",
                (root.id,),
            )
            transaction.execute(
                "UPDATE data.releases SET created_at = '2000-01-01' WHERE id = %s",
                (latest.id,),
            )
        assert runtime.data.overview().latest_release == latest
        assert runtime.data.list_releases().items == [latest, root]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_wider_source_gap_is_one_internal_catch_up_release() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _request_and_process(settings, "ticket-11-catch-up-root")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-11-catch-up"},
        )
        assert response.status_code == 202
    with open_core_runtime(settings) as runtime:
        data = DataService(
            runtime.database,
            runtime.publication,
            FixtureDataSource(available_new_sessions=3),
        )
        assert data.process_next_update()
        releases = data.list_releases().items
        assert len(releases) == 2
        assert releases[0].predecessor_id == releases[1].id
        assert releases[0].session_count == 759
        latest_canonical = data.load_canonical(releases[0].id)
        latest_calendar = latest_canonical["research_calendar"]
        metadata = _release_metadata(runtime.database, releases[0].id)
        assert metadata["latest_release_id"] == releases[0].id
        assert metadata["provenance"]["appended_session_range"] == {
            "start": latest_calendar[-3],
            "end": latest_calendar[-1],
        }
        assert metadata["provenance"]["correction_change_set"] == []


def _request_and_process(settings: CoreSettings, request_id: str) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": request_id},
        )
        assert response.status_code == 202
    with open_core_runtime(settings) as runtime:
        assert runtime.data.process_next_update()


def _reset_core_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()


def _release_metadata(database: PostgresDatabase, release_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT state.latest_release_id, manifest.manifest_bytes
            FROM data.state AS state
            JOIN data.releases AS release ON release.id = %s
            JOIN publication.manifests AS manifest
              ON manifest.sha256 = release.manifest_sha256
            WHERE state.singleton = 1
            """,
            (release_id,),
        ).fetchone()
    assert row is not None
    manifest = json.loads(bytes(row["manifest_bytes"]))
    return {
        "latest_release_id": row["latest_release_id"],
        "provenance": manifest["provenance"],
    }
