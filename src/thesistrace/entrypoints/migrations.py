from __future__ import annotations

from thesistrace._postgres import (
    MigrationPlan,
    PostgresDatabase,
    apply_migrations,
    verify_migrations,
)
from thesistrace.daily_track.migrations import MIGRATIONS as DAILY_TRACK_MIGRATIONS
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


def migrate_core(database_url: str) -> tuple[str, ...]:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        return tuple(
            f"{plan.schema}.{migration}"
            for plan in CORE_MIGRATION_PLANS
            for migration in apply_migrations(database, plan)
        )
    finally:
        database.close()


def verify_core_migrations(database: PostgresDatabase) -> None:
    for plan in CORE_MIGRATION_PLANS:
        verify_migrations(database, plan)
