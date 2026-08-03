from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.service import DataUpdateConflict
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
    open_core_runtime,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_no_change_is_terminal_idempotent_and_publishes_nothing() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    _request_and_process(settings, "ticket-12-root")
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        published_replay = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-12-root"},
        )
        assert published_replay.status_code == 202
        assert published_replay.json()["outcome"] == "published"
    _request_and_process(settings, "ticket-12-later")

    with open_core_runtime(settings) as runtime:
        latest_before = runtime.data.overview().latest_release
        assert latest_before is not None
        counts_before = _durable_counts(runtime.database)

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        accepted = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-12-no-change"},
        )
        assert accepted.status_code == 202
        assert accepted.json()["outcome"] == "accepted"
        accepted_replay = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-12-no-change"},
        )
        assert accepted_replay.status_code == 202
        assert accepted_replay.json() == accepted.json()

    with open_core_runtime(settings) as runtime:
        assert runtime.data.process_next_update()
        assert runtime.data.overview().latest_release == latest_before
        assert runtime.data.overview().latest_update_outcome == "no_change"
        counts_after = _durable_counts(runtime.database)
        assert counts_after["releases"] == counts_before["releases"]
        assert counts_after["manifests"] == counts_before["manifests"]
        assert counts_after["objects"] == counts_before["objects"]
        assert counts_after["attempts"] == counts_before["attempts"] + 1

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        replay = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "ticket-12-no-change"},
        )
        assert replay.status_code == 202
        assert replay.json() == {
            "request_id": "ticket-12-no-change",
            "outcome": "no_change",
        }

    with open_core_runtime(settings) as runtime:
        assert _durable_counts(runtime.database) == counts_after
        with runtime.database.transaction() as transaction:
            receipt = transaction.execute(
                """
                SELECT status, release_id, failure_reason
                FROM data.update_receipts
                WHERE request_id = 'ticket-12-no-change'
                """
            ).fetchone()
        assert receipt == {
            "status": "no_change",
            "release_id": None,
            "failure_reason": None,
        }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_malformed_and_conflicting_update_requests_create_no_new_work() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        for response in (
            client.post("/api/data/update"),
            client.post(
                "/api/data/update",
                headers={"Idempotency-Key": ""},
            ),
            client.post(
                "/api/data/update",
                headers={
                    "Idempotency-Key": "malformed-body",
                    "Content-Type": "application/json",
                },
                content="{",
            ),
            client.post(
                "/api/data/update",
                headers={"Idempotency-Key": "forbidden-provider-mode"},
                json={"source": "fixture"},
            ),
        ):
            assert response.status_code == 422

    with open_core_runtime(settings) as runtime:
        assert _durable_counts(runtime.database)["receipts"] == 0
        assert runtime.data.update("fingerprint-conflict").outcome == "accepted"
        with runtime.database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.update_receipts
                SET request_fingerprint = 'different-input'
                WHERE request_id = 'fingerprint-conflict'
                """
            )

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        conflict = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": "fingerprint-conflict"},
        )
        assert conflict.status_code == 409

    with open_core_runtime(settings) as runtime:
        counts = _durable_counts(runtime.database)
        assert counts["receipts"] == 1
        assert counts["attempts"] == 0


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_postgresql_admits_only_one_concurrent_data_update() -> None:
    settings = CoreSettings.from_environment()
    _reset_core_schemas(settings)
    with open_core_runtime(settings) as runtime:
        barrier = Barrier(6)

        def admit(index: int) -> str:
            barrier.wait()
            try:
                return runtime.data.update(f"ticket-12-concurrent-{index}").outcome
            except DataUpdateConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=6) as executor:
            outcomes = list(executor.map(admit, range(6)))

        assert outcomes.count("accepted") == 1
        assert outcomes.count("conflict") == 5
        with runtime.database.transaction() as transaction:
            active = transaction.execute(
                """
                SELECT count(*) AS count
                FROM data.update_receipts
                WHERE status IN ('accepted', 'running')
                """
            ).fetchone()
        assert active == {"count": 1}


def _request_and_process(settings: CoreSettings, request_id: str) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/data/update",
            headers={"Idempotency-Key": request_id},
        )
        assert response.status_code == 202
    with open_core_runtime(settings) as runtime:
        assert runtime.data.process_next_update()


def _durable_counts(database: PostgresDatabase) -> dict[str, int]:
    with database.transaction() as transaction:
        row = transaction.execute(
            """
            SELECT
              (SELECT count(*) FROM data.releases) AS releases,
              (SELECT count(*) FROM data.update_receipts) AS receipts,
              (SELECT count(*) FROM data.update_attempts) AS attempts,
              (SELECT count(*) FROM publication.manifests) AS manifests,
              (SELECT count(*) FROM publication.objects) AS objects
            """
        ).fetchone()
    assert row is not None
    return {key: int(value) for key, value in row.items()}


def _reset_core_schemas(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS data CASCADE")
            transaction.execute("DROP SCHEMA IF EXISTS publication CASCADE")
    finally:
        database.close()
