from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_core_daily_track_retry import (
    _admit_and_execute,
    _publish_successor,
    _rerun_and_execute,
    _start_track,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.worker import _process_once
from thesistrace.research_kernel import KernelRunError


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_missing_daily_track_stop_is_a_typed_product_action() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/daily-tracks/track_00000000000000000000/stop",
            json={"request_id": "ticket-35-missing"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "DailyTrack not found"}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_active_and_blocked_tracks_stop_without_moving_their_heads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed_run = _admit_and_execute(client)
        active = _start_track(client, seed_run["id"], "ticket-35-active")
        first_release = _publish_successor(client, available_sessions=1)
        assert runtime.daily_tracks.process_next() is True
        cache = runtime.daily_tracks._working_cache
        assert cache is not None and cache.path(active["id"]).is_file()
        fence_before = _fence(runtime.database, active["id"])

        stopped = client.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={"request_id": "ticket-35-stop-active"},
        )
        assert stopped.status_code == 202
        assert stopped.json()["status"] == "stopped"
        assert stopped.json()["current_release_id"] == first_release["id"]
        assert _fence(runtime.database, active["id"]) == fence_before + 1
        assert not cache.path(active["id"]).exists()
        detail = client.get(f"/api/daily-tracks/{active['id']}").json()
        assert detail["status"] == "stopped"
        assert detail["head_release_id"] == first_release["id"]

        replay = client.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={"request_id": "ticket-35-stop-active"},
        )
        assert replay.json() == stopped.json()
        assert _fence(runtime.database, active["id"]) == fence_before + 1
        assert client.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={"request_id": "ticket-35-stop-again"},
        ).status_code == 409
        assert client.post(
            f"/api/daily-tracks/{active['id']}/retry",
            json={"request_id": "ticket-35-retry-stopped"},
        ).status_code == 409

        blocked_run = _rerun_and_execute(client, seed_run["id"], "ticket-35-blocked-run")
        blocked = _start_track(client, blocked_run["id"], "ticket-35-blocked")
        original_execute = runtime.daily_tracks._execute

        def fail_blocked(claim: object) -> object:
            if claim.track_id == blocked["id"]:
                raise KernelRunError("private stopped failure")
            return original_execute(claim)

        monkeypatch.setattr(runtime.daily_tracks, "_execute", fail_blocked)
        _process_once(runtime)
        assert client.get(f"/api/daily-tracks/{blocked['id']}").json()["status"] == "blocked"
        blocked_stop = client.post(
            f"/api/daily-tracks/{blocked['id']}/stop",
            json={"request_id": "ticket-35-stop-blocked"},
        )
        assert blocked_stop.status_code == 202
        assert blocked_stop.json()["status"] == "stopped"
        assert _progression_status(runtime.database, blocked["id"]) == "cancelled"

        later = _publish_successor(client, available_sessions=2)
        _process_once(runtime)
        assert client.get("/api/data").json()["latest_release"]["id"] == later["id"]
        assert client.get(f"/api/daily-tracks/{active['id']}").json()[
            "head_release_id"
        ] == first_release["id"]


def _fence(database: PostgresDatabase, track_id: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT execution_fence FROM daily_tracks.tracks WHERE id = %s",
            (track_id,),
        ).fetchone()
    assert row is not None
    return int(row["execution_fence"])


def _progression_status(database: PostgresDatabase, track_id: str) -> str:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT status FROM daily_tracks.progressions
            WHERE track_id = %s ORDER BY created_at DESC LIMIT 1
            """,
            (track_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _drop_product_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS daily_tracks CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS research_runs CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()
