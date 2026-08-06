from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.daily_track import DailyTrackService
from thesistrace.entrypoints.runtime import (
    CoreRuntime,
    CoreSettings,
    core_environment_is_configured,
)
from thesistrace.publication import PreparedPublication, Publication, PublishedRef
from thesistrace.research_kernel import AdvanceInput, KernelState
from thesistrace.research_kernel import advance as advance_kernel

_SUMMARY_FIELDS = {
    "id",
    "status",
    "seed_run_id",
    "seed_release_id",
    "current_release_id",
    "definition_id",
    "definition_revision",
    "result_checksum_sha256",
    "strategy_session",
}

_DETAIL_FIELDS = {
    "id",
    "status",
    "origin",
    "head_release_id",
    "strategy_session",
    "lag_releases",
    "blocked_reason",
    "factor",
    "strategy",
}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_0003_migration_backfills_existing_progressions_and_recovers_running() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as old_process:
        runtime = old_process.app.state.core_runtime
        succeeded_track = _seed_track(old_process, "ticket-29-upgrade")
        running_track = _rerun_track(
            old_process,
            succeeded_track["seed_run_id"],
            "ticket-29-upgrade-running",
        )
        successor = _publish_successor(old_process, 1)
        assert runtime.daily_tracks.process_next() is True
        assert (
            old_process.get(f"/api/daily-tracks/{succeeded_track['id']}").json()[
                "head_release_id"
            ]
            == successor["id"]
        )

        lost_worker = _service(
            runtime,
            progress=lambda stage, _track_id, _target_id: _lose_process(stage),
        )
        with pytest.raises(SystemExit, match="simulated DailyTrack worker loss"):
            lost_worker.process_next()
        with runtime.database.transaction() as transaction:
            transaction.execute("DROP TABLE daily_tracks.progression_attempts")
            deleted = transaction.execute(
                """
                DELETE FROM daily_tracks.schema_migrations
                WHERE name = '0003_recoverable_progression_attempts'
                """
            )
            assert deleted.rowcount == 1

    with TestClient(create_app(settings)) as upgraded_process:
        runtime = upgraded_process.app.state.core_runtime
        snapshots = {
            str(snapshot.pop("track_id")): snapshot
            for snapshot in _attempt_snapshots(runtime.database)
        }
        assert snapshots == {
            succeeded_track["id"]: {
                "status": "succeeded",
                "ordinal": 1,
                "fence": 1,
                "expired": True,
                "finished": True,
                "failure_reason": None,
            },
            running_track["id"]: {
                "status": "running",
                "ordinal": 1,
                "fence": 1,
                "expired": True,
                "finished": False,
                "failure_reason": None,
            },
        }

        assert runtime.daily_tracks.process_next() is True
        recovered = upgraded_process.get(f"/api/daily-tracks/{running_track['id']}").json()
        assert recovered["head_release_id"] == successor["id"]
        assert _durable_counts(runtime.database, running_track["id"]) == {
            "progressions": 1,
            "attempts": {"failed": 1, "succeeded": 1},
            "checkpoints": 1,
        }
        assert _failed_attempt_reasons(runtime.database, running_track["id"]) == ["WorkerLost"]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fresh_worker_recovers_interrupted_target_then_resumes_ordered_catch_up() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as first_process:
        runtime = first_process.app.state.core_runtime
        track = _seed_track(first_process, "ticket-29-restart")
        successors = [_publish_successor(first_process, count) for count in (1, 2)]
        lost_worker = _service(
            runtime,
            progress=lambda stage, _track_id, _target_id: _lose_process(stage),
        )

        with pytest.raises(SystemExit, match="simulated DailyTrack worker loss"):
            lost_worker.process_next()
        assert (
            first_process.get(f"/api/daily-tracks/{track['id']}").json()["head_release_id"]
            == track["seed_release_id"]
        )
        _expire_live_attempt(runtime.database, track["id"])

    with TestClient(create_app(settings)) as restarted_process:
        runtime = restarted_process.app.state.core_runtime
        assert runtime.daily_tracks.process_next() is True
        assert (
            restarted_process.get(f"/api/daily-tracks/{track['id']}").json()["head_release_id"]
            == successors[0]["id"]
        )
        assert runtime.daily_tracks.process_next() is True
        detail = restarted_process.get(f"/api/daily-tracks/{track['id']}").json()
        assert detail["head_release_id"] == successors[1]["id"]
        assert runtime.daily_tracks.process_next() is False
        assert _durable_counts(runtime.database, track["id"]) == {
            "progressions": 2,
            "attempts": {"failed": 1, "succeeded": 2},
            "checkpoints": 2,
        }
        assert _failed_attempt_reasons(runtime.database, track["id"]) == ["WorkerLost"]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_live_owner_renews_its_lease_and_duplicate_worker_cannot_claim() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    entered = Event()
    release = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track = _seed_track(client, "ticket-29-live-owner")
        successor = _publish_successor(client, 1)

        def block_kernel(advance_input: AdvanceInput) -> KernelState:
            entered.set()
            if not release.wait(timeout=30):
                raise TimeoutError("blocked DailyTrack Kernel was not released")
            return advance_kernel(advance_input)

        owner = _service(
            runtime,
            advance=block_kernel,
            lease_seconds=1,
            heartbeat_seconds=0.05,
        )
        duplicate = _service(runtime)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(owner.process_next)
            assert entered.wait(timeout=20)
            try:
                assert _wait_for_lease_renewal(runtime.database, track["id"])
                assert duplicate.process_next() is False
            finally:
                release.set()
            assert future.result(timeout=30) is True

        assert (
            client.get(f"/api/daily-tracks/{track['id']}").json()["head_release_id"]
            == successor["id"]
        )
        assert _durable_counts(runtime.database, track["id"]) == {
            "progressions": 1,
            "attempts": {"succeeded": 1},
            "checkpoints": 1,
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_recovered_winner_fences_stale_prepared_worker_and_public_state_is_clean() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    prepared = Event()
    release_stale = Event()

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track = _seed_track(client, "ticket-29-stale-owner")
        successor = _publish_successor(client, 1)

        def pause_after_prepare(stage: str, track_id: str, _target_id: str) -> None:
            if stage != "prepared":
                return
            _expire_live_attempt(runtime.database, track_id)
            prepared.set()
            if not release_stale.wait(timeout=30):
                raise TimeoutError("stale DailyTrack worker was not released")

        stale_publication = _PublicationRecordSpy(runtime.publication)
        stale = _service(
            runtime,
            publication=stale_publication,
            progress=pause_after_prepare,
        )
        winner = _service(runtime)
        with ThreadPoolExecutor(max_workers=1) as executor:
            stale_future = executor.submit(stale.process_next)
            assert prepared.wait(timeout=30)
            try:
                assert winner.process_next() is True
                winning_detail = client.get(f"/api/daily-tracks/{track['id']}").json()
                assert winning_detail["head_release_id"] == successor["id"]
            finally:
                release_stale.set()
            assert stale_future.result(timeout=30) is True

        assert client.get(f"/api/daily-tracks/{track['id']}").json() == winning_detail
        assert _durable_counts(runtime.database, track["id"]) == {
            "progressions": 1,
            "attempts": {"failed": 1, "succeeded": 1},
            "checkpoints": 1,
        }
        assert _failed_attempt_reasons(runtime.database, track["id"]) == ["WorkerLost"]
        assert stale_publication.record_calls == 0
        assert _checkpoint_publication_count(runtime.database, track["id"]) == 1
        assert winner.process_next() is False

        listed = client.get("/api/daily-tracks").json()
        assert set(winning_detail) == _DETAIL_FIELDS
        assert set(listed) == {"items", "next_cursor"}
        assert listed["next_cursor"] is None
        assert len(listed["items"]) == 1
        assert set(listed["items"][0]) == _SUMMARY_FIELDS


def _service(
    runtime: CoreRuntime,
    *,
    publication: object | None = None,
    advance: Callable[[AdvanceInput], KernelState] = advance_kernel,
    progress: Callable[[str, str, str], None] | None = None,
    lease_seconds: float = 15 * 60,
    heartbeat_seconds: float = 30,
) -> DailyTrackService:
    return DailyTrackService(
        runtime.database,
        publication=publication or runtime.publication,
        next_release=runtime.data.next_release,
        load_canonical=runtime.data.load_canonical,
        advance_kernel=advance,
        progress=progress,
        lease_seconds=lease_seconds,
        heartbeat_seconds=heartbeat_seconds,
    )


class _PublicationRecordSpy:
    def __init__(self, delegate: Publication) -> None:
        self._delegate = delegate
        self.record_calls = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    def record(
        self,
        transaction: PostgresTransaction,
        prepared: PreparedPublication,
    ) -> PublishedRef:
        self.record_calls += 1
        return self._delegate.record(transaction, prepared)


def _lose_process(stage: str) -> None:
    if stage == "claimed":
        raise SystemExit("simulated DailyTrack worker loss")


def _seed_track(client: TestClient, request_id: str) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data.update(f"{request_id}-seed-release")
    assert runtime.data.process_next_update() is True
    admitted = client.post(
        "/api/definitions/run",
        json={
            "request_id": f"{request_id}-run",
            "name": request_id,
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
    run_id = admitted.json()["run"]["id"]
    assert runtime.research_runs.process_next() is True
    started = client.post(
        f"/api/research-runs/{run_id}/daily-tracks",
        json={"request_id": f"{request_id}-track"},
    )
    assert started.status_code == 201
    return started.json()


def _rerun_track(
    client: TestClient,
    run_id: str,
    request_id: str,
) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    accepted = client.post(
        f"/api/research-runs/{run_id}/rerun",
        json={"request_id": f"{request_id}-run"},
    )
    assert accepted.status_code == 202
    rerun_id = accepted.json()["id"]
    assert runtime.research_runs.process_next() is True
    started = client.post(
        f"/api/research-runs/{rerun_id}/daily-tracks",
        json={"request_id": f"{request_id}-track"},
    )
    assert started.status_code == 201
    return started.json()


def _publish_successor(client: TestClient, available_sessions: int) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data._source = FixtureDataSource(sessions_after_bootstrap=available_sessions)
    accepted = client.post(
        "/api/data/update",
        headers={"Idempotency-Key": f"ticket-29-release-{available_sessions}"},
        json={},
    )
    assert accepted.status_code == 202
    assert runtime.data.process_next_update() is True
    latest = client.get("/api/data").json()["latest_release"]
    assert latest is not None
    return latest


def _expire_live_attempt(database: PostgresDatabase, track_id: str) -> None:
    with database.transaction() as transaction:
        updated = transaction.execute(
            """
            UPDATE daily_tracks.progression_attempts
            SET lease_expires_at = '2000-01-01'
            WHERE track_id = %s AND status = 'running'
            """,
            (track_id,),
        )
        assert updated.rowcount == 1


def _wait_for_lease_renewal(database: PostgresDatabase, track_id: str) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT heartbeat_at > started_at AS renewed
                FROM daily_tracks.progression_attempts
                WHERE track_id = %s AND status = 'running'
                """,
                (track_id,),
            ).fetchone()
        if row == {"renewed": True}:
            return True
        time.sleep(0.05)
    return False


def _attempt_snapshots(database: PostgresDatabase) -> list[dict[str, object]]:
    with database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT attempt.track_id, attempt.status, attempt.ordinal,
                   attempt.fence, attempt.lease_expires_at <= now() AS expired,
                   attempt.finished_at IS NOT NULL AS finished,
                   attempt.failure_reason
            FROM daily_tracks.progression_attempts AS attempt
            JOIN daily_tracks.progressions AS progression
              ON progression.track_id = attempt.track_id
             AND progression.target_release_id = attempt.target_release_id
            ORDER BY progression.created_at, attempt.track_id, attempt.ordinal
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _durable_counts(database: PostgresDatabase, track_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
              (SELECT count(*) FROM daily_tracks.progressions
               WHERE track_id = %s) AS progressions,
              (SELECT count(*) FROM daily_tracks.checkpoints
               WHERE track_id = %s) AS checkpoints
            """,
            (track_id, track_id),
        ).fetchone()
        attempts = transaction.execute(
            """
            SELECT status, count(*) AS count
            FROM daily_tracks.progression_attempts
            WHERE track_id = %s
            GROUP BY status
            """,
            (track_id,),
        ).fetchall()
    assert row is not None
    return {
        "progressions": int(row["progressions"]),
        "attempts": {str(item["status"]): int(item["count"]) for item in attempts},
        "checkpoints": int(row["checkpoints"]),
    }


def _failed_attempt_reasons(database: PostgresDatabase, track_id: str) -> list[str]:
    with database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT failure_reason
            FROM daily_tracks.progression_attempts
            WHERE track_id = %s AND status = 'failed'
            ORDER BY ordinal
            """,
            (track_id,),
        ).fetchall()
    return [str(row["failure_reason"]) for row in rows]


def _checkpoint_publication_count(database: PostgresDatabase, track_id: str) -> int:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT count(*) AS count
            FROM publication.manifests AS manifest
            JOIN daily_tracks.checkpoints AS checkpoint
              ON checkpoint.manifest_sha256 = manifest.sha256
            WHERE checkpoint.track_id = %s
              AND manifest.kind = 'daily-track.checkpoint'
            """,
            (track_id,),
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
