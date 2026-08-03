from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime


def test_data_update_returns_before_worker_publishes_first_fixture_release(
) -> None:
    core_settings = CoreSettings.from_environment()
    database = PostgresDatabase(core_settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()
    with TestClient(create_app(core_settings)) as client:
        accepted = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-10-first-release"},
        )

        assert accepted.status_code == 202
        assert accepted.json() == {
            "request_id": "ticket-10-first-release",
            "outcome": "accepted",
        }
        assert client.get("/api/data").json() == {
            "status": "updating",
            "latest_release": None,
            "latest_update_outcome": None,
        }

    with open_core_runtime(core_settings) as runtime:
        assert runtime.data.process_next_update()

    with TestClient(create_app(core_settings)) as client:
        overview = client.get("/api/data")
        assert overview.status_code == 200
        payload = overview.json()
        assert payload["status"] == "idle"
        assert payload["latest_update_outcome"] == "published"
        release = payload["latest_release"]
        assert release["predecessor_id"] is None
        assert release["session_count"] == 756
        assert release["covered_session_range"]["start"] < release[
            "covered_session_range"
        ]["end"]
        assert "manifest_sha256" not in release
        assert "object_key" not in release

        history = client.get("/api/data/releases").json()
        assert history == {"items": [release], "next_cursor": None}
        detail = client.get(f"/api/data/releases/{release['id']}")
        assert detail.status_code == 200
        assert detail.json() == release

    with open_core_runtime(core_settings) as runtime:
        canonical = runtime.data.load_canonical(release["id"])
        assert len(canonical["research_calendar"]) == 756
        assert canonical["schema_version"] == "canonical-eod-v1"
