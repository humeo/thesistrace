from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.daily_track import (
    DailyTrackAccessInspector,
    DailyTrackService,
    RefreshDailyTrackCommand,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
)
from thesistrace.data import DatasetLifecycle
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core
from thesistrace.research_batch import ResearchBatchCancelCommand, ResearchBatchService
from thesistrace.researcher import ResearcherIdentity, ResearcherService

RESEARCHER_A = ResearcherIdentity(
    researcher_id=UUID("d9d17e8b-538d-4472-a7ac-56982fb36b12"),
    email="batch-alpha@example.com",
    display_label="batch-alpha",
)
RESEARCHER_B = ResearcherIdentity(
    researcher_id=UUID("3f088c70-3980-4d42-826f-7e52440b2555"),
    email="batch-beta@example.com",
    display_label="batch-beta",
)


@pytest.fixture
def ownership_database() -> PostgresDatabase:
    if not core_environment_is_configured():
        pytest.skip("the isolated Core PostgreSQL/RustFS runtime is not configured")
    database_url = CoreSettings.from_environment().database_url
    _drop_core_schemas(database_url)
    initialize_core(database_url)
    database = PostgresDatabase(database_url)
    database.open()
    try:
        researchers = ResearcherService(database)
        researchers.bootstrap(RESEARCHER_A)
        researchers.bootstrap(RESEARCHER_B)
        yield database
    finally:
        database.close()
        _drop_core_schemas(database_url)


def test_research_batch_browse_and_cursor_are_researcher_scoped(
    ownership_database: PostgresDatabase,
    tmp_path: Path,
) -> None:
    _insert_batch(
        ownership_database,
        RESEARCHER_A.researcher_id,
        "batch-alpha-new",
        "2026-08-03T00:00:00Z",
    )
    _insert_batch(
        ownership_database,
        RESEARCHER_A.researcher_id,
        "batch-alpha-old",
        "2026-08-02T00:00:00Z",
    )
    _insert_batch(
        ownership_database,
        RESEARCHER_B.researcher_id,
        "batch-beta",
        "2026-08-04T00:00:00Z",
    )
    service = ResearchBatchService(
        ownership_database,
        research_runs=cast(Any, object()),
        dataset_lifecycle=cast(Any, object()),
        publication=cast(Any, object()),
        attempt_control_directory=tmp_path,
    )

    first_page = service.list(RESEARCHER_A.researcher_id, cursor=None, limit=1)

    assert [item.id for item in first_page.items] == ["batch-alpha-new"]
    assert first_page.next_cursor is not None
    second_page = service.list(
        RESEARCHER_A.researcher_id,
        cursor=first_page.next_cursor,
        limit=1,
    )
    assert [item.id for item in second_page.items] == ["batch-alpha-old"]
    assert service.get(RESEARCHER_A.researcher_id, "batch-beta") is None
    with pytest.raises(ValueError, match="Research Batch cursor is invalid"):
        service.list(
            RESEARCHER_B.researcher_id,
            cursor=first_page.next_cursor,
            limit=1,
        )


def test_research_batch_cancel_hides_foreign_id_before_receipt_conflict(
    ownership_database: PostgresDatabase,
    tmp_path: Path,
) -> None:
    _insert_batch(
        ownership_database,
        RESEARCHER_A.researcher_id,
        "batch-alpha",
        "2026-08-03T00:00:00Z",
    )
    _insert_batch(
        ownership_database,
        RESEARCHER_B.researcher_id,
        "batch-beta",
        "2026-08-04T00:00:00Z",
    )
    with ownership_database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_batches.admission_receipts (
                researcher_id, request_id, request_fingerprint, batch_id, outcome
            ) VALUES (%s, 'colliding-request', 'admission-fingerprint',
                      'batch-alpha', '{"outcome":"accepted"}'::jsonb)
            """,
            (RESEARCHER_A.researcher_id,),
        )
    service = ResearchBatchService(
        ownership_database,
        research_runs=cast(Any, object()),
        dataset_lifecycle=cast(Any, object()),
        publication=cast(Any, object()),
        attempt_control_directory=tmp_path,
    )

    assert (
        service.cancel(
            RESEARCHER_A.researcher_id,
            "batch-beta",
            ResearchBatchCancelCommand(request_id="colliding-request"),
        )
        is None
    )


def test_daily_track_browse_mutations_and_active_count_are_researcher_scoped(
    ownership_database: PostgresDatabase, tmp_path: Path,
) -> None:
    for researcher_id, track_id, status in (
        (RESEARCHER_A.researcher_id, "track-alpha-active", "active"),
        (RESEARCHER_A.researcher_id, "track-alpha-stopping", "stopping"),
        (RESEARCHER_A.researcher_id, "track-alpha-stopped", "stopped"),
        (RESEARCHER_B.researcher_id, "track-beta-active", "active"),
    ):
        _insert_track(ownership_database, researcher_id, track_id, status)
    with ownership_database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_progressions (
                id, track_id, predecessor_checkpoint_manifest_sha256,
                target_sessions, target_start_session, target_end_session,
                planning_data_generation_id, status, provenance, finished_at
            ) VALUES (
                'progression-alpha-receipt', 'track-alpha-active',
                'checkpoint-track-alpha-active', ARRAY['2026-08-02'::date],
                '2026-08-02', '2026-08-02', 'generation',
                'cancelled', '{}'::jsonb, now()
            )
            """
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.retry_receipts (
                researcher_id, request_id, request_fingerprint,
                track_id, progression_id, outcome
            ) VALUES (
                %s, 'foreign-retry', 'own-track-fingerprint',
                'track-alpha-active', 'progression-alpha-receipt', %s
            )
            """,
            (
                RESEARCHER_A.researcher_id,
                Jsonb(_track_outcome("track-alpha-active", "active")),
            ),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.stop_receipts (
                researcher_id, request_id, request_fingerprint, track_id, outcome
            ) VALUES (
                %s, 'foreign-stop', 'own-track-fingerprint',
                'track-alpha-stopped', %s
            )
            """,
            (
                RESEARCHER_A.researcher_id,
                Jsonb(_track_outcome("track-alpha-stopped", "stopped")),
            ),
        )
    service = DailyTrackService(
        ownership_database,
        publication=cast(Any, object()),
        dataset_lifecycle=DatasetLifecycle(ownership_database, tmp_path),
    )
    inspector = DailyTrackAccessInspector(ownership_database)

    assert [item.id for item in service.list(RESEARCHER_A.researcher_id).items] == [
        "track-alpha-stopped",
        "track-alpha-stopping",
        "track-alpha-active",
    ]
    assert inspector.count_active(RESEARCHER_A.researcher_id) == 2
    assert inspector.count_active(RESEARCHER_B.researcher_id) == 1
    assert service.get(RESEARCHER_A.researcher_id, "track-beta-active") is None
    assert (
        service.refresh(
            RESEARCHER_A.researcher_id,
            "track-beta-active",
            RefreshDailyTrackCommand(request_id="foreign-refresh"),
        )
        is None
    )
    assert (
        service.retry(
            RESEARCHER_A.researcher_id,
            "track-beta-active",
            RetryDailyTrackCommand(request_id="foreign-retry"),
        )
        is None
    )
    assert (
        service.stop(
            RESEARCHER_A.researcher_id,
            "track-beta-active",
            StopDailyTrackCommand(request_id="foreign-stop"),
        )
        is None
    )
    assert service.delete(RESEARCHER_A.researcher_id, "track-beta-active") is False


