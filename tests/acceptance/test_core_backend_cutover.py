from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from test_core_daily_track_activation import _drop_product_schemas

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
FASTAPI_FRAMEWORK_ROUTES = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
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
        first_update = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-37-first-release"},
            json={},
        )
        assert first_update.status_code == 202
        _run_default_worker(settings, fixture_availability="1")
        assert client.get("/api/data").json()["latest_update_outcome"] == "published"

        admitted = client.post(
            "/api/definitions/run",
            json={
                "request_id": "ticket-37-cutover",
                "alpha": {
                    "operator_id": "ts_mean",
                    "operands": [
                        {"field_id": "price.close.adjusted"},
                        {"literal": 20},
                    ],
                },
                "universe": "top1000",
                "neutralization": "industry",
                "holdings_count": 30,
                "rebalance_every_sessions": 5,
            },
        )
        assert admitted.status_code == 200
        run = admitted.json()["run"]
        assert run["status"] == "queued"
        _run_default_worker(settings, fixture_availability="1")
        run = client.get(f"/api/research-runs/{run['id']}").json()
        assert run["status"] == "succeeded"

        started = client.post(
            f"/api/research-runs/{run['id']}/daily-tracks",
            json={"request_id": "ticket-37-start-tracking"},
        )
        assert started.status_code == 201
        track = started.json()
        later_update = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-37-later-release"},
            json={},
        )
        assert later_update.status_code == 202
        _run_default_worker(settings, fixture_availability="2")
        advanced = client.get(f"/api/daily-tracks/{track['id']}").json()
        assert advanced["head_release_id"] != track["seed_release_id"]
        before = _resource_snapshot(client, run_id=run["id"], track_id=track["id"])
        authoritative_before = _authoritative_snapshot(settings)

    _run_default_worker(settings, fixture_availability="2")

    with TestClient(create_app(settings)) as restarted:
        assert _public_routes(restarted) == PUBLIC_ROUTES
        assert _resource_snapshot(
            restarted,
            run_id=run["id"],
            track_id=track["id"],
        ) == before
        assert _authoritative_snapshot(settings) == authoritative_before


def _public_routes(client: TestClient) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in client.app.routes
        if route.path not in FASTAPI_FRAMEWORK_ROUTES
        for method in route.methods
    }


def _resource_snapshot(
    client: TestClient,
    *,
    run_id: object,
    track_id: object,
) -> dict[str, object]:
    release_history = client.get("/api/data/releases").json()
    definitions = client.get("/api/definitions").json()
    return {
        "data": client.get("/api/data").json(),
        "releases": release_history,
        "release_details": [
            client.get(f"/api/data/releases/{release['id']}").json()
            for release in release_history["items"]
        ],
        "definitions": definitions,
        "definition_details": [
            client.get(f"/api/definitions/{definition['id']}").json()
            for definition in definitions["items"]
        ],
        "research_runs": client.get("/api/research-runs").json(),
        "research_run": client.get(f"/api/research-runs/{run_id}").json(),
        "daily_tracks": client.get("/api/daily-tracks").json(),
        "daily_track": client.get(f"/api/daily-tracks/{track_id}").json(),
    }


def _authoritative_snapshot(settings: CoreSettings) -> dict[str, object]:
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
            manifest_objects = transaction.execute(
                """
                SELECT manifest_sha256, ordinal, logical_name, object_sha256
                FROM publication.manifest_objects
                ORDER BY manifest_sha256, ordinal
                """
            ).fetchall()
            releases = transaction.execute(
                """
                SELECT id, predecessor_id, manifest_sha256
                FROM data.releases
                ORDER BY id
                """
            ).fetchall()
            runs = transaction.execute(
                """
                SELECT id, dataset_release_id, result_manifest_sha256, result_provenance
                FROM research_runs.runs
                ORDER BY id
                """
            ).fetchall()
            tracks = transaction.execute(
                """
                SELECT id, origin, current_release_id, head_manifest_sha256
                FROM daily_tracks.tracks
                ORDER BY id
                """
            ).fetchall()
            checkpoints = transaction.execute(
                """
                SELECT track_id, target_release_id, manifest_sha256, provenance
                FROM daily_tracks.checkpoints
                ORDER BY track_id, target_release_id
                """
            ).fetchall()
        return {
            "publication_manifests": manifests,
            "publication_objects": objects,
            "publication_manifest_objects": manifest_objects,
            "data_releases": releases,
            "research_runs": runs,
            "daily_tracks": tracks,
            "daily_track_checkpoints": checkpoints,
        }
    finally:
        database.close()


def _run_default_worker(settings: CoreSettings, *, fixture_availability: str) -> None:
    worker = shutil.which("thesistrace-worker")
    assert worker is not None
    completed = subprocess.run(
        [worker, "--once"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "THESISTRACE_DATABASE_URL": settings.database_url,
            "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
            "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
            "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
            "THESISTRACE_S3_BUCKET": settings.s3_bucket,
            "THESISTRACE_S3_REGION": settings.s3_region,
            "THESISTRACE_FIXTURE_AVAILABILITY_SEQUENCE": fixture_availability,
        },
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
