from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_core_daily_track_activation import (
    _admit_and_execute,
    _drop_product_schemas,
    _stored_seed,
)

from thesistrace._postgres import PostgresDatabase, apply_migrations
from thesistrace.daily_track.migrations import MIGRATIONS as DAILY_TRACK_MIGRATIONS
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS
from thesistrace.definition.migrations import MIGRATIONS as DEFINITION_MIGRATIONS
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import JsonPayload, PublishedRef
from thesistrace.publication.migrations import MIGRATIONS as PUBLICATION_MIGRATIONS
from thesistrace.research_run import ResearchRunTrackingUnavailable
from thesistrace.research_run.migrations import MIGRATIONS as RESEARCH_RUN_MIGRATIONS

ACTIVE_TRACK_LIMIT_DETAIL = "Active DailyTrack limit of 10 reached"


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_legacy_start_tracking_receipt_moves_to_research_runs_and_survives_restart() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
    seed_run_id = "run_ticket36_legacy"
    request_id = "ticket-36-legacy-receipt"
    track = {
        "id": "track_ticket36_legacy",
        "status": "active",
        "seed_run_id": seed_run_id,
        "seed_release_id": "release_ticket36_legacy",
        "current_release_id": "release_ticket36_legacy",
        "definition_id": "definition_ticket36_legacy",
        "definition_revision": 1,
        "result_checksum_sha256": "a" * 64,
        "strategy_session": "2025-12-31",
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "action": "research-runs.start-tracking/v1",
                "seed_run_id": seed_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        for plan in (
            PUBLICATION_MIGRATIONS,
            DATA_MIGRATIONS,
            DEFINITION_MIGRATIONS,
            RESEARCH_RUN_MIGRATIONS,
            DAILY_TRACK_MIGRATIONS,
        ):
            apply_migrations(database, plan)
        with database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    id, status, seed_run_id, origin,
                    current_release_id, current_strategy_session
                ) VALUES (%s, 'active', %s, %s, %s, %s)
                """,
                (
                    track["id"],
                    seed_run_id,
                    Jsonb({}),
                    track["current_release_id"],
                    track["strategy_session"],
                ),
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.activation_receipts (
                    request_id, request_fingerprint, track_id, outcome
                ) VALUES (%s, %s, %s, %s)
                """,
                (request_id, fingerprint, track["id"], Jsonb(track)),
            )
    finally:
        database.close()

    with TestClient(create_app(settings)) as upgraded:
        replay = upgraded.post(
            f"/api/research-runs/{seed_run_id}/daily-tracks",
            json={"request_id": request_id},
        )
        assert replay.status_code == 201
        assert replay.json() == track
        conflict = upgraded.post(
            "/api/research-runs/run_ticket36_other/daily-tracks",
            json={"request_id": request_id},
        )
        assert conflict.status_code == 409

    with TestClient(create_app(settings)) as restarted:
        replay = restarted.post(
            f"/api/research-runs/{seed_run_id}/daily-tracks",
            json={"request_id": request_id},
        )
        assert replay.status_code == 201
        assert replay.json() == track
        assert _admission_counts(restarted.app.state.core_runtime.database) == {
            "tracks": 1,
            "active_or_blocked": 1,
            "research_run_receipts": 1,
            "legacy_daily_track_receipts": 0,
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_start_tracking_receipt_and_track_commit_in_one_owned_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        runs = _eligible_runs(client, count=3)
        assert _admission_counts(runtime.database) == {
            "tracks": 0,
            "active_or_blocked": 0,
            "research_run_receipts": 0,
            "legacy_daily_track_receipts": 0,
        }

        malformed = client.post(
            f"/api/research-runs/{runs[0]['id']}/daily-tracks",
            json={"request_id": "ticket-36-malformed", "limit": 10},
        )
        assert malformed.status_code == 422
        assert _admission_counts(runtime.database)["research_run_receipts"] == 0

        barrier = Barrier(4)

        def start(index: int) -> object:
            barrier.wait(timeout=10)
            return client.post(
                f"/api/research-runs/{runs[0]['id']}/daily-tracks",
                json={"request_id": f"ticket-36-concurrent-{index}"},
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = [
                future.result(timeout=30)
                for future in [executor.submit(start, index) for index in range(4)]
            ]
        assert [response.status_code for response in responses] == [201] * 4
        track = responses[0].json()
        assert [response.json() for response in responses] == [track] * 4
        assert _admission_counts(runtime.database) == {
            "tracks": 1,
            "active_or_blocked": 1,
            "research_run_receipts": 4,
            "legacy_daily_track_receipts": 0,
        }

        replay = client.post(
            f"/api/research-runs/{runs[0]['id']}/daily-tracks",
            json={"request_id": "ticket-36-concurrent-0"},
        )
        assert replay.status_code == 201
        assert replay.json() == track
        assert _admission_counts(runtime.database)["research_run_receipts"] == 4

        conflict = client.post(
            f"/api/research-runs/{runs[1]['id']}/daily-tracks",
            json={"request_id": "ticket-36-concurrent-0"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "Start Tracking request_id conflicts"

        original_activate = runtime.research_runs._activate_track
        assert original_activate is not None

        def activate_then_fail(transaction: object, origin: object) -> object:
            original_activate(transaction, origin)
            raise ResearchRunTrackingUnavailable("injected activation rollback")

        monkeypatch.setattr(runtime.research_runs, "_activate_track", activate_then_fail)
        rolled_back = client.post(
            f"/api/research-runs/{runs[2]['id']}/daily-tracks",
            json={"request_id": "ticket-36-rollback"},
        )
        assert rolled_back.status_code == 409
        assert _admission_counts(runtime.database) == {
            "tracks": 1,
            "active_or_blocked": 1,
            "research_run_receipts": 4,
            "legacy_daily_track_receipts": 0,
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_tenth_track_wins_eleventh_is_rejected_and_stop_releases_capacity() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        runs = _eligible_runs(client, count=11)
        tracks: list[dict[str, object]] = []
        for index, run in enumerate(runs[:9]):
            response = client.post(
                f"/api/research-runs/{run['id']}/daily-tracks",
                json={"request_id": f"ticket-36-fill-{index}"},
            )
            assert response.status_code == 201
            tracks.append(response.json())
        _make_blocked(runtime.database, str(tracks[0]["id"]))
        assert _admission_counts(runtime.database)["active_or_blocked"] == 9

        barrier = Barrier(2)

        def race(index: int) -> object:
            barrier.wait(timeout=10)
            return client.post(
                f"/api/research-runs/{runs[9 + index]['id']}/daily-tracks",
                json={"request_id": f"ticket-36-capacity-race-{index}"},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            raced = [
                future.result(timeout=30)
                for future in [executor.submit(race, index) for index in range(2)]
            ]
        assert sorted(response.status_code for response in raced) == [201, 409]
        rejected_index = next(
            index for index, response in enumerate(raced) if response.status_code == 409
        )
        rejected = raced[rejected_index]
        assert rejected.json()["detail"] == ACTIVE_TRACK_LIMIT_DETAIL
        rejected_run = runs[9 + rejected_index]
        assert _admission_counts(runtime.database) == {
            "tracks": 10,
            "active_or_blocked": 10,
            "research_run_receipts": 10,
            "legacy_daily_track_receipts": 0,
        }
        assert not _has_start_receipt(
            runtime.database,
            f"ticket-36-capacity-race-{rejected_index}",
        )

        stopped_track = tracks[1]
        stopped = client.post(
            f"/api/daily-tracks/{stopped_track['id']}/stop",
            json={"request_id": "ticket-36-release-capacity"},
        )
        assert stopped.status_code == 202
        assert _admission_counts(runtime.database)["active_or_blocked"] == 9

        admitted_after_stop = client.post(
            f"/api/research-runs/{rejected_run['id']}/daily-tracks",
            json={"request_id": "ticket-36-after-stop"},
        )
        assert admitted_after_stop.status_code == 201
        assert admitted_after_stop.json()["seed_run_id"] == rejected_run["id"]
        assert _admission_counts(runtime.database) == {
            "tracks": 11,
            "active_or_blocked": 10,
            "research_run_receipts": 11,
            "legacy_daily_track_receipts": 0,
        }
        stopped_detail = client.get(f"/api/daily-tracks/{stopped_track['id']}").json()
        assert stopped_detail["status"] == "stopped"


def _eligible_runs(client: TestClient, *, count: int) -> list[dict[str, object]]:
    runtime = client.app.state.core_runtime
    first = _admit_and_execute(client, request_id="ticket-36-seed")
    if count == 1:
        return [first]
    stored = _stored_seed(CoreSettings.from_environment(), first["id"])
    source = runtime.publication.read(
        PublishedRef(
            manifest_sha256=str(stored["result_manifest_sha256"]),
            kind="research.result",
            provenance=dict(stored["result_provenance"]),
        )
    )
    payload = json.loads(source.payloads["result"].content)
    runs = [first]
    for index in range(1, count):
        run_id = f"run_ticket36_{index:02d}"
        provenance = {**stored["result_provenance"], "research_run_id": run_id}
        prepared = runtime.publication.prepare(
            kind="research.result",
            payloads={"result": JsonPayload(payload)},
            provenance=provenance,
        )
        with runtime.database.transaction() as transaction:
            published = runtime.publication.record(transaction, prepared)
            transaction.execute(
                """
                INSERT INTO research_runs.runs (
                    id, definition_id, definition_revision, dataset_release_id,
                    status, immutable_input, result_manifest_sha256,
                    result_provenance
                ) VALUES (%s, %s, %s, %s, 'succeeded', %s, %s, %s)
                """,
                (
                    run_id,
                    first["definition_id"],
                    first["definition_revision"],
                    first["dataset_release_id"],
                    Jsonb(stored["immutable_input"]),
                    published.manifest_sha256,
                    Jsonb(provenance),
                ),
            )
        runs.append({**first, "id": run_id})
    return runs


def _admission_counts(database: object) -> dict[str, int]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
              (SELECT count(*) FROM daily_tracks.tracks) AS tracks,
              (SELECT count(*) FROM daily_tracks.tracks
               WHERE status IN ('active', 'blocked')) AS active_or_blocked,
              (SELECT count(*) FROM research_runs.start_tracking_receipts)
                AS research_run_receipts,
              (SELECT count(*) FROM daily_tracks.activation_receipts)
                AS legacy_daily_track_receipts
            """
        ).fetchone()
    assert row is not None
    return {name: int(value) for name, value in row.items()}


def _has_start_receipt(database: object, request_id: str) -> bool:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT EXISTS (
              SELECT 1 FROM research_runs.start_tracking_receipts
              WHERE request_id = %s
            ) AS present
            """,
            (request_id,),
        ).fetchone()
    return row == {"present": True}


def _make_blocked(database: object, track_id: str) -> None:
    with database.transaction() as transaction:
        transaction.execute(
            """
            UPDATE daily_tracks.tracks
            SET status = 'blocked',
                blocked_target_release_id = 'release_ticket36_blocked',
                blocked_reason = 'DailyTrack could not process this Dataset Release.'
            WHERE id = %s
            """,
            (track_id,),
        )
