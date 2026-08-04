from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
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

        def edit(name: str):
            return client.put(
                f"/api/definitions/{definition_id}",
                json={"expected_revision": 1, "name": name},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(edit, ("Concurrent A", "Concurrent B")))

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
