from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from core_runtime import create_initialized_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import (
    DataGarbageCollector,
    DatasetLifecycle,
    MountedGenerationStore,
)
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture

SESSIONS = (
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-10",
    "2026-08-11",
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_batch_admission_rejects_all_invalid_computation_before_product_state(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        structurally_invalid = (
            ({**_factor_command("batch-empty"), "factors": []}, None),
            ({
                **_factor_command("batch-too-large"),
                "factors": [
                    {
                        "item_key": f"factor-{ordinal}",
                        "formula": f"close + {ordinal}",
                    }
                    for ordinal in range(21)
                ],
            }, "factor-20"),
            ({
                **_strategy_command("batch-mixed"),
                "factors": [{"item_key": "mixed", "formula": "close"}],
            }, None),
            ({
                **_strategy_command("batch-invalid-strategy"),
                "strategies": [
                    {
                        "item_key": "invalid",
                        "holdings_count": 0,
                        "rebalance_every_sessions": 1,
                    }
                ],
            }, "invalid"),
            ({
                **_factor_command("batch-invalid-key"),
                "factors": [{"item_key": "   ", "formula": "close"}],
            }, None),
        )
        for command, expected_item_key in structurally_invalid:
            response = client.post("/api/research-batches", json=command)
            assert response.status_code == 422
            assert set(response.json()) == {"issues"}
            assert response.json()["issues"]
            assert {
                issue["code"] for issue in response.json()["issues"]
            } == {"INVALID_BATCH_INPUT"}
            if expected_item_key is not None:
                assert any(
                    issue["item_key"] == expected_item_key
                    for issue in response.json()["issues"]
                )
            assert _counts(settings) == _empty_counts()

        duplicate_key = client.post(
            "/api/research-batches",
            json={
                **_factor_command("batch-duplicate-key"),
                "factors": [
                    {"item_key": "same", "formula": "close"},
                    {"item_key": " same ", "formula": "open"},
                ],
            },
        )
        assert duplicate_key.status_code == 422
        assert duplicate_key.json()["issues"][0]["code"] == "DUPLICATE_ITEM_KEY"
        assert _counts(settings) == _empty_counts()

        invalid = client.post(
            "/api/research-batches",
            json={
                **_factor_command("batch-invalid"),
                "factors": [
                    {"item_key": "valid", "formula": "close"},
                    {"item_key": "invalid", "formula": "unknown_field +"},
                ],
            },
        )
        assert invalid.status_code == 422
        issue = invalid.json()["issues"][0]
        assert issue["item_key"] == "invalid"
        assert issue["field"] == "factors[1].formula"
        assert issue["range"] is not None
        assert _counts(settings) == _empty_counts()

        duplicate_factor = client.post(
            "/api/research-batches",
            json={
                **_factor_command("batch-duplicate-factor"),
                "factors": [
                    {"item_key": "first", "formula": "rank(close)"},
                    {"item_key": "second", "formula": "rank( close )"},
                ],
            },
        )
        assert duplicate_factor.status_code == 422
        assert duplicate_factor.json()["issues"] == [
            {
                "code": "DUPLICATE_FACTOR_EXPRESSION",
                "field": "factors",
                "message": (
                    "Canonical Factor Expression duplicates item_key first and second"
                ),
                "item_key": "second",
                "severity": "error",
                "range": None,
                "details": None,
            }
        ]
        assert _counts(settings) == _empty_counts()

        duplicate_strategy = client.post(
            "/api/research-batches",
            json={
                **_strategy_command("batch-duplicate-strategy"),
                "strategies": [
                    {
                        "item_key": "first",
                        "holdings_count": 1,
                        "rebalance_every_sessions": 1,
                    },
                    {
                        "item_key": "second",
                        "holdings_count": 1,
                        "rebalance_every_sessions": 1,
                    },
                ],
            },
        )
        assert duplicate_strategy.status_code == 422
        assert "first and second" in duplicate_strategy.json()["issues"][0]["message"]
        assert _counts(settings) == _empty_counts()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_strategy_sweep_capacity_rejection_creates_no_product_state(
    tmp_path: Path,
) -> None:
    settings = replace(
        CoreSettings.from_environment(),
        data_mount=tmp_path,
        research_execution_memory_bytes=67_112_600,
    )
    drop_product_schemas(settings)
    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        command = _strategy_command("batch-strategy-capacity")
        response = client.post(
            "/api/research-batches",
            json={**command, "strategies": [command["strategies"][0]]},
        )

        assert response.status_code == 422
        assert response.json()["issues"][0]["code"] == (
            "RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY"
        )
        assert _counts(settings) == _empty_counts()


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_factor_and_strategy_batch_admission_is_atomic_idempotent_and_queryable(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    factor_command = _factor_command("batch-factor-success")
    strategy_command = _strategy_command("batch-strategy-success")

    with TestClient(create_app(settings)) as client:
        _publish_current_data(settings)
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(
                executor.map(
                    lambda _index: client.post(
                        "/api/research-batches",
                        json=factor_command,
                    ),
                    range(8),
                )
            )
        assert {response.status_code for response in responses} == {202}
        assert len({response.json()["id"] for response in responses}) == 1
        factor = responses[0].json()
        assert factor["batch_kind"] == "factor_evaluation"
        assert factor["status"] == "queued"
        assert factor["progress"] == {"completed_items": 0, "total_items": 2}
        assert [(item["ordinal"], item["item_key"]) for item in factor["items"]] == [
            (1, "value"),
            (2, "rank"),
        ]
        assert len({item["research_run_id"] for item in factor["items"]}) == 2
        assert {item["dependency_role"] for item in factor["items"]} == {"factor"}
        assert client.app.state.core_runtime.research_runs.process_next() is False
        child_cancel = client.post(
            f"/api/research-runs/{factor['items'][0]['research_run_id']}/cancel",
            json={"request_id": "batch-child-cancel"},
        )
        assert child_cancel.status_code == 409
        assert client.get(f"/api/research-batches/{factor['id']}").json() == factor

        conflict = client.post(
            "/api/research-batches",
            json={**factor_command, "universe": "top1000"},
        )
        assert conflict.status_code == 409

        strategy_response = client.post("/api/research-batches", json=strategy_command)
        assert strategy_response.status_code == 202
        strategy = strategy_response.json()
        assert strategy["batch_kind"] == "strategy_sweep"
        assert [item["item_key"] for item in strategy["items"]] == ["focused", "broad"]
        assert {item["dependency_role"] for item in strategy["items"]} == {"strategy"}
        assert strategy["scope"] == factor["scope"]

        first_page = client.get("/api/research-batches", params={"limit": 1})
        assert first_page.status_code == 200
        assert [item["id"] for item in first_page.json()["items"]] == [strategy["id"]]
        second_page = client.get(
            "/api/research-batches",
            params={"limit": 1, "cursor": first_page.json()["next_cursor"]},
        )
        assert [item["id"] for item in second_page.json()["items"]] == [factor["id"]]
        assert client.get(f"/api/research-batches/{factor['id']}").json() == factor
        assert client.get("/api/research-batches/batch_missing").status_code == 404
        assert client.get("/api/research-batches", params={"cursor": "bad"}).status_code == 422
        assert client.delete(f"/api/research-batches/{factor['id']}").status_code == 405

        folders = client.get("/api/research-folders").json()["items"]
        assert any(
            folder["id"] == "folder_batch_research"
            and folder["name"] == "Batch Research"
            for folder in folders
        )
        protected = client.delete("/api/research-folders/folder_batch_research")
        assert protected.status_code == 409

    frozen_generation = str(factor["scope"]["data_generation_id"])
    _expire_batch_retention_leases(settings)
    replacement_generation = _publish_current_data(
        settings,
        operation_id="research-batch-replacement-head",
        expected_generation=frozen_generation,
        prepared_at=datetime(2026, 8, 11, 13, tzinfo=UTC),
    )
    assert replacement_generation != frozen_generation
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        collection = DataGarbageCollector(database, settings.data_mount).collect(
            idempotency_key="research-batch-expired-retention"
        )
    finally:
        database.close()
    assert collection.status == "succeeded"
    assert (
        MountedGenerationStore(settings.data_mount)
        .validate_generation(frozen_generation)
        .manifest_sha256
        == frozen_generation
    )

    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/research-batches/{factor['id']}").json() == factor
        assert restarted.get(f"/api/research-batches/{strategy['id']}").json() == strategy

    counts = _counts(settings)
    assert counts == {
        "batches": 2,
        "items": 4,
        "batch_receipts": 2,
        "runs": 4,
        "ordinary_receipts": 0,
        "cancel_receipts": 0,
        "batch_owned_runs": 4,
        "batch_retentions": 2,
        "publication_manifests": 0,
    }


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_injected_second_item_failure_rolls_back_complete_batch_admission(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    with TestClient(create_app(settings)):
        _publish_current_data(settings)
        _install_second_item_failure(settings)
        with TestClient(create_app(settings), raise_server_exceptions=False) as failing:
            response = failing.post(
                "/api/research-batches",
                json=_factor_command("batch-transaction-failure"),
            )
        assert response.status_code == 500
        assert _counts(settings) == _empty_counts()


def _factor_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "batch_kind": "factor_evaluation",
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "universe": "top300",
        "neutralization": "none",
        "factors": [
            {"item_key": "value", "name": "Value", "formula": "close"},
            {"item_key": "rank", "name": "Rank", "formula": "rank(close)"},
        ],
    }


def _strategy_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "batch_kind": "strategy_sweep",
        "start_date": "2026-08-03",
        "end_date": "2026-08-04",
        "universe": "top300",
        "neutralization": "none",
        "alpha": {"formula": "close", "hypothesis": "shared"},
        "strategies": [
            {
                "item_key": "focused",
                "name": "Focused",
                "holdings_count": 1,
                "rebalance_every_sessions": 1,
            },
            {
                "item_key": "broad",
                "name": "Broad",
                "holdings_count": 2,
                "rebalance_every_sessions": 2,
            },
        ],
    }


def _publish_current_data(
    settings: CoreSettings,
    *,
    operation_id: str = "research-batch-admission-head",
    expected_generation: str | None = None,
    prepared_at: datetime = datetime(2026, 8, 11, 12, tzinfo=UTC),
    sessions: tuple[str, ...] = SESSIONS,
    instrument_count: int = 1,
) -> str:
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )
    try:
        try:
            s3.create_bucket(Bucket=settings.s3_bucket)
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass
    finally:
        s3.close()
    template = build_minimal_canonical_fixture()
    instrument_template = template["instruments"][0]
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    industry = template["industry_membership"][0]
    instruments = [
        {
            **instrument_template,
            "instrument_id": f"equity:{ordinal:06d}.SZ",
            "ts_code": f"{ordinal:06d}.SZ",
        }
        for ordinal in range(1, instrument_count + 1)
    ]
    instrument_ids = [str(value["instrument_id"]) for value in instruments]
    canonical = {
        **template,
        "instruments": instruments,
        "research_calendar": list(sessions),
        "prices": [
            {**price, "session": session, "instrument_id": instrument_id}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "trading_states": [
            {**state, "session": session, "instrument_id": instrument_id}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "price_limits": [
            {**limit, "session": session, "instrument_id": instrument_id}
            for session in sessions
            for instrument_id in instrument_ids
        ],
        "industry_membership": [
            {**industry, "instrument_id": instrument_id}
            for instrument_id in instrument_ids
        ],
        "base_pool": [
            {"session": session, "instrument_ids": instrument_ids} for session in sessions
        ],
        "liquidity_universes": {
            name: [
                {
                    "session": session,
                    "instrument_ids": instrument_ids[:maximum_size],
                    "status": "available",
                }
                for session in sessions
            ]
            for name, maximum_size in (
                ("top300", 300),
                ("top1000", 1_000),
                ("top2000", 2_000),
                ("top3000", 3_000),
            )
        },
    }
    generation = MountedGenerationStore(settings.data_mount).materialize(
        canonical,
        prepared_at=prepared_at,
        source_name="research-batch-admission-test",
        source_lineage={
            "contract": "research-batch-admission",
            "operation_id": operation_id,
        },
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_generation,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _expire_batch_retention_leases(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            updated = transaction.execute(
                """
                UPDATE data.generation_candidates
                SET lease_expires_at = now() - interval '1 day'
                WHERE operation_id LIKE 'research-batch:%' AND status = 'live'
                """
            )
        assert updated.rowcount == 2
    finally:
        database.close()


def _counts(settings: CoreSettings) -> dict[str, int]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM research_batches.batches) AS batches,
                    (SELECT count(*) FROM research_batches.items) AS items,
                    (SELECT count(*) FROM research_batches.admission_receipts)
                        AS batch_receipts,
                    (SELECT count(*) FROM research_runs.runs) AS runs,
                    (SELECT count(*) FROM research_runs.admission_requests)
                        AS ordinary_receipts,
                    (SELECT count(*) FROM research_runs.cancel_receipts)
                        AS cancel_receipts,
                    (SELECT count(*) FROM research_runs.runs
                     WHERE execution_owner = 'research_batch') AS batch_owned_runs,
                    (SELECT count(*) FROM data.generation_candidates
                     WHERE operation_id LIKE 'research-batch:%' AND status = 'live')
                        AS batch_retentions,
                    (SELECT count(*) FROM publication.manifests)
                        AS publication_manifests
                """
            ).fetchone()
        assert row is not None
        return {name: int(value) for name, value in row.items()}
    finally:
        database.close()


def _empty_counts() -> dict[str, int]:
    return {
        "batches": 0,
        "items": 0,
        "batch_receipts": 0,
        "runs": 0,
        "ordinary_receipts": 0,
        "cancel_receipts": 0,
        "batch_owned_runs": 0,
        "batch_retentions": 0,
        "publication_manifests": 0,
    }


def _install_second_item_failure(settings: CoreSettings) -> None:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute(
                """
                CREATE FUNCTION research_batches.reject_second_item()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.ordinal = 2 THEN
                        RAISE EXCEPTION 'injected second Batch Item failure';
                    END IF;
                    RETURN NEW;
                END
                $$;
                CREATE TRIGGER reject_second_item
                BEFORE INSERT ON research_batches.items
                FOR EACH ROW EXECUTE FUNCTION research_batches.reject_second_item();
                """
            )
    finally:
        database.close()
