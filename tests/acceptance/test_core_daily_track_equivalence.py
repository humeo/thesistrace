from __future__ import annotations

import json

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.adapters.fixture_data import FixtureDataSource
from thesistrace.daily_track.service import DailyTrackEquivalenceMismatch
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import VerifiedBundle, VerifiedPayload
from thesistrace.publication.serialization import canonical_json_bytes


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_persisted_checkpoint_chain_matches_reference_after_cache_rebuild() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track = _seed_track(client)
        releases: list[dict[str, object]] = []
        for available_sessions in (1, 2, 3):
            releases.append(_publish_successor(client, available_sessions))
            assert runtime.daily_tracks.process_next() is True
            if available_sessions == 1:
                cache = runtime.daily_tracks._working_cache
                assert cache is not None
                cache.path(track["id"]).unlink()

        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        cache_path = cache.path(track["id"])
        cache_before = cache_path.read_bytes()
        durable_before = _durable_evidence(runtime.database, str(track["id"]))

        proof = runtime.daily_tracks.verify_persisted_equivalence(str(track["id"]))

        assert proof.status == "equivalent"
        assert proof.track_id == track["id"]
        assert proof.head_release_id == releases[-1]["id"]
        assert proof.release_sequence == (
            track["seed_release_id"],
            *(release["id"] for release in releases),
        )
        assert proof.checkpoint_count == 3
        assert len(proof.checkpoint_evidence_sha256s) == 3
        assert proof.final_evidence_sha256 == proof.checkpoint_evidence_sha256s[-1]
        assert _durable_evidence(runtime.database, str(track["id"])) == durable_before
        assert cache_path.read_bytes() == cache_before
        assert client.post(f"/api/daily-tracks/{track['id']}/verify-equivalence").status_code in {
            404,
            405,
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_equivalence_mismatch_is_read_only_and_reports_first_semantic_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        track = _seed_track(client)
        releases = [_publish_successor(client, count) for count in (1, 2)]
        assert runtime.daily_tracks.process_next() is True
        assert runtime.daily_tracks.process_next() is True
        cache = runtime.daily_tracks._working_cache
        assert cache is not None
        cache_path = cache.path(track["id"])
        cache_before = cache_path.read_bytes()
        durable_before = _durable_evidence(runtime.database, str(track["id"]))
        original_read = runtime.publication.read

        def read_with_semantic_mismatch(published_ref: object) -> VerifiedBundle:
            bundle = original_read(published_ref)
            if published_ref.manifest_sha256 != durable_before["head_manifest_sha256"]:
                return bundle
            payload = bundle.payloads["checkpoint"]
            value = json.loads(payload.content)
            retained = value["strategy_state"]["retained_delta"]
            retained[-1]["benchmark_nav"] = "semantic-mismatch"
            return VerifiedBundle(
                kind=bundle.kind,
                manifest_sha256=bundle.manifest_sha256,
                provenance=bundle.provenance,
                payloads={
                    **bundle.payloads,
                    "checkpoint": VerifiedPayload(
                        media_type=payload.media_type,
                        content=canonical_json_bytes(value),
                        serialization=payload.serialization,
                    ),
                },
            )

        def reject_publication(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("equivalence verification must not publish")

        monkeypatch.setattr(runtime.publication, "read", read_with_semantic_mismatch)
        monkeypatch.setattr(runtime.publication, "prepare", reject_publication)
        monkeypatch.setattr(runtime.publication, "record", reject_publication)
        target_id = releases[-1]["id"]

        with pytest.raises(DailyTrackEquivalenceMismatch) as failure:
            runtime.daily_tracks.verify_persisted_equivalence(str(track["id"]))

        assert str(failure.value) == (
            f"EQUIVALENCE_MISMATCH at $.checkpoints.{target_id}.state"
            ".strategy_state.retained_delta[1].benchmark_nav"
        )
        assert _durable_evidence(runtime.database, str(track["id"])) == durable_before
        assert cache_path.read_bytes() == cache_before


def _seed_track(client: TestClient) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data.update("ticket-31-seed-release")
    assert runtime.data.process_next_update() is True
    admitted = client.post(
        "/api/definitions/run",
        json={
            "request_id": "ticket-31-seed-run",
            "name": "ticket-31",
            "alpha": {
                "operator_id": "pct_change",
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
        json={"request_id": "ticket-31-track"},
    )
    assert started.status_code == 201
    return started.json()


def _publish_successor(client: TestClient, available_sessions: int) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    runtime.data._source = FixtureDataSource(sessions_after_bootstrap=available_sessions)
    response = client.post(
        "/api/data/update",
        headers={"Idempotency-Key": f"ticket-31-release-{available_sessions}"},
        json={},
    )
    assert response.status_code == 202
    assert runtime.data.process_next_update() is True
    latest = client.get("/api/data").json()["latest_release"]
    assert latest is not None
    return latest


def _durable_evidence(database: PostgresDatabase, track_id: str) -> dict[str, object]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT track.current_release_id, track.current_strategy_session,
                   track.head_manifest_sha256,
                   (SELECT count(*) FROM daily_tracks.checkpoints
                    WHERE track_id = track.id) AS checkpoint_count,
                   (SELECT count(*) FROM publication.manifests) AS publication_count
            FROM daily_tracks.tracks AS track
            WHERE track.id = %s
            """,
            (track_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


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
