from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.worker import _process_once
from thesistrace.research_kernel import KernelRunError

PUBLIC_BLOCKED_REASON = "DailyTrack could not process this Dataset Release."
INTERNAL_TERMS = (
    "attempt",
    "ordinal",
    "fence",
    "claim",
    "secret kernel failure",
    "object_key",
    "manifest",
    "workerlost",
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_one_failed_track_blocks_without_stalling_data_or_another_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as first_process:
        runtime = first_process.app.state.core_runtime
        seed_run = _admit_and_execute(first_process)
        failed_track = _start_track(
            first_process,
            seed_run["id"],
            "ticket-33-failed-track",
        )
        other_run = _rerun_and_execute(
            first_process,
            seed_run["id"],
            "ticket-33-other-run",
        )
        other_track = _start_track(
            first_process,
            other_run["id"],
            "ticket-33-other-track",
        )
        first_target = _publish_successor(first_process, available_sessions=1)
        publication_count_before_failure = _publication_count(runtime.database)
        original_execute = runtime.daily_tracks._execute

        def fail_only_one_track(claim: object) -> object:
            if (
                claim.track_id == failed_track["id"]
                and claim.target.id == first_target["id"]
            ):
                raise KernelRunError("secret kernel failure for ticket 33")
            return original_execute(claim)

        monkeypatch.setattr(runtime.daily_tracks, "_execute", fail_only_one_track)
        _process_once(runtime)

        blocked = first_process.get(
            f"/api/daily-tracks/{failed_track['id']}"
        ).json()
        progressed = first_process.get(
            f"/api/daily-tracks/{other_track['id']}"
        ).json()
        assert blocked["status"] == "blocked"
        assert blocked["blocked_reason"] == PUBLIC_BLOCKED_REASON
        assert blocked["head_release_id"] == failed_track["current_release_id"]
        assert progressed["status"] == "active"
        assert progressed["head_release_id"] == first_target["id"]
        _assert_public_projection_is_sanitized(blocked)
        listed = first_process.get("/api/daily-tracks").json()
        assert {item["id"]: item["status"] for item in listed["items"]} == {
            failed_track["id"]: "blocked",
            other_track["id"]: "active",
        }
        _assert_public_projection_is_sanitized(listed)

        blocked_snapshot = _track_snapshot(runtime.database, failed_track["id"])
        assert blocked_snapshot == {
            "status": "blocked",
            "current_release_id": failed_track["current_release_id"],
            "head_manifest_sha256": None,
            "blocked_target_release_id": first_target["id"],
            "blocked_reason": PUBLIC_BLOCKED_REASON,
            "checkpoint_count": 0,
            "progression_status": "blocked",
            "attempts": [
                {"ordinal": ordinal, "status": "failed", "failure_reason": "KernelRunError"}
                for ordinal in (1, 2, 3)
            ],
        }
        assert _publication_count(runtime.database) == publication_count_before_failure + 1

        second_target = _publish_successor(first_process, available_sessions=2)
        _process_once(runtime)
        assert first_process.get("/api/data").json()["latest_release"]["id"] == second_target["id"]
        assert (
            first_process.get(f"/api/daily-tracks/{other_track['id']}").json()[
                "head_release_id"
            ]
            == second_target["id"]
        )
        assert _track_snapshot(runtime.database, failed_track["id"]) == blocked_snapshot
        assert _publication_count(runtime.database) > publication_count_before_failure

    with TestClient(create_app(settings)) as restarted_process:
        restarted_runtime = restarted_process.app.state.core_runtime
        restarted = restarted_process.get(
            f"/api/daily-tracks/{failed_track['id']}"
        ).json()
        assert restarted["status"] == "blocked"
        assert restarted["blocked_reason"] == PUBLIC_BLOCKED_REASON
        assert restarted["head_release_id"] == failed_track["current_release_id"]
        assert _track_snapshot(restarted_runtime.database, failed_track["id"]) == blocked_snapshot
        assert restarted_runtime.daily_tracks.process_next() is False
        assert _track_snapshot(restarted_runtime.database, failed_track["id"]) == blocked_snapshot


def _assert_public_projection_is_sanitized(projection: object) -> None:
    serialized = json.dumps(projection, sort_keys=True).lower()
    for term in INTERNAL_TERMS:
        assert term not in serialized


def _track_snapshot(database: PostgresDatabase, track_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        track = transaction.execute(
            """
            SELECT status, current_release_id, head_manifest_sha256,
                   blocked_target_release_id, blocked_reason
            FROM daily_tracks.tracks
            WHERE id = %s
            """,
            (track_id,),
        ).fetchone()
        progression = transaction.execute(
            """
            SELECT status
            FROM daily_tracks.progressions
            WHERE track_id = %s
            ORDER BY created_at, target_release_id
            """,
            (track_id,),
        ).fetchone()
        attempts = transaction.execute(
            """
            SELECT ordinal, status, failure_reason
            FROM daily_tracks.progression_attempts
            WHERE track_id = %s
            ORDER BY ordinal
            """,
            (track_id,),
        ).fetchall()
        checkpoint = transaction.execute(
            """
            SELECT count(*) AS checkpoint_count
            FROM daily_tracks.checkpoints
            WHERE track_id = %s
            """,
            (track_id,),
        ).fetchone()
    assert track is not None and progression is not None and checkpoint is not None
    return {
        **track,
        "checkpoint_count": int(checkpoint["checkpoint_count"]),
        "progression_status": progression["status"],
        "attempts": attempts,
    }


def _publication_count(database: PostgresDatabase) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            "SELECT count(*) AS publication_count FROM publication.manifests"
        ).fetchone()
    assert row is not None
    return int(row["publication_count"])


def _admit_and_execute(client: TestClient) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data.update("ticket-33-seed-release")
    assert runtime.data.process_next_update() is True
    response = client.post(
        "/api/definitions/run",
        json={
            "request_id": "ticket-33-seed-run",
            "name": "ticket-33",
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
    request_id = f"ticket-33-release-{available_sessions}"
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
