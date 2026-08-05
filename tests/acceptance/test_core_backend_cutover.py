from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from test_core_daily_track_activation import _admit_and_execute, _drop_product_schemas

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured

PUBLIC_ROUTES = {
    ("GET", "/api/data"),
    ("GET", "/api/data/releases"),
    ("GET", "/api/data/releases/{release_id}"),
    ("POST", "/api/data/update"),
    ("GET", "/api/definitions"),
    ("POST", "/api/definitions"),
    ("GET", "/api/definitions/authoring-options"),
    ("POST", "/api/definitions/run"),
    ("GET", "/api/definitions/{definition_id}"),
    ("PUT", "/api/definitions/{definition_id}"),
    ("POST", "/api/definitions/{definition_id}/run"),
    ("GET", "/api/research-runs"),
    ("GET", "/api/research-runs/{run_id}"),
    ("POST", "/api/research-runs/{run_id}/cancel"),
    ("POST", "/api/research-runs/{run_id}/rerun"),
    ("POST", "/api/research-runs/{run_id}/daily-tracks"),
    ("GET", "/api/daily-tracks"),
    ("GET", "/api/daily-tracks/{track_id}"),
    ("POST", "/api/daily-tracks/{track_id}/retry"),
    ("POST", "/api/daily-tracks/{track_id}/stop"),
}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_default_backend_preserves_all_resources_and_publications_across_restart() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        assert _public_routes(client) == PUBLIC_ROUTES
        run = _admit_and_execute(client, request_id="ticket-37-cutover")
        started = client.post(
            f"/api/research-runs/{run['id']}/daily-tracks",
            json={"request_id": "ticket-37-start-tracking"},
        )
        assert started.status_code == 201
        track = started.json()
        before = _resource_snapshot(client, run_id=run["id"], track_id=track["id"])
        publications_before = _publication_snapshot(settings)

    worker = shutil.which("thesistrace-worker")
    assert worker is not None
    completed = subprocess.run(
        [worker, "--once"],
        check=False,
        capture_output=True,
        text=True,
        env=_core_environment(settings),
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr

    with TestClient(create_app(settings)) as restarted:
        assert _public_routes(restarted) == PUBLIC_ROUTES
        assert _resource_snapshot(
            restarted,
            run_id=run["id"],
            track_id=track["id"],
        ) == before
        assert _publication_snapshot(settings) == publications_before


def _public_routes(client: TestClient) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in client.app.routes
        if route.path.startswith("/api/")
        for method in route.methods
    }


def _resource_snapshot(
    client: TestClient,
    *,
    run_id: object,
    track_id: object,
) -> dict[str, object]:
    return {
        "data": client.get("/api/data").json(),
        "releases": client.get("/api/data/releases").json(),
        "definitions": client.get("/api/definitions").json(),
        "research_runs": client.get("/api/research-runs").json(),
        "research_run": client.get(f"/api/research-runs/{run_id}").json(),
        "daily_tracks": client.get("/api/daily-tracks").json(),
        "daily_track": client.get(f"/api/daily-tracks/{track_id}").json(),
    }


def _publication_snapshot(settings: CoreSettings) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            manifests = transaction.execute(
                "SELECT sha256, kind, manifest_bytes FROM publication.manifests ORDER BY sha256"
            ).fetchall()
            objects = transaction.execute(
                "SELECT sha256, byte_size FROM publication.objects ORDER BY sha256"
            ).fetchall()
        return {"manifests": manifests, "objects": objects}
    finally:
        database.close()


def _core_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
    }
