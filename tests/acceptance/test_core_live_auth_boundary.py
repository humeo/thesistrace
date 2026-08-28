from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient
from live_auth import create_live_login_session, run_auth_operator
from test_core_current_head_research_run_execution import (
    _publish_head,
    _run_command,
    _run_worker_once,
)
from test_core_research_batch_admission import _factor_command

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS/Auth runtime is not configured",
)
@pytest.mark.parametrize(
    ("access_command", "email"),
    (
        ("deactivate", "live-core-deactivation@example.test"),
        ("revoke-sessions", "live-core-session-revocation@example.test"),
    ),
)
def test_real_workers_continue_after_access_is_revoked(
    tmp_path: Path,
    access_command: str,
    email: str,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    login = create_live_login_session(email)
    request_headers = {
        "cookie": login.cookie,
        "origin": _public_origin(),
    }

    seed_sessions = ("2026-08-03", "2026-08-04", "2026-08-05")
    seed_head = _publish_head(settings, sessions=seed_sessions, price_offset=0)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/research-folders").status_code == 401
        bootstrap = client.post(
            "/api/researcher/bootstrap",
            headers=request_headers,
        )
        assert bootstrap.status_code == 200, bootstrap.text
        researcher_id = bootstrap.json()["researcher_id"]
        assert bootstrap.json()["system_folders"] == {
            "default": "folder_default",
            "batch_research": "folder_batch_research",
        }
        folders = client.get(
            "/api/research-folders",
            headers={"cookie": login.cookie},
        )
        assert folders.status_code == 200

        seed = client.post(
            "/api/research-runs",
            headers=request_headers,
            json=_run_command("live-auth-track-seed"),
        )
        assert seed.status_code == 202, seed.text
        runtime = client.app.state.core_runtime
        assert runtime.research_runs.process_next() is True
        track = client.post(
            f"/api/research-runs/{seed.json()['id']}/daily-tracks",
            headers=request_headers,
            json={"request_id": "live-auth-track-start"},
        )
        assert track.status_code == 201, track.text
        _publish_head(
            settings,
            sessions=(*seed_sessions, "2026-08-06"),
            price_offset=1,
            expected_manifest=seed_head,
        )

        pending_run = client.post(
            "/api/research-runs",
            headers=request_headers,
            json=_run_command(
                "live-auth-pending-run",
                research_kind="factor_evaluation",
            ),
        )
        assert pending_run.status_code == 202, pending_run.text
        pending_batch = client.post(
            "/api/research-batches",
            headers=request_headers,
            json=_factor_command("live-auth-pending-batch"),
        )
        assert pending_batch.status_code == 202, pending_batch.text

        mutation = run_auth_operator(access_command, "--email", login.email)
        assert mutation == {
            "command": access_command,
            "researcher_id": researcher_id,
            "status": "updated",
        }
        assert client.get(
            f"/api/research-runs/{pending_run.json()['id']}",
            headers={"cookie": login.cookie},
        ).status_code == 401

        for role in ("research", "batch-research", "tracking"):
            worker = _run_worker_once(settings, role)
            assert worker.returncode == 0, worker.stderr

    assert _worker_outcomes(
        settings,
        run_id=pending_run.json()["id"],
        batch_id=pending_batch.json()["id"],
        track_id=track.json()["id"],
    ) == {"batch": "succeeded", "run": "succeeded", "track": "active"}


def _public_origin() -> str:
    value = os.environ.get("THESISTRACE_PUBLIC_ORIGIN", "")
    if not value:
        raise RuntimeError("THESISTRACE_PUBLIC_ORIGIN is unavailable")
    return value


def _worker_outcomes(
    settings: CoreSettings,
    *,
    run_id: str,
    batch_id: str,
    track_id: str,
) -> dict[str, str]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    (SELECT status FROM research_runs.runs WHERE id = %s) AS run,
                    (SELECT status FROM research_batches.batches WHERE id = %s) AS batch,
                    (SELECT status FROM daily_tracks.tracks WHERE id = %s) AS track
                """,
                (run_id, batch_id, track_id),
            ).fetchone()
        assert row is not None
        return {name: str(value) for name, value in row.items()}
    finally:
        database.close()
