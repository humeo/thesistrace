from __future__ import annotations

from psycopg import sql

from thesistrace._postgres import (
    MigrationError,
    MigrationPlan,
    PostgresDatabase,
    PostgresTransaction,
    apply_migrations,
    verify_migrations,
)
from thesistrace.daily_track.migrations import MIGRATIONS as DAILY_TRACK_MIGRATIONS
from thesistrace.data.lifecycle import CURRENT_DATA_CUTOVER_LOCK
from thesistrace.data.migrations import MIGRATIONS as DATA_MIGRATIONS
from thesistrace.definition.migrations import MIGRATIONS as DEFINITION_MIGRATIONS
from thesistrace.publication.migrations import MIGRATIONS as PUBLICATION_MIGRATIONS
from thesistrace.research_run.migrations import MIGRATIONS as RESEARCH_RUN_MIGRATIONS

CORE_MIGRATION_PLANS: tuple[MigrationPlan, ...] = (
    PUBLICATION_MIGRATIONS,
    DATA_MIGRATIONS,
    DEFINITION_MIGRATIONS,
    RESEARCH_RUN_MIGRATIONS,
    DAILY_TRACK_MIGRATIONS,
)

LEGACY_DATASET_RELEASE_DIAGNOSTIC = (
    "UNSUPPORTED_LEGACY_DATASET_RELEASE_STATE: run the private development-reset "
    "command or perform a separately managed migration before current-data cutover"
)
_CONTRACTION_MIGRATIONS = {
    "data": "0009_contract_permanent_dataset_release_path",
    "daily_tracks": "0010_contract_release_coordinate_storage",
}


def migrate_core(database_url: str) -> tuple[str, ...]:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.session_advisory_lock(CURRENT_DATA_CUTOVER_LOCK):
            guard_legacy_dataset_release_state(database)
            return tuple(
                f"{plan.schema}.{migration}"
                for plan in CORE_MIGRATION_PLANS
                for migration in apply_migrations(database, plan)
            )
    finally:
        database.close()


def verify_core_migrations(database: PostgresDatabase) -> None:
    guard_legacy_dataset_release_state(database)
    for plan in CORE_MIGRATION_PLANS:
        verify_migrations(database, plan)


def verify_development_reset_migrations(database: PostgresDatabase) -> None:
    """Verify the reset seam without requiring the destructive contractions."""
    for plan in CORE_MIGRATION_PLANS:
        verify_migrations(database, _before_contraction(plan))


def guard_legacy_dataset_release_state(database: PostgresDatabase) -> None:
    with database.transaction() as transaction:
        if any(
            _table_has_rows(transaction, table)
            for table in (
                "data.releases",
                "data.update_receipts",
                "data.update_attempts",
                "data.release_fields",
                "data.fields",
                "daily_tracks.progressions",
                "daily_tracks.checkpoints",
                "daily_tracks.progression_attempts",
            )
        ):
            raise MigrationError(LEGACY_DATASET_RELEASE_DIAGNOSTIC)
        if _column_has_value(transaction, "data", "state", "latest_release_id"):
            raise MigrationError(LEGACY_DATASET_RELEASE_DIAGNOSTIC)
        if any(
            _column_has_value(transaction, "daily_tracks", "tracks", column)
            for column in (
                "current_release_id",
                "current_strategy_session",
                "head_manifest_sha256",
                "blocked_target_release_id",
            )
        ):
            raise MigrationError(LEGACY_DATASET_RELEASE_DIAGNOSTIC)
        if _column_has_value(
            transaction,
            "daily_tracks",
            "retry_receipts",
            "target_release_id",
        ):
            raise MigrationError(LEGACY_DATASET_RELEASE_DIAGNOSTIC)
        if _table_has_rows(transaction, "daily_tracks.tracks") and _track_without_session_state(
            transaction
        ):
            raise MigrationError(LEGACY_DATASET_RELEASE_DIAGNOSTIC)
        if _publication_has_dataset_release(transaction):
            raise MigrationError(LEGACY_DATASET_RELEASE_DIAGNOSTIC)


def _before_contraction(plan: MigrationPlan) -> MigrationPlan:
    contraction = _CONTRACTION_MIGRATIONS.get(plan.schema)
    if contraction is None:
        return plan
    migrations = tuple(migration for migration in plan.migrations if migration.name != contraction)
    return MigrationPlan(
        schema=plan.schema,
        ledger_table=plan.ledger_table,
        lock_name=plan.lock_name,
        migrations=migrations,
    )


def _table_has_rows(transaction: PostgresTransaction, table: str) -> bool:
    relation = transaction.execute("SELECT to_regclass(%s) AS value", (table,)).fetchone()
    if relation is None or relation["value"] is None:
        return False
    schema, name = table.split(".", maxsplit=1)
    row = transaction.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        ) AS present
        """,
        (schema, name),
    ).fetchone()
    if row is None or not row["present"]:
        return False
    # Identifiers come only from the fixed module-owned table list above.
    found = transaction.execute(
        sql.SQL("SELECT EXISTS (SELECT 1 FROM {}.{}) AS value").format(
            sql.Identifier(schema),
            sql.Identifier(name),
        )
    ).fetchone()
    return bool(found and found["value"])


def _column_has_value(
    transaction: PostgresTransaction,
    schema: str,
    table: str,
    column: str,
) -> bool:
    present = transaction.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
        ) AS value
        """,
        (schema, table, column),
    ).fetchone()
    if present is None or not present["value"]:
        return False
    found = transaction.execute(
        sql.SQL(
            "SELECT EXISTS (SELECT 1 FROM {}.{} WHERE {} IS NOT NULL) AS value"
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.Identifier(column),
        )
    ).fetchone()
    return bool(found and found["value"])


def _track_without_session_state(transaction: PostgresTransaction) -> bool:
    if not _table_has_rows(transaction, "daily_tracks.tracks"):
        return False
    state = transaction.execute(
        "SELECT to_regclass('daily_tracks.session_tracking_states') AS value"
    ).fetchone()
    if state is None or state["value"] is None:
        return True
    row = transaction.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM daily_tracks.tracks AS track
            WHERE NOT EXISTS (
                SELECT 1 FROM daily_tracks.session_tracking_states AS state
                WHERE state.track_id = track.id
            )
        ) AS value
        """
    ).fetchone()
    return bool(row and row["value"])


def _publication_has_dataset_release(transaction: PostgresTransaction) -> bool:
    relation = transaction.execute(
        "SELECT to_regclass('publication.manifests') AS value"
    ).fetchone()
    if relation is None or relation["value"] is None:
        return False
    row = transaction.execute(
        "SELECT EXISTS (SELECT 1 FROM publication.manifests WHERE kind = 'data.release') AS value"
    ).fetchone()
    return bool(row and row["value"])
