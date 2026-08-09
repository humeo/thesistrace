from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from core_runtime import create_migrated_test_app as create_app
from core_runtime import drop_product_schemas
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.migrations import migrate_core
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.fixture import build_minimal_canonical_fixture


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_invalid_requested_dates_save_a_draft_without_queueing_or_reading_data(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)

    with TestClient(create_app(settings)) as client:
        missing = client.post(
            "/api/definitions/run",
            json={**_valid_command("dated-missing"), "start_date": None},
        )
        head_manifest = tmp_path / "HEAD.json"
        head_manifest.write_bytes(b"not-a-valid-head")
        reversed_dates = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-reversed"),
                "start_date": "2026-08-07",
                "end_date": "2026-08-03",
            },
        )
        malformed = client.post(
            "/api/definitions/run",
            json={**_valid_command("dated-malformed"), "start_date": "2026-02-30"},
        )
        head_manifest.unlink()
        not_ready = client.post(
            "/api/definitions/run",
            json=_valid_command("dated-not-ready"),
        )
        not_ready_outcome = not_ready.json()
        head_manifest.write_bytes(b"not-a-valid-head")
        wrong_type = client.post(
            f"/api/definitions/{not_ready_outcome['definition']['id']}/run",
            json={
                "request_id": "dated-wrong-type",
                "expected_revision": 1,
                "start_date": 20260803,
            },
        )
        head_manifest.unlink()

        assert missing.status_code == 200
        assert missing.json()["issues"] == [
            {
                "code": "START_DATE_REQUIRED",
                "field": "start_date",
                "message": "Research start date is required",
            }
        ]
        assert reversed_dates.status_code == 200
        assert reversed_dates.json()["issues"] == [
            {
                "code": "RESEARCH_DATE_ORDER_INVALID",
                "field": "end_date",
                "message": "Research end date must not precede start date",
            }
        ]
        assert malformed.status_code == 422
        assert not_ready.status_code == 200
        assert not_ready_outcome["issues"] == [
            {
                "code": "DATA_NOT_READY",
                "field": "data",
                "message": "Current Dataset is not ready",
            }
        ]
        assert wrong_type.status_code == 422
        assert (
            client.get(
                f"/api/definitions/{not_ready_outcome['definition']['id']}"
            ).json()
            == not_ready_outcome["definition"]
        )
        assert _counts(settings) == {"definitions": 3, "receipts": 3, "runs": 0}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_current_calendar_admits_any_positive_inclusive_period_without_binding_head(
    tmp_path: Path,
) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    migrate_core(settings.database_url)
    sessions = (
        "2026-07-31",
        "2026-08-03",
        "2026-08-04",
        "2026-08-06",
        "2026-08-07",
    )
    first_manifest = _publish_head(settings, sessions=sessions, price_offset=0)

    with TestClient(create_app(settings)) as client:
        outside = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-outside"),
                "start_date": "2026-07-30",
                "end_date": "2026-08-07",
            },
        )
        no_session = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-no-session"),
                "start_date": "2026-08-05",
                "end_date": "2026-08-05",
            },
        )
        accepted = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-inclusive"),
                "start_date": "2026-08-01",
                "end_date": "2026-08-05",
            },
        )
        one_session = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-one-session"),
                "start_date": "2026-08-06",
                "end_date": "2026-08-06",
            },
        )

        assert outside.json()["issues"][0]["code"] == "RESEARCH_PERIOD_OUTSIDE_COVERAGE"
        assert no_session.json()["issues"][0]["code"] == "RESEARCH_PERIOD_HAS_NO_SESSIONS"
        assert accepted.status_code == 200
        outcome = accepted.json()
        assert outcome["outcome"] == "accepted"
        assert outcome["definition"]["start_date"] == "2026-08-01"
        assert outcome["definition"]["end_date"] == "2026-08-05"
        assert outcome["run"] == {
            "id": outcome["run"]["id"],
            "status": "queued",
            "definition_id": outcome["definition"]["id"],
            "definition_revision": 1,
            "start_date": "2026-08-01",
            "end_date": "2026-08-05",
        }
        assert one_session.json()["outcome"] == "accepted"

        stored = _stored_run(settings, outcome["run"]["id"])
        frozen = stored["immutable_input"]
        assert frozen["requested_start_date"] == "2026-08-01"
        assert frozen["requested_end_date"] == "2026-08-05"
        assert frozen["definition"]["content"] == {
            "name": "Dated research",
            "hypothesis": None,
            "start_date": "2026-08-01",
            "end_date": "2026-08-05",
            "alpha": {"field_id": "price.close.adjusted"},
            "universe": "top300",
            "neutralization": "none",
            "holdings_count": 1,
            "rebalance_every_sessions": 1,
        }
        serialized = str(frozen).lower()
        for forbidden in ("release", "generation", "manifest", "head", first_manifest):
            assert forbidden not in serialized
        assert _pin_count(settings) == 0

        replay = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-inclusive"),
                "start_date": "2026-08-01",
                "end_date": "2026-08-05",
            },
        )
        assert replay.json() == outcome
        conflict = client.post(
            "/api/definitions/run",
            json={
                **_valid_command("dated-inclusive"),
                "start_date": "2026-08-02",
                "end_date": "2026-08-05",
            },
        )
        assert conflict.status_code == 409

        listing = client.get("/api/research-runs").json()
        detail = client.get(f"/api/research-runs/{outcome['run']['id']}").json()
        assert detail == outcome["run"]
        assert outcome["run"] in listing["items"]
        public = f"{outcome} {listing} {detail}".lower()
        for forbidden in ("release", "generation", "manifest", "pin", "attempt"):
            assert forbidden not in public

    second_manifest = _publish_head(
        settings,
        sessions=sessions,
        price_offset=1,
        expected_manifest=first_manifest,
    )
    assert second_manifest != first_manifest
    with TestClient(create_app(settings)) as reopened:
        assert reopened.get(f"/api/research-runs/{outcome['run']['id']}").json() == outcome["run"]
    assert _pin_count(settings) == 0


