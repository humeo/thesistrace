from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import MigrationError, PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.migrations import CORE_MIGRATION_PLANS
from thesistrace.entrypoints.runtime import (
    CoreSettings,
    core_environment_is_configured,
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
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert missing_worker.returncode != 0
    assert "missing migration ledger" in missing_worker.stderr

    first_migration = _run_migration_command()
    assert first_migration.returncode == 0, first_migration.stderr
    before_startup = _migration_ledger(settings.database_url)
    repeated_migration = _run_migration_command()
    assert repeated_migration.returncode == 0, repeated_migration.stderr
    assert _migration_ledger(settings.database_url) == before_startup

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/data").status_code == 200
    worker = subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert worker.returncode == 0, worker.stderr
    assert _migration_ledger(settings.database_url) == before_startup


def _run_migration_command() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "thesistrace.entrypoints.migrate"],
        capture_output=True,
        check=False,
        text=True,
    )


def _drop_product_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for plan in reversed(CORE_MIGRATION_PLANS):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{plan.schema}" CASCADE')
    finally:
        database.close()


def _migration_ledger(database_url: str) -> tuple[tuple[str, str, str, object], ...]:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        rows: list[tuple[str, str, str, object]] = []
        with database.transaction() as transaction:
            for plan in CORE_MIGRATION_PLANS:
                for row in transaction.execute(
                    f'SELECT name, sha256, applied_at FROM "{plan.schema}".'
                    f'"{plan.ledger_table}" ORDER BY name'
                ).fetchall():
                    rows.append(
                        (plan.schema, row["name"], row["sha256"], row["applied_at"])
                    )
        return tuple(rows)
    finally:
        database.close()
