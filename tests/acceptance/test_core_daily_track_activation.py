from __future__ import annotations

import copy
import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.publication import (
    PublicationUnavailableError,
    PublishedRef,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_run.result import read_result_bundle, result_publication_payloads


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_start_tracking_copies_one_complete_origin_and_reopens_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.core_runtime
        original = _admit_and_execute(client, request_id="ticket-26-seed")
        stored_seed = _stored_seed(settings, original["id"])
        published = runtime.publication.read(
            PublishedRef(
                manifest_sha256=stored_seed["result_manifest_sha256"],
                kind="research.result",
                provenance=stored_seed["result_provenance"],
            )
        )
        stored_result = read_result_bundle(published)
        result_checksum = hashlib.sha256(canonical_json_bytes(stored_result)).hexdigest()

        command = {"request_id": "ticket-26-start"}
        started = client.post(
            f"/api/research-runs/{original['id']}/daily-tracks",
            json=command,
        )

        assert started.status_code == 201
        track = started.json()
        assert track == {
            "id": track["id"],
            "status": "active",
            "seed_run_id": original["id"],
            "seed_release_id": original["dataset_release_id"],
            "current_release_id": original["dataset_release_id"],
            "definition_id": original["definition_id"],
            "definition_revision": original["definition_revision"],
            "result_checksum_sha256": result_checksum,
            "strategy_session": stored_result["terminal_strategy_state"]["session"],
        }
        origin = _stored_origin(settings, track["id"])
        assert origin == {
            "seed_run_id": original["id"],
            "definition_id": original["definition_id"],
            "definition_revision": original["definition_revision"],
            "immutable_input": stored_seed["immutable_input"],
            "seed_release_id": original["dataset_release_id"],
            "verified_result": {
                "kind": "research.result",
                "research_run_id": original["id"],
                "schema_version": stored_seed["result_provenance"]["schema_version"],
                "result_manifest_sha256": stored_seed["result_manifest_sha256"],
                "result_checksum_sha256": track["result_checksum_sha256"],
            },
            "initial_strategy_state": stored_result["terminal_strategy_state"],
            "calculation_contracts": stored_seed["result_provenance"]["calculation_contracts"],
        }
        assert _counts(settings) == {"tracks": 1, "receipts": 1}

        replay = client.post(
            f"/api/research-runs/{original['id']}/daily-tracks",
            json=command,
        )
        assert replay.status_code == 201
        assert replay.json() == track
        same_seed_new_request = client.post(
            f"/api/research-runs/{original['id']}/daily-tracks",
            json={"request_id": "ticket-26-same-seed"},
        )
        assert same_seed_new_request.status_code == 201
        assert same_seed_new_request.json() == track
        assert _counts(settings) == {"tracks": 1, "receipts": 2}

        read_barrier = Barrier(4)
        original_read = runtime.publication.read_in_transaction

        def synchronized_read(*args: object, **kwargs: object) -> object:
            read_barrier.wait(timeout=10)
            return original_read(*args, **kwargs)

        monkeypatch.setattr(runtime.publication, "read_in_transaction", synchronized_read)
        with ThreadPoolExecutor(max_workers=4) as executor:
            concurrent = [
                executor.submit(
                    client.post,
                    f"/api/research-runs/{original['id']}/daily-tracks",
                    json={"request_id": f"ticket-26-concurrent-{index}"},
                )
                for index in range(4)
            ]
            concurrent_responses = [future.result(timeout=20) for future in concurrent]
        monkeypatch.setattr(runtime.publication, "read_in_transaction", original_read)
        assert [response.status_code for response in concurrent_responses] == [201] * 4
        assert [response.json() for response in concurrent_responses] == [track] * 4
        assert _counts(settings) == {"tracks": 1, "receipts": 6}

        other = _admit_and_execute(client, request_id="ticket-26-other")
        conflict = client.post(
            f"/api/research-runs/{other['id']}/daily-tracks",
            json=command,
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "Start Tracking request_id conflicts"

        def publication_unavailable(*_args: object, **_kwargs: object) -> object:
            raise PublicationUnavailableError("temporary object read failure")

        monkeypatch.setattr(
            runtime.publication,
            "read_in_transaction",
            publication_unavailable,
        )
        unavailable = client.post(
            f"/api/research-runs/{other['id']}/daily-tracks",
            json={"request_id": "ticket-26-temporary"},
        )
        monkeypatch.setattr(runtime.publication, "read_in_transaction", original_read)
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "Start Tracking is temporarily unavailable"
        assert _counts(settings) == {"tracks": 1, "receipts": 6}

        before_malformed = _counts(settings)
        for body in ({}, {"request_id": "malformed", "extra": True}):
            response = client.post(
                f"/api/research-runs/{original['id']}/daily-tracks",
                json=body,
            )
            assert response.status_code == 422
        assert _counts(settings) == before_malformed

        queued = _admit(client, request_id="ticket-26-queued")
        for seed_status in ("queued", "running", "failed", "cancelled"):
            _set_run_status(settings, queued["id"], seed_status)
            rejected = client.post(
                f"/api/research-runs/{queued['id']}/daily-tracks",
                json={"request_id": f"ticket-26-{seed_status}"},
            )
            assert rejected.status_code == 409
        missing = client.post(
            "/api/research-runs/run_00000000/daily-tracks",
            json={"request_id": "ticket-26-missing"},
        )
        assert missing.status_code == 404

        _clone_invalid_seed(
            settings,
            original["id"],
            "run_incomplete",
            manifest=None,
            provenance={
                **stored_seed["result_provenance"],
                "research_run_id": "run_incomplete",
            },
        )
        incomplete = client.post(
            "/api/research-runs/run_incomplete/daily-tracks",
            json={"request_id": "ticket-26-incomplete"},
        )
        assert incomplete.status_code == 409
        _clone_invalid_seed(
            settings,
            original["id"],
            "run_unreadable",
            manifest="0" * 64,
            provenance={
                **stored_seed["result_provenance"],
                "research_run_id": "run_unreadable",
            },
        )
        unreadable = client.post(
            "/api/research-runs/run_unreadable/daily-tracks",
            json={"request_id": "ticket-26-unreadable"},
        )
        assert unreadable.status_code == 409

        incomplete_result = copy.deepcopy(stored_result)
        incomplete_result["terminal_strategy_state"].pop("metric_state")
        incomplete_provenance = {
            **stored_seed["result_provenance"],
            "research_run_id": "run_incomplete_result",
        }
        prepared = runtime.publication.prepare(
            kind="research.result",
            payloads=result_publication_payloads(incomplete_result),
            provenance=incomplete_provenance,
        )
        with runtime.database.transaction() as transaction:
            incomplete_ref = runtime.publication.record(transaction, prepared)
        _clone_invalid_seed(
            settings,
            original["id"],
            "run_incomplete_result",
            manifest=incomplete_ref.manifest_sha256,
            provenance=incomplete_provenance,
        )
        incomplete_bundle = client.post(
            "/api/research-runs/run_incomplete_result/daily-tracks",
            json={"request_id": "ticket-26-incomplete-result"},
        )
        assert incomplete_bundle.status_code == 409

        assert client.get("/api/daily-tracks").json() == {
            "items": [track],
            "next_cursor": None,
        }
        detail = client.get(f"/api/daily-tracks/{track['id']}").json()
        assert detail["id"] == track["id"]
        assert detail["head_release_id"] == track["current_release_id"]
        assert detail["lag_releases"] == 0
        assert detail["origin"] == {
            "seed_run_id": track["seed_run_id"],
            "seed_release_id": track["seed_release_id"],
            "definition_id": track["definition_id"],
            "definition_revision": track["definition_revision"],
            "result_checksum_sha256": track["result_checksum_sha256"],
            "strategy_session": track["strategy_session"],
        }
        assert len(detail["strategy"]["observations"]) == 504
        assert client.post("/api/daily-tracks", json={}).status_code in {404, 405}
        assert client.delete(f"/api/daily-tracks/{track['id']}").status_code in {404, 405}

        _delete_seed_definition_and_run(settings, original)

        replay_after_delete = client.post(
            f"/api/research-runs/{original['id']}/daily-tracks",
            json=command,
        )
        assert replay_after_delete.status_code == 201
        assert replay_after_delete.json() == track
        conflict_before_missing_validation = client.post(
            "/api/research-runs/run_00000000/daily-tracks",
            json=command,
        )
        assert conflict_before_missing_validation.status_code == 409
        assert (
            conflict_before_missing_validation.json()["detail"]
            == "Start Tracking request_id conflicts"
        )

    _restart_worker_once(settings)

    with TestClient(create_app(settings)) as restarted:
        reopened = restarted.get(f"/api/daily-tracks/{track['id']}")
        assert reopened.status_code == 200
        assert reopened.json() == detail
        assert restarted.get("/api/daily-tracks").json()["items"] == [track]


def _admit_and_execute(client: TestClient, *, request_id: str) -> dict[str, object]:
    run = _admit(client, request_id=request_id)
    runtime = client.app.state.core_runtime
    assert runtime.research_runs.process_next() is True
    completed = client.get(f"/api/research-runs/{run['id']}").json()
    assert completed["status"] == "succeeded"
    return completed


def _admit(client: TestClient, *, request_id: str) -> dict[str, object]:
    runtime = client.app.state.core_runtime
    if client.get("/api/data").json()["latest_release"] is None:
        runtime.data.update(f"{request_id}-release")
        assert runtime.data.process_next_update() is True
    response = client.post(
        "/api/definitions/run",
        json={
            "request_id": request_id,
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
    assert response.status_code == 200
    return response.json()["run"]


def _stored_seed(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT immutable_input, result_manifest_sha256, result_provenance
                FROM research_runs.runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
            assert row is not None
            return dict(row)
    finally:
        database.close()


def _stored_origin(settings: CoreSettings, track_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT origin FROM daily_tracks.tracks WHERE id = %s",
                (track_id,),
            ).fetchone()
            assert row is not None
            return row["origin"]
    finally:
        database.close()


def _counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            tracks = transaction.execute(
                "SELECT count(*) AS count FROM daily_tracks.tracks"
            ).fetchone()
            receipts = transaction.execute(
                "SELECT count(*) AS count FROM research_runs.start_tracking_receipts"
            ).fetchone()
            assert tracks is not None and receipts is not None
            return {
                "tracks": int(tracks["count"]),
                "receipts": int(receipts["count"]),
            }
    finally:
        database.close()


def _set_run_status(settings: CoreSettings, run_id: str, status: str) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                "UPDATE research_runs.runs SET status = %s WHERE id = %s",
                (status, run_id),
            )
    finally:
        database.close()


def _clone_invalid_seed(
    settings: CoreSettings,
    source_id: str,
    clone_id: str,
    *,
    manifest: str | None,
    provenance: dict[str, object],
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO research_runs.runs (
                    id, definition_id, definition_revision, dataset_release_id,
                    status, immutable_input, result_manifest_sha256,
                    result_provenance
                )
                SELECT %s, definition_id, definition_revision,
                       dataset_release_id, 'succeeded', immutable_input,
                       %s, %s
                FROM research_runs.runs
                WHERE id = %s
                """,
                (clone_id, manifest, Jsonb(provenance), source_id),
            )
    finally:
        database.close()


def _delete_seed_definition_and_run(
    settings: CoreSettings,
    run: dict[str, object],
) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                "DELETE FROM research_runs.attempts WHERE run_id = %s",
                (run["id"],),
            )
            transaction.execute(
                "DELETE FROM research_runs.runs WHERE id = %s",
                (run["id"],),
            )
            transaction.execute(
                "DELETE FROM definitions.run_receipts WHERE definition_id = %s",
                (run["definition_id"],),
            )
            transaction.execute(
                "DELETE FROM definitions.records WHERE id = %s",
                (run["definition_id"],),
            )
    finally:
        database.close()


def _restart_worker_once(settings: CoreSettings) -> None:
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
    }
    completed = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


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
