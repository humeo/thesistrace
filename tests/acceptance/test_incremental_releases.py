from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings


def test_incremental_catchup_and_correction_releases_form_one_immutable_chain(
    tmp_path: Path,
) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        root = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "root"},
            json={"fixture": "v1"},
        ).json()["release"]

        daily_response = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "daily-1"},
            json={"new_sessions": 1, "corrections": []},
        )
        assert daily_response.status_code == 201
        daily = daily_response.json()["release"]
        assert daily["predecessor_id"] == root["id"]
        assert daily["session_count"] == 757
        assert daily["appended_session_range"]["start"] == daily["appended_session_range"]["end"]
        assert daily["correction_change_set"] == []
        root_hashes = {item["sha256"] for item in root["objects"]}
        daily_hashes = {item["sha256"] for item in daily["objects"]}
        assert root_hashes < daily_hashes
        assert {item["kind"] for item in daily["objects"]} >= {
            "source_delta",
            "canonical_delta",
        }

        invalid = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "correction-only"},
            json={
                "new_sessions": 0,
                "corrections": [
                    {
                        "session": root["appended_session_range"]["start"],
                        "instrument_id": "equity:600000.SH",
                        "field": "close_raw",
                        "value": "9.9900",
                    }
                ],
            },
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/workspace").json()["latest_dataset_release"]["id"] == daily["id"]

        catchup = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "catchup-3"},
            json={"new_sessions": 3, "corrections": []},
        ).json()["release"]
        assert catchup["predecessor_id"] == daily["id"]
        assert catchup["session_count"] == 760
        assert catchup["appended_session_range"]["start"] < catchup["appended_session_range"]["end"]
        assert client.get("/api/v1/workspace").json()["resource_counts"]["dataset_releases"] == 3

        correction = {
            "session": root["appended_session_range"]["start"],
            "instrument_id": "equity:600000.SH",
            "field": "close_raw",
            "value": "9.9900",
        }
        corrected_response = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "daily-with-correction"},
            json={"new_sessions": 1, "corrections": [correction]},
        )
        assert corrected_response.status_code == 201
        corrected = corrected_response.json()["release"]
        assert corrected["predecessor_id"] == catchup["id"]
        assert corrected["session_count"] == 761
        assert corrected["correction_change_set"] == [correction]

        repeated = client.post(
            "/api/v1/dataset-releases/publish-fixture",
            headers={"Idempotency-Key": "daily-with-correction"},
            json={"new_sessions": 1, "corrections": [correction]},
        )
        assert repeated.status_code == 200
        assert repeated.json()["release"]["id"] == corrected["id"]

        latest_contract = client.get(
            f"/api/v1/dataset-releases/{corrected['id']}/data-contract"
        ).json()
        assert latest_contract["calendar"]["session_count"] == 761
        assert client.get("/api/v1/dataset-releases/root-does-not-exist").status_code == 404
        assert client.get(f"/api/v1/dataset-releases/{root['id']}").json() == root