def test_admission_snapshot_maps_weekend_and_holiday_boundaries() -> None:
    from thesistrace.data import DatasetAdmissionSnapshot

    snapshot = DatasetAdmissionSnapshot(
        coverage_start=date(2026, 7, 31),
        coverage_end=date(2026, 8, 7),
        research_sessions=(
            date(2026, 7, 31),
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 6),
            date(2026, 8, 7),
        ),
        available_field_ids=frozenset({"price.close.adjusted"}),
    )

    assert snapshot.research_period(date(2026, 8, 1), date(2026, 8, 5)) == (
        date(2026, 8, 3),
        date(2026, 8, 4),
    )
    assert snapshot.research_period(date(2026, 8, 5), date(2026, 8, 5)) == ()


def _valid_command(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "name": "Dated research",
        "start_date": "2026-08-03",
        "end_date": "2026-08-07",
        "alpha": {"field_id": "price.close.adjusted"},
        "universe": "top300",
        "neutralization": "none",
        "holdings_count": 1,
        "rebalance_every_sessions": 1,
    }


def _canonical(sessions: tuple[str, ...], *, price_offset: int) -> dict[str, object]:
    template = build_minimal_canonical_fixture(price_offset=price_offset)
    instrument_id = str(template["instruments"][0]["instrument_id"])
    price = template["prices"][0]
    state = template["trading_states"][0]
    limit = template["price_limits"][0]
    universe = {"instrument_ids": [instrument_id], "status": "available"}
    return {
        **template,
        "research_calendar": list(sessions),
        "prices": [{**price, "session": session} for session in sessions],
        "trading_states": [{**state, "session": session} for session in sessions],
        "price_limits": [{**limit, "session": session} for session in sessions],
        "base_pool": [
            {"session": session, "instrument_ids": [instrument_id]} for session in sessions
        ],
        "liquidity_universes": {
            name: [{"session": session, **universe} for session in sessions]
            for name in ("top300", "top1000", "top2000", "top3000")
        },
    }


def _publish_head(
    settings: CoreSettings,
    *,
    sessions: tuple[str, ...],
    price_offset: int,
    expected_manifest: str | None = None,
) -> str:
    store = MountedGenerationStore(settings.data_mount)
    generation = store.materialize(
        _canonical(sessions, price_offset=price_offset),
        prepared_at=datetime(2026, 8, 9, price_offset, tzinfo=UTC),
        source_name="dated-admission-test",
        source_lineage={"price_offset": price_offset},
    )
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        lifecycle = DatasetLifecycle(database, settings.data_mount)
        operation_id = f"dated-admission-{price_offset}"
        lifecycle.protect_candidate(
            operation_id=operation_id,
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=expected_manifest,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id=operation_id,
        )
    finally:
        database.close()
    return generation.manifest_sha256


def _stored_run(settings: CoreSettings, run_id: str) -> dict[str, object]:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT * FROM research_runs.runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        assert row is not None
        return row
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
                    (SELECT count(*) FROM definitions.records) AS definitions,
                    (SELECT count(*) FROM definitions.run_receipts) AS receipts,
                    (SELECT count(*) FROM research_runs.runs) AS runs
                """
            ).fetchone()
        assert row is not None
        return {name: int(row[name]) for name in ("definitions", "receipts", "runs")}
    finally:
        database.close()


def _pin_count(settings: CoreSettings) -> int:
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT count(*) AS count FROM data.generation_pins"
            ).fetchone()
        assert row is not None
        return int(row["count"])
    finally:
        database.close()
