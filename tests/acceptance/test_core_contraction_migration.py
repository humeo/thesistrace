from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb
from test_core_daily_track_activation import _drop_product_schemas

from thesistrace._postgres import MigrationPlan, PostgresDatabase, apply_migrations
from thesistrace.daily_track.migrations import MIGRATIONS as DAILY_TRACK_MIGRATIONS
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.research_run.migrations import MIGRATIONS as RESEARCH_RUN_MIGRATIONS


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_published_migration_history_forwards_legacy_receipts_then_drops_table() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings)
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
