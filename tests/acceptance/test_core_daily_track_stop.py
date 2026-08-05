from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_core_daily_track_retry import (
    _admit_and_execute,
    _publish_successor,
    _rerun_and_execute,
    _start_track,
)

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import DailyTrackService
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
        detail_before = client.get(f"/api/daily-tracks/{active['id']}").json()
        checkpoint_count_before = _checkpoint_count(runtime.database, active["id"])

        assert _stop_receipt_count(runtime.database) == 0
        malformed = client.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={
                "request_id": "ticket-35-malformed",
                "target_release_id": first_release["id"],
            },
        )
        assert malformed.status_code == 422
        assert _stop_receipt_count(runtime.database) == 0

        stopped = client.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={"request_id": "ticket-35-stop-active"},
        )
        assert stopped.status_code == 202
        assert stopped.json()["status"] == "stopped"
        assert stopped.json()["current_release_id"] == first_release["id"]
        assert _fence(runtime.database, active["id"]) == fence_before + 1
        assert _stop_receipt_count(runtime.database) == 1
        assert not cache.path(active["id"]).exists()
        detail = client.get(f"/api/daily-tracks/{active['id']}").json()
        assert detail["status"] == "stopped"
        assert detail["head_release_id"] == first_release["id"]
        assert detail["origin"] == detail_before["origin"]
        assert detail["factor"] == detail_before["factor"]
        assert detail["strategy"] == detail_before["strategy"]
        assert _checkpoint_count(runtime.database, active["id"]) == checkpoint_count_before

        cache.path(active["id"]).write_bytes(b"interrupted-cleanup")
        assert cache.path(active["id"]).is_file()
        replay = client.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={"request_id": "ticket-35-stop-active"},
        )
        assert replay.json() == stopped.json()
        assert _fence(runtime.database, active["id"]) == fence_before + 1
        assert _stop_receipt_count(runtime.database) == 1
        assert not cache.path(active["id"]).exists()
        assert (
            client.post(
                f"/api/daily-tracks/{active['id']}/stop",
                json={"request_id": "ticket-35-stop-again"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/daily-tracks/{active['id']}/retry",
                json={"request_id": "ticket-35-retry-stopped"},
            ).status_code
            == 409
        )

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
        cross_track_conflict = client.post(
            f"/api/daily-tracks/{blocked['id']}/stop",
            json={"request_id": "ticket-35-stop-active"},
        )
        assert cross_track_conflict.status_code == 409
        assert _stop_receipt_count(runtime.database) == 1
        blocked_stop = client.post(
            f"/api/daily-tracks/{blocked['id']}/stop",
            json={"request_id": "ticket-35-stop-blocked"},
        )
        assert blocked_stop.status_code == 202
        assert blocked_stop.json()["status"] == "stopped"
        assert _progression_status(runtime.database, blocked["id"]) == "cancelled"
        assert _stop_receipt_count(runtime.database) == 2
        assert (
            client.post(
                f"/api/daily-tracks/{blocked['id']}/retry",
                json={"request_id": "ticket-35-retry-blocked-stopped"},
            ).status_code
            == 409
        )

        later = _publish_successor(client, available_sessions=2)
        _process_once(runtime)
        assert client.get("/api/data").json()["latest_release"]["id"] == later["id"]
        assert (
            client.get(f"/api/daily-tracks/{active['id']}").json()["head_release_id"]
            == first_release["id"]
        )

        stopped_outcome = stopped.json()
        stopped_detail = client.get(f"/api/daily-tracks/{active['id']}").json()
        stopped_fence = _fence(runtime.database, active["id"])

    with TestClient(create_app(settings)) as restarted:
        runtime = restarted.app.state.core_runtime
        replay = restarted.post(
            f"/api/daily-tracks/{active['id']}/stop",
            json={"request_id": "ticket-35-stop-active"},
        )
        assert replay.status_code == 202
        assert replay.json() == stopped_outcome
        assert _fence(runtime.database, active["id"]) == stopped_fence
        assert _stop_receipt_count(runtime.database) == 2
        restarted_detail = restarted.get(f"/api/daily-tracks/{active['id']}").json()
        assert restarted_detail == stopped_detail
        assert restarted_detail["origin"] == detail_before["origin"]
        assert _checkpoint_count(runtime.database, active["id"]) == checkpoint_count_before


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_stop_fences_a_worker_that_prepared_before_publication() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    prepared = Event()
    release_worker = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed_run = _admit_and_execute(client)
        track = _start_track(client, seed_run["id"], "ticket-35-prepared-track")
        _publish_successor(client, available_sessions=1)
        head_before = client.get(f"/api/daily-tracks/{track['id']}").json()
        publication_count_before = _checkpoint_publication_count(runtime.database)
        checkpoint_count_before = _checkpoint_count(runtime.database, track["id"])

        def pause_after_prepare(stage: str, track_id: str, _target_id: str) -> None:
            if stage != "prepared" or track_id != track["id"]:
                return
            prepared.set()
            if not release_worker.wait(timeout=30):
                raise TimeoutError("prepared DailyTrack worker was not released")

        stale_worker = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            next_release=runtime.data.next_release,
            load_canonical=runtime.data.load_canonical,
            progress=pause_after_prepare,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale_worker.process_next)
            assert prepared.wait(timeout=30)
            fence_before_stop = _fence(runtime.database, track["id"])
            try:
                stopped = client.post(
                    f"/api/daily-tracks/{track['id']}/stop",
                    json={"request_id": "ticket-35-stop-prepared"},
                )
                assert stopped.status_code == 202
                assert stopped.json()["status"] == "stopped"
                assert _fence(runtime.database, track["id"]) == fence_before_stop + 1
                assert _progression_status(runtime.database, track["id"]) == "cancelled"
                assert _attempt_status(runtime.database, track["id"]) == "cancelled"
            finally:
                release_worker.set()
            assert future.result(timeout=30) is True

        stopped_detail = client.get(f"/api/daily-tracks/{track['id']}").json()
        assert stopped_detail["status"] == "stopped"
        assert stopped_detail["head_release_id"] == head_before["head_release_id"]
        assert _checkpoint_publication_count(runtime.database) == publication_count_before
        assert _checkpoint_count(runtime.database, track["id"]) == checkpoint_count_before
        assert _progression_status(runtime.database, track["id"]) == "cancelled"
        assert _attempt_status(runtime.database, track["id"]) == "cancelled"
        assert runtime.daily_tracks.process_next() is False


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_worker_reconciles_its_local_cache_after_http_stop(tmp_path: Path) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed_run = _admit_and_execute(client)
        track = _start_track(client, seed_run["id"], "ticket-35-worker-cache-track")
        successor = _publish_successor(client, available_sessions=1)
        worker = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            next_release=runtime.data.next_release,
            load_canonical=runtime.data.load_canonical,
            working_cache_root=tmp_path / "worker-local-cache",
        )
        assert worker.process_next() is True
        cache = worker._working_cache
        assert cache is not None and cache.path(track["id"]).is_file()

        stopped = client.post(
            f"/api/daily-tracks/{track['id']}/stop",
            json={"request_id": "ticket-35-stop-worker-cache"},
        )
        assert stopped.status_code == 202
        assert stopped.json()["current_release_id"] == successor["id"]
        assert cache.path(track["id"]).is_file()

        assert worker.reconcile_stopped_working_cache() == 1
        assert not cache.path(track["id"]).exists()
        assert worker.reconcile_stopped_working_cache() == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_worker_cannot_restore_cache_after_stop_follows_publication(
    tmp_path: Path,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    published = Event()
    release_worker = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed_run = _admit_and_execute(client)
        track = _start_track(client, seed_run["id"], "ticket-35-published-track")
        successor = _publish_successor(client, available_sessions=1)

        def pause_after_publication(stage: str, track_id: str, _target_id: str) -> None:
            if stage != "published" or track_id != track["id"]:
                return
            published.set()
            if not release_worker.wait(timeout=30):
                raise TimeoutError("published DailyTrack worker was not released")

        worker = DailyTrackService(
            runtime.database,
            publication=runtime.publication,
            next_release=runtime.data.next_release,
            load_canonical=runtime.data.load_canonical,
            progress=pause_after_publication,
            working_cache_root=tmp_path / "worker-local-cache",
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(worker.process_next)
            assert published.wait(timeout=10)
            try:
                stopped = client.post(
                    f"/api/daily-tracks/{track['id']}/stop",
                    json={"request_id": "ticket-35-stop-after-publication"},
                )
                assert stopped.status_code == 202
                assert stopped.json()["current_release_id"] == successor["id"]
            finally:
                release_worker.set()
            assert future.result(timeout=30) is True

        cache = worker._working_cache
        assert cache is not None
        assert not cache.path(track["id"]).exists()
        detail = client.get(f"/api/daily-tracks/{track['id']}").json()
        assert detail["status"] == "stopped"
        assert detail["head_release_id"] == successor["id"]


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


def _attempt_status(database: PostgresDatabase, track_id: str) -> str:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT status FROM daily_tracks.progression_attempts
            WHERE track_id = %s ORDER BY started_at DESC LIMIT 1
            """,
            (track_id,),
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _checkpoint_count(database: PostgresDatabase, track_id: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS count FROM daily_tracks.checkpoints WHERE track_id = %s",
            (track_id,),
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _checkpoint_publication_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT count(*) AS count FROM publication.manifests
            WHERE kind = 'daily-track.checkpoint'
            """
        ).fetchone()
    assert row is not None
    return int(row["count"])


def _stop_receipt_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS count FROM daily_tracks.stop_receipts"
        ).fetchone()
    assert row is not None
    return int(row["count"])


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
