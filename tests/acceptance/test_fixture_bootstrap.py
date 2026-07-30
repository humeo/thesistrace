from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings


def test_fixture_bootstrap_is_atomic_immutable_and_idempotent(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )

    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "bootstrap-fixture-v1"},
            json={"fixture": "v1"},
        )

        assert first.status_code == 201
        published = first.json()
        assert published["status"] == "succeeded"
        assert published["release"]["predecessor_id"] is None
        assert published["release"]["session_count"] == 756
        assert published["release"]["instrument_count"] >= 30
        assert published["release"]["correction_change_set"] == []
        assert published["release"]["appended_session_range"]["start"]
        assert published["release"]["appended_session_range"]["end"]
        assert {item["kind"] for item in published["release"]["objects"]} >= {
            "source_fixture",
            "canonical_partition",
        }
        assert all(len(item["sha256"]) == 64 for item in published["release"]["objects"])

        repeated = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "bootstrap-fixture-v1"},
            json={"fixture": "v1"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["release"]["id"] == published["release"]["id"]

        workspace = client.get("/api/v1/workspace").json()
        assert workspace["resource_counts"]["dataset_releases"] == 1
        assert workspace["latest_dataset_release"]["id"] == published["release"]["id"]

        first_object = published["release"]["objects"][0]
        object_response = client.get(f"/api/v1/objects/{first_object['sha256']}")
        assert object_response.status_code == 200
        assert object_response.headers["etag"] == f'"sha256:{first_object["sha256"]}"'

        canonical_object = next(
            item
            for item in published["release"]["objects"]
            if item["kind"] == "canonical_partition"
        )
        parquet_response = client.get(
            f"/api/v1/objects/{canonical_object['sha256']}"
        )
        assert parquet_response.status_code == 200
        assert parquet_response.headers["content-type"] == "application/vnd.apache.parquet"
        assert parquet_response.headers["etag"] == (
            f'"sha256:{canonical_object["sha256"]}"'
        )

        failed = client.post(
            "/api/v1/dataset-releases/bootstrap",
            headers={"Idempotency-Key": "invalid-bootstrap"},
            json={"fixture": "invalid"},
        )
        assert failed.status_code == 422

        after_failure = client.get("/api/v1/workspace").json()
        assert after_failure["resource_counts"]["dataset_releases"] == 1
        assert after_failure["latest_dataset_release"]["id"] == published["release"]["id"]