def _insert_batch(
    database: PostgresDatabase,
    researcher_id: UUID,
    batch_id: str,
    created_at: str,
) -> None:
    scope = {
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "universe": "top300",
        "neutralization": "none",
        "numeric_execution_contract": "numeric-contract",
        "semantic_versions": {},
        "data_generation_id": "generation",
        "data_through_session": "2026-08-02",
    }
    with database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_batches.batches (
                researcher_id, id, batch_kind, status, scope, created_at
            ) VALUES (%s, %s, 'factor_evaluation', 'queued', %s, %s)
            """,
            (researcher_id, batch_id, Jsonb(scope), created_at),
        )
        transaction.execute(
            """
            INSERT INTO research_batches.progress (
                batch_id, completed_items, total_items, shared_alpha_factor_status
            ) VALUES (%s, 0, 1, NULL)
            """,
            (batch_id,),
        )


def _insert_track(
    database: PostgresDatabase,
    researcher_id: UUID,
    track_id: str,
    status: str,
) -> None:
    run_id = f"seed-{track_id}"
    origin = {
        "seed_run_id": run_id,
        "immutable_input": {},
        "seed_data_generation_id": "generation",
        "seed_data_through_session": "2026-08-01",
        "verified_result": {
            "kind": "research.result",
            "research_run_id": run_id,
            "schema_version": "result-v1",
            "result_manifest_sha256": "a" * 64,
            "result_checksum_sha256": "b" * 64,
        },
        "strategy_entry_session": "2026-08-01",
        "strategy_initial_cash_cny": "1",
        "initial_strategy_state": {
            "session": "2026-08-01",
            "gross_cash": "1",
            "net_cash": "1",
            "gross_nav": "1",
            "net_nav": "1",
            "cumulative_transaction_cost": "0",
            "positions": [],
            "rebalance_phase": {},
            "pending_signal": None,
            "last_daily_observation": {},
            "metric_state": {},
        },
        "calculation_contracts": {},
    }
    checkpoint_id = f"checkpoint-{track_id}"
    with database.transaction() as transaction:
        transaction.execute(
            """
            INSERT INTO research_runs.run_ownership (researcher_id, run_id)
            VALUES (%s, %s)
            """,
            (researcher_id, run_id),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.tracks (
                researcher_id, id, status, seed_run_id, origin, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                researcher_id,
                track_id,
                status,
                run_id,
                Jsonb(origin),
                {
                    "track-alpha-active": "2026-08-01T00:00:00Z",
                    "track-alpha-stopping": "2026-08-02T00:00:00Z",
                    "track-alpha-stopped": "2026-08-03T00:00:00Z",
                    "track-beta-active": "2026-08-04T00:00:00Z",
                }[track_id],
            ),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_checkpoints (
                manifest_sha256, track_id, boundary_session,
                terminal_strategy_state, data_generation_id, provenance
            ) VALUES (%s, %s, '2026-08-01', '{}'::jsonb, 'generation', '{}'::jsonb)
            """,
            (checkpoint_id, track_id),
        )
        transaction.execute(
            """
            INSERT INTO daily_tracks.session_tracking_states (
                track_id, origin_session, origin_checkpoint_manifest_sha256,
                current_checkpoint_manifest_sha256
            ) VALUES (%s, '2026-08-01', %s, %s)
            """,
            (track_id, checkpoint_id, checkpoint_id),
        )


def _track_outcome(track_id: str, status: str) -> dict[str, str]:
    return {
        "id": track_id,
        "status": status,
        "seed_run_id": f"seed-{track_id}",
        "result_checksum_sha256": "b" * 64,
        "origin_session": "2026-08-01",
        "strategy_session": "2026-08-01",
    }


def _drop_core_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()
