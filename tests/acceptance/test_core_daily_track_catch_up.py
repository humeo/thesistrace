from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.worker import _process_once
from thesistrace.publication import PublishedRef


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_lagging_tracks_catch_up_every_direct_successor_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        seed_run = _admit_and_execute(client)
        first_track = _start_track(client, seed_run["id"], "ticket-28-first-track")
        seed_release_id = first_track["current_release_id"]
        seed_session = first_track["strategy_session"]

        releases = [_publish_successor(client, available_sessions=count) for count in (1, 2, 3)]
        assert [release["predecessor_id"] for release in releases] == [
            seed_release_id,
            releases[0]["id"],
            releases[1]["id"],
        ]
        assert client.get("/api/data").json()["latest_release"]["id"] == releases[-1]["id"]

        observed_heads: list[str] = []
        for release in releases:
            assert runtime.daily_tracks.process_next() is True
            detail = client.get(f"/api/daily-tracks/{first_track['id']}").json()
            observed_heads.append(detail["current_release_id"])
            assert detail["current_release_id"] == release["id"]
            assert detail["strategy_session"] == release["covered_session_range"]["end"]
        assert observed_heads == [release["id"] for release in releases]
        assert runtime.daily_tracks.process_next() is False

        checkpoints = _checkpoint_rows(settings, first_track["id"])
        assert [row["target_release_id"] for row in checkpoints] == observed_heads
        assert [row["predecessor_release_id"] for row in checkpoints] == [
            seed_release_id,
            releases[0]["id"],
            releases[1]["id"],
        ]
        for index, row in enumerate(checkpoints):
            bundle = runtime.publication.read(
                PublishedRef(
                    manifest_sha256=row["manifest_sha256"],
                    kind="daily-track.checkpoint",
                    provenance=row["provenance"],
                )
            )
            payload = json.loads(bundle.payloads["checkpoint"].content)
            assert (
                payload["canonical"]["research_calendar"][-1]
                == releases[index]["covered_session_range"]["end"]
            )
            predecessor = row["provenance"]["predecessor"]
            if index == 0:
                assert predecessor["kind"] == "tracking.origin"
            else:
                assert predecessor == {
                    "kind": "daily-track.checkpoint",
                    "manifest_sha256": checkpoints[index - 1]["manifest_sha256"],
                    "release_id": releases[index - 1]["id"],
                }

        worker_run = _rerun_and_execute(client, seed_run["id"], "ticket-28-worker-run")
        worker_track = _start_track(client, worker_run["id"], "ticket-28-worker-track")
        _process_once(runtime)
        worker_detail = client.get(f"/api/daily-tracks/{worker_track['id']}").json()
        assert worker_detail["current_release_id"] == releases[-1]["id"]
        assert len(_checkpoint_rows(settings, worker_track["id"])) == 3

        failed_run = _rerun_and_execute(client, seed_run["id"], "ticket-28-failed-run")
        failed_track = _start_track(client, failed_run["id"], "ticket-28-failed-track")
        original_advance = runtime.daily_tracks._advance_kernel

        def fail_middle(advance_input: object) -> object:
            sessions = advance_input.new_canonical_snapshot()["research_calendar"]
            if sessions == [releases[1]["covered_session_range"]["end"]]:
                raise RuntimeError("injected middle target failure")
            return original_advance(advance_input)

        monkeypatch.setattr(runtime.daily_tracks, "_advance_kernel", fail_middle)
        with pytest.raises(RuntimeError, match="injected middle target failure"):
            _process_once(runtime)
        failed_detail = client.get(f"/api/daily-tracks/{failed_track['id']}").json()
        assert failed_detail["current_release_id"] == releases[0]["id"]
        assert failed_detail["strategy_session"] != seed_session
        assert [
            row["target_release_id"] for row in _checkpoint_rows(settings, failed_track["id"])
        ] == [releases[0]["id"]]
        assert _running_target(settings, failed_track["id"]) == releases[1]["id"]
        assert runtime.daily_tracks.process_next() is False
        assert client.get("/api/data").json()["latest_release"]["id"] == releases[-1]["id"]

        assert client.post(f"/api/daily-tracks/{failed_track['id']}/catch-up").status_code in {
            404,
            405,
        }


def _admit_and_execute(client: TestClient) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data.update("ticket-28-seed-release")
    assert runtime.data.process_next_update() is True
    response = client.post(
        "/api/definitions/run",
        json={
            "request_id": "ticket-28-seed-run",
            "name": "ticket-28",
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
    assert response.status_code == 200
    run = response.json()["run"]
    assert runtime.research_runs.process_next() is True
    completed = client.get(f"/api/research-runs/{run['id']}").json()
    assert completed["status"] == "succeeded"
    return completed


def _rerun_and_execute(client: TestClient, run_id: str, request_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/research-runs/{run_id}/rerun",
        json={"request_id": request_id},
    )
    assert response.status_code == 202
    run = response.json()
    runtime = client.app.state.core_runtime
    assert runtime.research_runs.process_next() is True
    completed = client.get(f"/api/research-runs/{run['id']}").json()
    assert completed["status"] == "succeeded"
    return completed


def _start_track(client: TestClient, run_id: str, request_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/research-runs/{run_id}/daily-tracks",
        json={"request_id": request_id},
    )
    assert response.status_code == 201
    return response.json()


def _publish_successor(client: TestClient, *, available_sessions: int) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data._source = FixtureDataSource(sessions_after_bootstrap=available_sessions)
    request_id = f"ticket-28-release-{available_sessions}"
    response = client.post(
        "/api/data/update",
        headers={"Idempotency-Key": request_id},
        json={},
    )
    assert response.status_code == 202
    assert runtime.data.process_next_update() is True
    latest = client.get("/api/data").json()["latest_release"]
    assert latest is not None
    return latest


def _checkpoint_rows(settings: CoreSettings, track_id: str) -> list[dict[str, object]]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            return transaction.execute(
                """
                SELECT target_release_id, predecessor_release_id,
                       manifest_sha256, provenance
                FROM daily_tracks.checkpoints
                WHERE track_id = %s
                ORDER BY created_at, target_release_id
                """,
                (track_id,),
            ).fetchall()
    finally:
        database.close()


def _running_target(settings: CoreSettings, track_id: str) -> str:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT target_release_id
                FROM daily_tracks.progressions
                WHERE track_id = %s AND status = 'running'
                """,
                (track_id,),
            ).fetchone()
            assert row is not None
            return str(row["target_release_id"])
    finally:
        database.close()


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
