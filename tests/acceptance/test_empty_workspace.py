import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings


def make_settings(root: Path) -> Settings:
    return Settings(
        metadata_path=root / "metadata.sqlite3",
        object_root=root / "objects",
        worker_stale_after_seconds=30,
    )


def test_empty_workspace_is_persistent_and_reports_dependency_health(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        workspace_response = client.get("/api/v1/workspace")
        health_response = client.get("/api/v1/health")

    assert workspace_response.status_code == 200
    first_workspace = workspace_response.json()
    assert first_workspace["installation_id"]
    assert first_workspace["resource_counts"] == {
        "dataset_releases": 0,
        "research_definitions": 0,
        "research_runs": 0,
        "daily_tracks": 0,
    }
    assert first_workspace["latest_dataset_release"] is None

    assert health_response.status_code == 200
    assert health_response.json() == {
        "status": "degraded",
        "components": {
            "database": {"status": "available"},
            "object_store": {"status": "available"},
            "worker": {"status": "unavailable", "last_heartbeat_at": None},
        },
    }

    with TestClient(create_app(settings)) as client:
        missing = client.get("/api/v1/research-runs/missing")
        unknown_route = client.get("/api/v1/not-a-resource")
        missing_header = client.post(
            "/api/v1/dataset-releases/bootstrap",
            json={"fixture": "v1"},
        )
    assert missing.status_code == 404
    assert missing.json()["detail"] == {
        "reason_code": "RESEARCH_RUN_NOT_FOUND",
        "message": "ResearchRun not found",
    }
    assert unknown_route.status_code == 404
    assert unknown_route.json()["detail"]["reason_code"] == "ROUTE_NOT_FOUND"
    assert missing_header.status_code == 422
    assert missing_header.json()["detail"]["reason_code"] == "REQUEST_VALIDATION_FAILED"

    with TestClient(create_app(settings)) as restarted_client:
        restarted_workspace = restarted_client.get("/api/v1/workspace").json()

    assert restarted_workspace["installation_id"] == first_workspace["installation_id"]


def test_worker_cli_heartbeat_becomes_visible_through_public_health_api(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)):
        pass

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.worker",
            "--once",
            "--metadata",
            str(settings.metadata_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health").json()

    assert health["status"] == "available"
    assert health["components"]["worker"]["status"] == "available"
    assert health["components"]["worker"]["last_heartbeat_at"] is not None


def test_parallel_health_probes_do_not_interfere_with_each_other(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)

    def read_object_store_status(_: int) -> str:
        with TestClient(app) as client:
            response = client.get("/api/v1/health")
        assert response.status_code == 200
        return str(response.json()["components"]["object_store"]["status"])

    with ThreadPoolExecutor(max_workers=16) as executor:
        statuses = list(executor.map(read_object_store_status, range(64)))

    assert statuses == ["available"] * 64
