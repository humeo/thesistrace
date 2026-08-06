from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import MigrationError, PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import (
    CORE_MIGRATION_PLANS,
    CoreSettings,
    core_environment_is_configured,
    migrate_core,
)


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_explicit_migration_is_idempotent_and_required_before_startup() -> None:
    settings = CoreSettings.from_environment()
    _drop_product_schemas(settings.database_url)

    with pytest.raises(MigrationError, match="missing migration ledger"):
        with TestClient(create_app(settings)):
            pass

    missing_worker = subprocess.run(
        ["uv", "run", "thesistrace-worker", "--once"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert missing_worker.returncode != 0
    assert "missing migration ledger" in missing_worker.stderr

    first_applied = migrate_core(settings.database_url)
    assert first_applied == tuple(
        f"{plan.schema}.{migration.name}"
        for plan in CORE_MIGRATION_PLANS
        for migration in plan.migrations
    )
    before_startup = _migration_ledger(settings.database_url)
    assert migrate_core(settings.database_url) == ()

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/data").status_code == 200
    worker = subprocess.run(
        ["uv", "run", "thesistrace-worker", "--once"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert worker.returncode == 0, worker.stderr
    assert _migration_ledger(settings.database_url) == before_startup


def _drop_product_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for plan in reversed(CORE_MIGRATION_PLANS):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{plan.schema}" CASCADE')
    finally:
        database.close()


def _migration_ledger(database_url: str) -> tuple[tuple[str, str, object], ...]:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        rows: list[tuple[str, str, object]] = []
        with database.transaction() as transaction:
            for plan in CORE_MIGRATION_PLANS:
                for row in transaction.execute(
                    f'SELECT name, sha256, applied_at FROM "{plan.schema}".'
                    f'"{plan.ledger_table}" ORDER BY name'
                ).fetchall():
                    rows.append((plan.schema, row["name"], row["applied_at"]))
        return tuple(rows)
    finally:
        database.close()
