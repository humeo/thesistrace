from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep

import pytest
from core_runtime import create_migrated_test_app as create_app
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_revision_conflicts_and_malformed_edits_never_corrupt_definition() -> None:
    settings = CoreSettings.from_environment()
    _drop_definitions_schema(settings)

    with TestClient(create_app(settings)) as client:
        created = client.post("/api/definitions", json={}).json()
        definition_id = created["id"]

        blocker = PostgresDatabase(settings.database_url)
        observer = PostgresDatabase(settings.database_url)
        blocker.open()
        observer.open()
        try:
            with (
                TestClient(create_app(settings)) as client_a,
                TestClient(create_app(settings)) as client_b,
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                start = Barrier(3)

                def edit(edit_client: TestClient, name: str):
                    start.wait(timeout=10)
                    return edit_client.put(
                        f"/api/definitions/{definition_id}",
                        json={"expected_revision": 1, "name": name},
                    )

                with blocker.transaction() as transaction:
                    transaction.execute(
                        "SELECT id FROM definitions.records WHERE id = %s FOR UPDATE",
                        (definition_id,),
                    ).fetchone()
                    futures = (
                        executor.submit(edit, client_a, "Concurrent A"),
                        executor.submit(edit, client_b, "Concurrent B"),
                    )
                    start.wait(timeout=10)
                    _wait_for_blocked_definition_locks(observer, expected=2)
                    assert all(not future.done() for future in futures)
                responses = [future.result(timeout=10) for future in futures]
        finally:
            observer.close()
            blocker.close()

        assert sorted(response.status_code for response in responses) == [200, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json() == {"detail": {"current_revision": 2}}
        authoritative = client.get(f"/api/definitions/{definition_id}").json()
        assert authoritative["revision"] == 2
        assert authoritative["name"] in {"Concurrent A", "Concurrent B"}

        malformed_edits = (
            {"expected_revision": 2, "dataset_release": "release_user_selected"},
            {"expected_revision": 2, "holdings_count": "30"},
            {"expected_revision": 2, "holdings_count": 101},
            {"expected_revision": 2, "alpha": []},
            {"expected_revision": 2, "alpha": {"operator_id": "ts_mean"}},
            {
                "expected_revision": 2,
                "alpha": {
                    "operator_id": "ts_mean",
                    "operands": [{"field_id": "price.close.adjusted"}],
                },
            },
            {
                "expected_revision": 2,
                "alpha": {
                    "operator_id": "ts_mean",
                    "operands": [
                        {"field_id": "price.close.adjusted"},
                        {"field_id": "market.volume.shares"},
                    ],
                },
            },
        )
        for command in malformed_edits:
            rejected = client.put(f"/api/definitions/{definition_id}", json=command)
            assert rejected.status_code == 422, (command, rejected.text)
            assert client.get(f"/api/definitions/{definition_id}").json() == authoritative

        alpha = {
            "operator_id": "add",
            "operands": [
                {"field_id": "price.close.adjusted"},
                {"field_id": "market.volume.shares"},
            ],
        }
        saved = client.put(
            f"/api/definitions/{definition_id}",
            json={
                "expected_revision": 2,
                "name": "Allowed edit",
                "hypothesis": "Optional and editable",
                "alpha": alpha,
                "universe": "top2000",
                "neutralization": "industry",
                "holdings_count": 40,
                "rebalance_every_sessions": 10,
            },
        )
        assert saved.status_code == 200
        assert saved.json() == {
            **authoritative,
            "revision": 3,
            "name": "Allowed edit",
            "hypothesis": "Optional and editable",
            "alpha": alpha,
            "universe": "top2000",
            "neutralization": "industry",
            "holdings_count": 40,
            "rebalance_every_sessions": 10,
        }


def _drop_definitions_schema(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS definitions CASCADE")
    finally:
        database.close()


def _wait_for_blocked_definition_locks(
    observer: PostgresDatabase,
    *,
    expected: int,
) -> None:
    deadline = monotonic() + 10
    blocked = 0
    while monotonic() < deadline:
        with observer.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT count(*) AS blocked
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND wait_event_type = 'Lock'
                  AND query LIKE '%%definitions.records%%'
                  AND query LIKE '%%FOR UPDATE%%'
                """
            ).fetchone()
        assert row is not None
        blocked = int(row["blocked"])
        if blocked >= expected:
            return
        sleep(0.05)
    raise AssertionError(
        f"expected {expected} concurrent Definition requests waiting on row locks; "
        f"observed {blocked}"
    )
