from __future__ import annotations

import hashlib

import pytest
from core_runtime import drop_product_schemas
from psycopg.types.json import Jsonb

from thesistrace._postgres import MigrationPlan, PostgresDatabase, apply_migrations
from thesistrace.daily_track.migrations import MIGRATIONS as DAILY_TRACK_MIGRATIONS
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_run.migrations import MIGRATIONS as RESEARCH_RUN_MIGRATIONS

HISTORICAL_DAILY_TRACK_SHA256 = {
    "0001_active_tracks_and_origins": (
        "a2e8afbcbf45608e5fba4f81cd23700b31ef5fc3658bc697c8ccb77f4f52ef63"
    ),
    "0002_direct_successor_progression": (
        "f25391ba255eec7b99df74bf02d2182c18561664cd98e8a1dbc6291b58e744cb"
    ),
    "0003_recoverable_progression_attempts": (
        "cf72e3016fa95d60b1786bc5be6c881ba11e753d8e7f3f84dc91f532b1d2baa9"
    ),
    "0004_blocked_track_failure_isolation": (
        "dafd5f30a871cf993386b326764ed1faab38ae962d908992d26f395ef0640b5d"
    ),
    "0005_blocked_retry_receipts": (
        "dba632be34aa1313a06407a2c9000ef0ae056c851f6db23a1bdb3bcd769cae34"
    ),
    "0006_irreversible_stop": (
        "598645a3aae32fac72f2f637c7f4f36819d142fb5bedeb6ee58c9630d25db832"
    ),
}
HISTORICAL_RESEARCH_RUN_SHA256 = {
    "0001_queued_research_runs": (
        "26711f46be6081eb4d97d66e88a0cc0275d77b4dbdb9b61af1266621c1ae473e"
    ),
    "0002_execution_attempts_and_results": (
        "ea88f1682e6aed7a5da8592a058bd833ed91e9458aa40e185171abe590d149c5"
    ),
    "0003_terminal_failure_reason": (
        "df8b834f19ceee450bd9bc1c22bcc62f56639d2485e4fdb42a6cc6cabe8c21d9"
    ),
    "0004_cancel_receipts": (
        "17cbefdd86317927e9c62707a59490fd5f10dd52fb5735144890edc4db751c85"
    ),
    "0005_exact_input_reruns": (
        "24d1e7ff52367144580cb819e5533c2258f7aed3616b12d96d164b9d1a7bffdd"
    ),
    "0006_start_tracking_receipts": (
        "1ea624d941a0e27c5d4af1710f67819bea5b11fd833d8ac83203ecfb52610f16"
    ),
}


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_published_migration_history_forwards_legacy_receipts_then_drops_table() -> None:
    assert _historical_sha256(DAILY_TRACK_MIGRATIONS) == HISTORICAL_DAILY_TRACK_SHA256
    assert _historical_sha256(RESEARCH_RUN_MIGRATIONS) == HISTORICAL_RESEARCH_RUN_SHA256

    settings = CoreSettings.from_environment()
    drop_product_schemas(settings)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        apply_migrations(database, DATA_MIGRATIONS)
        apply_migrations(database, _without_last(RESEARCH_RUN_MIGRATIONS))
        apply_migrations(database, _without_last(DAILY_TRACK_MIGRATIONS))

        outcome = {
            "id": "track_ticket47_upgrade",
            "status": "active",
            "seed_run_id": "run_ticket47_upgrade",
            "seed_release_id": "release_ticket47_upgrade",
            "current_release_id": "release_ticket47_upgrade",
            "definition_id": "definition_ticket47_upgrade",
            "definition_revision": 1,
            "result_checksum_sha256": "a" * 64,
            "strategy_session": "2025-12-31",
        }
        with database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO daily_tracks.tracks (
                    id, status, seed_run_id, origin,
                    current_release_id, current_strategy_session
                ) VALUES (%s, 'active', %s, %s, %s, %s)
                """,
                (
                    outcome["id"],
                    outcome["seed_run_id"],
                    Jsonb({}),
                    outcome["current_release_id"],
                    outcome["strategy_session"],
                ),
            )
            transaction.execute(
                """
                INSERT INTO daily_tracks.activation_receipts (
                    request_id, request_fingerprint, track_id, outcome
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    "ticket-47-upgrade",
                    "b" * 64,
                    outcome["id"],
                    Jsonb(outcome),
                ),
            )

        assert apply_migrations(database, RESEARCH_RUN_MIGRATIONS) == (
            "0007_import_legacy_start_tracking_receipts",
        )
        assert apply_migrations(database, DAILY_TRACK_MIGRATIONS) == (
            "0007_drop_legacy_activation_receipts",
        )

        with database.transaction() as transaction:
            receipt = transaction.execute(
                """
                SELECT request_fingerprint, seed_run_id, track_id, outcome
                FROM research_runs.start_tracking_receipts
                WHERE request_id = 'ticket-47-upgrade'
                """
            ).fetchone()
            legacy_table = transaction.execute(
                "SELECT to_regclass('daily_tracks.activation_receipts') AS table_name"
            ).fetchone()
        assert receipt == {
            "request_fingerprint": "b" * 64,
            "seed_run_id": outcome["seed_run_id"],
            "track_id": outcome["id"],
            "outcome": outcome,
        }
        assert legacy_table == {"table_name": None}
    finally:
        database.close()


def _without_last(plan: MigrationPlan) -> MigrationPlan:
    return MigrationPlan(
        schema=plan.schema,
        ledger_table=plan.ledger_table,
        lock_name=plan.lock_name,
        migrations=plan.migrations[:-1],
    )


def _historical_sha256(plan: MigrationPlan) -> dict[str, str]:
    return {
        migration.name: hashlib.sha256(migration.statement.encode()).hexdigest()
        for migration in plan.migrations[:-1]
    }
