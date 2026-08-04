from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import PublicationUnavailableError, PublishedRef


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_active_track_advances_only_to_one_direct_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        run = _admit_and_execute(client)
        started = client.post(
            f"/api/research-runs/{run['id']}/daily-tracks",
            json={"request_id": "ticket-27-start"},
        )
        assert started.status_code == 201
        seed_track = started.json()
        track_id = seed_track["id"]
        seed_release_id = seed_track["seed_release_id"]
        assert seed_track["current_release_id"] == seed_release_id

        with runtime.database.transaction() as transaction:
            assert runtime.data.next_release(transaction, seed_release_id) is None

        successor_id = _publish_successor(client, "ticket-27-successor")
        with runtime.database.transaction() as transaction:
            successor = runtime.data.next_release(transaction, seed_release_id)
        assert successor is not None
        assert successor.id == successor_id
        assert successor.predecessor_id == seed_release_id

        original_next_release = runtime.daily_tracks._next_release

        def fail_claim(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("injected claim failure")

        runtime.daily_tracks._next_release = fail_claim
        with pytest.raises(RuntimeError, match="injected claim failure"):
            runtime.daily_tracks.process_next()
        runtime.daily_tracks._next_release = original_next_release
        assert _track_state(settings, track_id) == {
            "current_release_id": seed_release_id,
            "head_manifest_sha256": None,
            "execution_fence": 0,
        }
        assert _counts(settings) == {"progressions": 0, "checkpoints": 0}

        observed_sessions: list[list[str]] = []
        original_advance = runtime.daily_tracks._advance_kernel

        def stale_advance(advance_input: object) -> object:
            snapshot = advance_input.new_canonical_snapshot()
            observed_sessions.append(list(snapshot["research_calendar"]))
            state = original_advance(advance_input)
            _increment_fence(settings, track_id)
            return state

        runtime.daily_tracks._advance_kernel = stale_advance
        assert runtime.daily_tracks.process_next() is True
        runtime.daily_tracks._advance_kernel = original_advance
        assert _track_state(settings, track_id)["current_release_id"] == seed_release_id
        assert _counts(settings) == {"progressions": 1, "checkpoints": 0}
        _clear_injected_stale_claim(settings, track_id, successor_id)

        def observed_advance(advance_input: object) -> object:
            snapshot = advance_input.new_canonical_snapshot()
            observed_sessions.append(list(snapshot["research_calendar"]))
            return original_advance(advance_input)

        runtime.daily_tracks._advance_kernel = observed_advance
        assert runtime.daily_tracks.process_next() is True
        runtime.daily_tracks._advance_kernel = original_advance
        advanced = client.get(f"/api/daily-tracks/{track_id}").json()
        assert advanced == {
            **seed_track,
            "current_release_id": successor_id,
            "strategy_session": successor.appended_session_end,
        }
        assert observed_sessions == [
            [successor.appended_session_end],
            [successor.appended_session_end],
        ]
        assert _counts(settings) == {"progressions": 1, "checkpoints": 1}
        assert runtime.daily_tracks.process_next() is False
        assert _counts(settings) == {"progressions": 1, "checkpoints": 1}

        checkpoint = _checkpoint(settings, track_id, successor_id)
        assert checkpoint["predecessor_release_id"] == seed_release_id
        provenance = checkpoint["provenance"]
        assert provenance["daily_track_id"] == track_id
        assert provenance["target_release_id"] == successor_id
        assert provenance["target_predecessor_id"] == seed_release_id
        assert provenance["predecessor"] == {
            "kind": "tracking.origin",
            "seed_release_id": seed_release_id,
            "seed_result_checksum_sha256": seed_track["result_checksum_sha256"],
        }
        assert provenance["calculation_contracts"]
        published = runtime.publication.read(
            PublishedRef(
                manifest_sha256=checkpoint["manifest_sha256"],
                kind="daily-track.checkpoint",
                provenance=provenance,
            )
        )
        state = json.loads(published.payloads["checkpoint"].content)
        assert state["schema_version"] == "daily-track-kernel-state-v1"
        assert state["canonical"]["research_calendar"][-1] == successor.appended_session_end

        rerun = client.post(
            f"/api/research-runs/{run['id']}/rerun",
            json={"request_id": "ticket-27-publication-failure-run"},
        )
        assert rerun.status_code == 202
        second_run = rerun.json()
        assert runtime.research_runs.process_next() is True
        second_started = client.post(
            f"/api/research-runs/{second_run['id']}/daily-tracks",
            json={"request_id": "ticket-27-publication-failure-track"},
        )
        assert second_started.status_code == 201
        second_track_id = second_started.json()["id"]
        before_failure = _track_state(settings, second_track_id)
        before_manifest_count = _manifest_count(settings)

        def fail_record(*_args: object, **_kwargs: object) -> object:
            raise PublicationUnavailableError("injected Publication failure")

        monkeypatch.setattr(runtime.publication, "record", fail_record)
        with pytest.raises(PublicationUnavailableError):
            runtime.daily_tracks.process_next()
        after_failure = _track_state(settings, second_track_id)
        assert after_failure["current_release_id"] == before_failure["current_release_id"]
        assert after_failure["head_manifest_sha256"] == before_failure["head_manifest_sha256"]
        assert _manifest_count(settings) == before_manifest_count
        assert (
            _checkpoint(
                settings,
                second_track_id,
                successor_id,
                required=False,
            )
            is None
        )

        assert client.post(f"/api/daily-tracks/{track_id}/advance").status_code in {
            404,
            405,
        }


def _admit_and_execute(client: TestClient) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data.update("ticket-27-seed-release")
    assert runtime.data.process_next_update() is True
    response = client.post(
        "/api/definitions/run",
        json={
            "request_id": "ticket-27-seed-run",
            "name": "ticket-27",
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


def _publish_successor(client: TestClient, request_id: str) -> str:
    response = client.post(
        "/api/data/update",
        headers={"Idempotency-Key": request_id},
        json={},
    )
    assert response.status_code == 202
    runtime = client.app.state.core_runtime
    assert runtime.data.process_next_update() is True
    latest = client.get("/api/data").json()["latest_release"]
    assert latest is not None
    return str(latest["id"])


def _track_state(settings: CoreSettings, track_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT current_release_id, head_manifest_sha256, execution_fence
                FROM daily_tracks.tracks
                WHERE id = %s
                """,
                (track_id,),
            ).fetchone()
            assert row is not None
            return dict(row)
    finally:
        database.close()


def _counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            progression = transaction.execute(
                "SELECT count(*) AS count FROM daily_tracks.progressions"
            ).fetchone()
            checkpoint = transaction.execute(
                "SELECT count(*) AS count FROM daily_tracks.checkpoints"
            ).fetchone()
            assert progression is not None and checkpoint is not None
            return {
                "progressions": int(progression["count"]),
                "checkpoints": int(checkpoint["count"]),
            }
    finally:
        database.close()


def _checkpoint(
    settings: CoreSettings,
    track_id: str,
    release_id: str,
    *,
    required: bool = True,
) -> dict[str, object] | None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT predecessor_release_id, manifest_sha256, provenance,
                       strategy_session
                FROM daily_tracks.checkpoints
                WHERE track_id = %s AND target_release_id = %s
                """,
                (track_id, release_id),
            ).fetchone()
            if required:
                assert row is not None
            return None if row is None else dict(row)
    finally:
        database.close()


def _manifest_count(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT count(*) AS count FROM publication.manifests"
            ).fetchone()
            assert row is not None
            return int(row["count"])
    finally:
        database.close()


def _increment_fence(settings: CoreSettings, track_id: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE daily_tracks.tracks
                SET execution_fence = execution_fence + 1
                WHERE id = %s
                """,
                (track_id,),
            )
    finally:
        database.close()


def _clear_injected_stale_claim(
    settings: CoreSettings,
    track_id: str,
    release_id: str,
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                DELETE FROM daily_tracks.progressions
                WHERE track_id = %s AND target_release_id = %s
                """,
                (track_id, release_id),
            )
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
