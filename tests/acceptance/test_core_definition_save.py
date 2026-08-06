import os
import subprocess
import sys

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_incomplete_nameless_definition_survives_http_and_worker_restart() -> None:
    settings = CoreSettings.from_environment()
    _drop_definitions_schema(settings)

    with TestClient(create_app(settings)) as client:
        created = client.post("/api/definitions", json={})

        assert created.status_code == 201
        definition = created.json()
        assert definition["id"].startswith("def_")
        assert definition["name"]
        assert definition["revision"] == 1
        assert definition["hypothesis"] is None
        assert definition["alpha"] is None
        assert definition["universe"] is None
        assert definition["neutralization"] is None
        assert definition["holdings_count"] is None
        assert definition["rebalance_every_sessions"] is None
        assert set(definition) == {
            "id",
            "revision",
            "name",
            "hypothesis",
            "alpha",
            "universe",
            "neutralization",
            "holdings_count",
            "rebalance_every_sessions",
        }

    _restart_worker_once(settings)

    with TestClient(create_app(settings)) as restarted_http:
        detail = restarted_http.get(f"/api/definitions/{definition['id']}")
        listed = restarted_http.get("/api/definitions")

        assert detail.status_code == 200
        assert detail.json() == definition
        assert listed.status_code == 200
        assert listed.json() == {
            "items": [
                {
                    "id": definition["id"],
                    "name": definition["name"],
                    "revision": 1,
                }
            ],
            "next_cursor": None,
        }

        renamed = restarted_http.put(
            f"/api/definitions/{definition['id']}",
            json={"expected_revision": 1, "name": "Quality without a hypothesis"},
        )
        assert renamed.status_code == 200
        assert renamed.json() == {
            **definition,
            "name": "Quality without a hypothesis",
            "revision": 2,
        }

    with TestClient(create_app(settings)) as final_http:
        reopened = final_http.get(f"/api/definitions/{definition['id']}")
        assert reopened.json()["name"] == "Quality without a hypothesis"
        assert reopened.json()["revision"] == 2


def _drop_definitions_schema(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
    finally:
        database.close()


def _restart_worker_once(settings: CoreSettings) -> None:
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
    }
    completed = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
