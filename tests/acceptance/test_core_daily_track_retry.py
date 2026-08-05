from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.worker import _process_once
from thesistrace.research_kernel import KernelRunError

PUBLIC_BLOCKED_REASON = "DailyTrack could not process this Dataset Release."


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_retry_targets_only_the_existing_failed_release_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as first_process:
        runtime = first_process.app.state.core_runtime
        seed_run = _admit_and_execute(first_process)
        first_track = _start_track(first_process, seed_run["id"], "ticket-34-first-track")
        second_run = _rerun_and_execute(first_process, seed_run["id"], "ticket-34-second-run")
        second_track = _start_track(
            first_process,
            second_run["id"],
            "ticket-34-second-track",
        )
        failed_target = _publish_successor(first_process, available_sessions=1)
        original_execute = runtime.daily_tracks._execute
        failed_ids = {first_track["id"], second_track["id"]}

        def fail_selected_tracks(claim: object) -> object:
            if claim.track_id in failed_ids and claim.target.id == failed_target["id"]:
                raise KernelRunError("private retry target failure")
            return original_execute(claim)

        monkeypatch.setattr(runtime.daily_tracks, "_execute", fail_selected_tracks)
        _process_once(runtime)
        assert _track_state(runtime.database, first_track["id"])["status"] == "blocked"
        assert _track_state(runtime.database, second_track["id"])["status"] == "blocked"
        newer_target = _publish_successor(first_process, available_sessions=2)
        run_count_before_retry = _run_count(runtime.database)

        assert _retry_receipt_count(runtime.database) == 0
        malformed = first_process.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "ticket-34-malformed", "target_release_id": newer_target["id"]},
        )
        assert malformed.status_code == 422
        assert _retry_receipt_count(runtime.database) == 0
        missing = first_process.post(
            "/api/daily-tracks/track_00000000000000000000/retry",
            json={"request_id": "ticket-34-missing"},
        )
        assert missing.status_code == 404
        assert _retry_receipt_count(runtime.database) == 0

        accepted = first_process.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "ticket-34-retry-first"},
        )
        assert accepted.status_code == 202
        accepted_outcome = accepted.json()
        assert accepted_outcome["status"] == "active"
        assert accepted_outcome["current_release_id"] == first_track["current_release_id"]
        assert _retry_receipt_count(runtime.database) == 1
        assert _progression_targets(runtime.database, first_track["id"]) == [
            {"target_release_id": failed_target["id"], "status": "running"}
        ]

        replay = first_process.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "ticket-34-retry-first"},
        )
        assert replay.status_code == 202
        assert replay.json() == accepted_outcome
        assert _retry_receipt_count(runtime.database) == 1
        assert _attempt_count(runtime.database, first_track["id"]) == 3

        conflict = first_process.post(
            f"/api/daily-tracks/{second_track['id']}/retry",
            json={"request_id": "ticket-34-retry-first"},
        )
        assert conflict.status_code == 409
        active_conflict = first_process.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "ticket-34-active-conflict"},
        )
        assert active_conflict.status_code == 409
        assert _retry_receipt_count(runtime.database) == 1

        monkeypatch.setattr(runtime.daily_tracks, "_execute", original_execute)
        assert runtime.daily_tracks.process_next() is True
        first_success = first_process.get(f"/api/daily-tracks/{first_track['id']}").json()
        assert first_success["status"] == "active"
        assert first_success["head_release_id"] == failed_target["id"]
        assert runtime.daily_tracks.process_next() is True
        caught_up = first_process.get(f"/api/daily-tracks/{first_track['id']}").json()
        assert caught_up["head_release_id"] == newer_target["id"]
        assert _run_count(runtime.database) == run_count_before_retry

        second_retry = first_process.post(
            f"/api/daily-tracks/{second_track['id']}/retry",
            json={"request_id": "ticket-34-retry-second"},
        )
        assert second_retry.status_code == 202
        monkeypatch.setattr(runtime.daily_tracks, "_execute", fail_selected_tracks)
        with pytest.raises(DailyTrackProgressionFailed):
            runtime.daily_tracks.process_next()
        second_failed = first_process.get(
            f"/api/daily-tracks/{second_track['id']}"
        ).json()
        assert second_failed["status"] == "blocked"
        assert second_failed["blocked_reason"] == PUBLIC_BLOCKED_REASON
        assert second_failed["head_release_id"] == second_track["current_release_id"]
        second_state = _track_state(runtime.database, second_track["id"])
        assert second_state["blocked_target_release_id"] == failed_target["id"]
        assert _attempt_count(runtime.database, second_track["id"]) == 4

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        replay = restarted_process.post(
            f"/api/daily-tracks/{first_track['id']}/retry",
            json={"request_id": "ticket-34-retry-first"},
        )
        assert replay.status_code == 202
        assert replay.json() == accepted_outcome
        assert _retry_receipt_count(runtime.database) == 2
        assert _attempt_count(runtime.database, first_track["id"]) == 5
        assert _attempt_count(runtime.database, second_track["id"]) == 4


def _track_state(database: PostgresDatabase, track_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT status, current_release_id, blocked_target_release_id, blocked_reason
            FROM daily_tracks.tracks
            WHERE id = %s
            """,
            (track_id,),
        ).fetchone()
    assert row is not None
    return row


def _progression_targets(database: PostgresDatabase, track_id: str) -> list[dict[str, object]]:
    with database.transaction() as transaction:
        return transaction.execute(
            """
            SELECT target_release_id, status
            FROM daily_tracks.progressions
            WHERE track_id = %s
            ORDER BY created_at, target_release_id
            """,
            (track_id,),
        ).fetchall()


def _attempt_count(database: PostgresDatabase, track_id: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT count(*) AS attempt_count
            FROM daily_tracks.progression_attempts
            WHERE track_id = %s
            """,
            (track_id,),
        ).fetchone()
    assert row is not None
    return int(row["attempt_count"])


def _retry_receipt_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS receipt_count FROM daily_tracks.retry_receipts"
        ).fetchone()
    assert row is not None
    return int(row["receipt_count"])


def _run_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute("SELECT count(*) AS run_count FROM research_runs.runs").fetchone()
    assert row is not None
    return int(row["run_count"])


def _admit_and_execute(client: TestClient) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data.update("ticket-34-seed-release")
    assert runtime.data.process_next_update() is True
    response = client.post(
        "/api/definitions/run",
        json={
            "request_id": "ticket-34-seed-run",
            "name": "ticket-34",
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
    runtime = client.app.state.core_runtime
    run = response.json()
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
    response = client.post(
        "/api/data/update",
        headers={"Idempotency-Key": f"ticket-34-release-{available_sessions}"},
        json={},
    )
    assert response.status_code == 202
    assert runtime.data.process_next_update() is True
    latest = client.get("/api/data").json()["latest_release"]
    assert latest is not None
    return latest


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
