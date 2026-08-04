from __future__ import annotations

import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.daily_track import DailyTrackProgressionFailed
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import (
    PublicationNotFoundError,
    PublicationVerificationError,
    PublishedRef,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_missing_corrupt_stale_and_fence_mismatched_cache_rebuilds_same_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        control, rebuilt = _seed_two_tracks(client, "ticket-30-rebuild")
        first = _publish_successor(client, 1)
        assert runtime.daily_tracks.process_next() is True
        assert runtime.daily_tracks.process_next() is True

        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        control_path = cache.path(control["id"])
        rebuilt_path = cache.path(rebuilt["id"])
        assert control_path.is_file() and rebuilt_path.is_file()
        history = [rebuilt_path.read_bytes()]
        cache_hits: list[bool] = []
        original_load = cache.load

        def observe_load(**kwargs: object) -> object:
            result = original_load(**kwargs)
            cache_hits.append(result is not None)
            return result

        monkeypatch.setattr(cache, "load", observe_load)

        for available_sessions, damage in (
            (2, "missing"),
            (3, "corrupt"),
            (4, "stale-head"),
            (5, "stale-fence"),
            (6, "oversized"),
        ):
            target = _publish_successor(client, available_sessions)
            assert runtime.daily_tracks.process_next() is True

            if damage == "missing":
                rebuilt_path.unlink()
            elif damage == "corrupt":
                rebuilt_path.write_bytes(b"not-json")
            elif damage == "stale-head":
                rebuilt_path.write_bytes(history[-2])
            elif damage == "stale-fence":
                entry = json.loads(rebuilt_path.read_bytes())
                entry["fence"] = int(entry["fence"]) - 1
                rebuilt_path.write_text(
                    json.dumps(entry, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
            else:
                rebuilt_path.write_bytes(b"x" * (cache.max_bytes + 1))

            assert runtime.daily_tracks.process_next() is True
            assert (
                client.get(f"/api/daily-tracks/{control['id']}").json()["current_release_id"]
                == target["id"]
            )
            assert (
                client.get(f"/api/daily-tracks/{rebuilt['id']}").json()["current_release_id"]
                == target["id"]
            )
            assert _checkpoint_payload(runtime, control["id"], target["id"]) == (
                _checkpoint_payload(runtime, rebuilt["id"], target["id"])
            )
            assert rebuilt_path.is_file()
            assert rebuilt_path.stat().st_size <= cache.max_bytes
            entry = json.loads(rebuilt_path.read_bytes())
            assert entry["pending_alpha_sessions"] <= 21
            assert entry["rolling_factor_rows"] <= 1_512
            assert "checkpoint_zlib_base64" not in entry
            history.append(rebuilt_path.read_bytes())

        assert runtime.daily_tracks.process_next() is False
        assert True in cache_hits
        assert False in cache_hits
        assert sorted(cache.root.glob("*.json")) == sorted([control_path, rebuilt_path])
        assert _cache_schema_names(runtime.database) == []
        assert set(client.get(f"/api/daily-tracks/{rebuilt['id']}").json()) == {
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
        assert first["id"] != target["id"]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_fresh_worker_uses_empty_local_cache_and_rebuilds_from_publication() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as first_process:
        runtime = first_process.app.state.core_runtime
        track = _seed_track(first_process, "ticket-30-restart")
        first = _publish_successor(first_process, 1)
        assert runtime.daily_tracks.process_next() is True
        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        old_root = cache.root
        assert cache.path(track["id"]).is_file()

    assert not old_root.exists()
    with TestClient(create_app(settings)) as publisher_process:
        runtime = publisher_process.app.state.core_runtime
        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        assert cache.root != old_root
        assert list(cache.root.iterdir()) == []
        second = _publish_successor(publisher_process, 2)

    completed = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr

    with TestClient(create_app(settings)) as observer_process:
        runtime = observer_process.app.state.core_runtime
        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        assert list(cache.root.iterdir()) == []
        assert (
            observer_process.get(f"/api/daily-tracks/{track['id']}").json()["current_release_id"]
            == second["id"]
        )
        assert second["predecessor_id"] == first["id"]


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
@pytest.mark.parametrize(
    "publication_error",
    [
        pytest.param(
            PublicationVerificationError("injected Checkpoint verification failure"),
            id="unverifiable",
        ),
        pytest.param(
            PublicationNotFoundError("injected missing Checkpoint"),
            id="missing",
        ),
    ],
)
def test_missing_or_unverifiable_checkpoint_never_falls_back_to_valid_cache(
    monkeypatch: pytest.MonkeyPatch,
    publication_error: Exception,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track = _seed_track(client, "ticket-30-publication-failure")
        first = _publish_successor(client, 1)
        assert runtime.daily_tracks.process_next() is True
        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        cached = cache.path(track["id"]).read_bytes()
        before = _durable_counts(runtime.database, track["id"])
        _publish_successor(client, 2)

        def fail_verification(*_args: object, **_kwargs: object) -> object:
            raise publication_error

        monkeypatch.setattr(runtime.publication, "read", fail_verification)
        with pytest.raises(DailyTrackProgressionFailed) as failure:
            runtime.daily_tracks.process_next()
        assert isinstance(failure.value.__cause__, type(publication_error))
        assert (
            client.get(f"/api/daily-tracks/{track['id']}").json()["current_release_id"]
            == first["id"]
        )
        assert _durable_counts(runtime.database, track["id"]) == {
            **before,
            "progressions": before["progressions"] + 1,
            "attempts": before["attempts"] + 1,
        }
        assert cache.path(track["id"]).read_bytes() == cached


def _seed_two_tracks(
    client: TestClient,
    request_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    first = _seed_track(client, request_id)
    runtime = client.app.state.core_runtime
    rerun = client.post(
        f"/api/research-runs/{first['seed_run_id']}/rerun",
        json={"request_id": f"{request_id}-rerun"},
    )
    assert rerun.status_code == 202
    assert runtime.research_runs.process_next() is True
    started = client.post(
        f"/api/research-runs/{rerun.json()['id']}/daily-tracks",
        json={"request_id": f"{request_id}-second-track"},
    )
    assert started.status_code == 201
    return first, started.json()


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


def _publish_successor(client: TestClient, available_sessions: int) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data._source = FixtureDataSource(sessions_after_bootstrap=available_sessions)
    accepted = client.post(
        "/api/data/update",
        headers={"Idempotency-Key": f"ticket-30-release-{available_sessions}"},
        json={},
    )
    assert accepted.status_code == 202
    assert runtime.data.process_next_update() is True
    latest = client.get("/api/data").json()["latest_release"]
    assert latest is not None
    return latest


def _checkpoint_payload(runtime: object, track_id: str, release_id: str) -> object:
    with runtime.database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT manifest_sha256, provenance
            FROM daily_tracks.checkpoints
            WHERE track_id = %s AND target_release_id = %s
            """,
            (track_id, release_id),
        ).fetchone()
    assert row is not None
    bundle = runtime.publication.read(
        PublishedRef(
            manifest_sha256=row["manifest_sha256"],
            kind="daily-track.checkpoint",
            provenance=row["provenance"],
        )
    )
    return json.loads(bundle.payloads["checkpoint"].content)


def _durable_counts(database: PostgresDatabase, track_id: str) -> dict[str, int]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
              (SELECT count(*) FROM daily_tracks.progressions
               WHERE track_id = %s) AS progressions,
              (SELECT count(*) FROM daily_tracks.progression_attempts
               WHERE track_id = %s) AS attempts,
              (SELECT count(*) FROM daily_tracks.checkpoints
               WHERE track_id = %s) AS checkpoints
            """,
            (track_id, track_id, track_id),
        ).fetchone()
    assert row is not None
    return {key: int(value) for key, value in row.items()}


def _cache_schema_names(database: PostgresDatabase) -> list[str]:
    with database.transaction() as transaction:
        rows = transaction.execute(
            """
            SELECT DISTINCT table_name || '.' || column_name AS name
            FROM information_schema.columns
            WHERE table_schema = 'daily_tracks'
              AND (table_name ILIKE '%cache%' OR column_name ILIKE '%cache%')
            ORDER BY name
            """
        ).fetchall()
    return [str(row["name"]) for row in rows]


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
