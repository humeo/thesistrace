from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase, SchemaError
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import CORE_SCHEMAS, initialize_core


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_explicit_schema_initialization_is_idempotent_and_required_before_startup() -> None:
    settings = CoreSettings.from_environment()
    _drop_core_schemas(settings.database_url)

    with pytest.raises(SchemaError, match="unsupported existing Core schema"):
        with TestClient(create_app(settings)):
            pass

    missing_worker = subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "research",
            "--once",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert missing_worker.returncode != 0
    assert "unsupported existing Core schema" in missing_worker.stderr

    assert initialize_core(settings.database_url) is True
    fingerprint = _schema_fingerprint(settings.database_url)
    assert initialize_core(settings.database_url) is False
    assert _schema_fingerprint(settings.database_url) == fingerprint

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/data").status_code == 200
    worker = subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--role",
            "research",
            "--once",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert worker.returncode == 0, worker.stderr
    assert _schema_fingerprint(settings.database_url) == fingerprint


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_schema_initialization_refuses_a_partial_or_old_database() -> None:
    settings = CoreSettings.from_environment()
    _drop_core_schemas(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            transaction.execute("CREATE SCHEMA data")
            transaction.execute("CREATE TABLE data.legacy_state (value text)")
        with pytest.raises(SchemaError, match="run pnpm dev:reset"):
            initialize_core(settings.database_url)
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT count(*) AS count FROM data.legacy_state"
            ).fetchone()
            assert row is not None
            assert row["count"] == 0
    finally:
        _drop_core_schemas(settings.database_url)
        database.close()


def _drop_core_schemas(database_url: str) -> None:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            for schema in reversed((*CORE_SCHEMAS, "thesistrace_meta")):
                transaction.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        database.close()


def _schema_fingerprint(database_url: str) -> str:
    database = PostgresDatabase(database_url)
    database.open()
    try:
        with database.transaction() as transaction:
            row = transaction.execute(
                "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton = true"
            ).fetchone()
            assert row is not None
            return str(row["fingerprint"])
    finally:
        database.close()
