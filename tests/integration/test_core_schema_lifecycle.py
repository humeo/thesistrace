from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from thesistrace._postgres import PostgresDatabase, SchemaError
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import (
    CORE_SCHEMAS,
    configure_core_runtime_access,
    initialize_core,
)


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


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_core_runtime_access_is_exact_and_does_not_cross_into_auth() -> None:
    settings = CoreSettings.from_environment()
    _drop_core_schemas(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        initialize_core(settings.database_url)
        with database.transaction() as transaction:
            transaction.execute("CREATE SCHEMA auth")
            transaction.execute("CREATE TABLE auth.access_probe (value text)")
            transaction.execute("GRANT USAGE ON SCHEMA data TO auth_runtime")
            transaction.execute(
                "GRANT SELECT ON data.current_dataset_state TO auth_runtime"
            )
            transaction.execute(
                "GRANT USAGE ON SEQUENCE daily_tracks.work_queue_sequence "
                "TO auth_runtime"
            )
            transaction.execute(
                "GRANT USAGE ON SCHEMA thesistrace_meta TO auth_runtime"
            )
            transaction.execute(
                "GRANT UPDATE ON thesistrace_meta.schema_contract TO auth_runtime"
            )

        configure_core_runtime_access(settings.database_url)
        configure_core_runtime_access(settings.database_url)

        with database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT
                    has_schema_privilege('core_runtime', 'data', 'USAGE') AS core_data,
                    has_schema_privilege('core_runtime', 'data', 'CREATE') AS core_create,
                    has_table_privilege(
                        'core_runtime', 'data.current_dataset_state', 'SELECT'
                    ) AS core_select,
                    has_table_privilege(
                        'core_runtime', 'data.current_dataset_state', 'TRUNCATE'
                    ) AS core_truncate,
                    has_table_privilege(
                        'core_runtime', 'thesistrace_meta.schema_contract', 'SELECT'
                    ) AS core_metadata_select,
                    has_table_privilege(
                        'core_runtime', 'thesistrace_meta.schema_contract', 'UPDATE'
                    ) AS core_metadata_update,
                    has_sequence_privilege(
                        'core_runtime', 'daily_tracks.work_queue_sequence', 'USAGE'
                    ) AS core_sequence,
                    has_schema_privilege('core_runtime', 'auth', 'USAGE') AS core_auth,
                    has_table_privilege(
                        'core_runtime', 'auth.access_probe', 'SELECT'
                    ) AS core_auth_select,
                    has_schema_privilege('auth_runtime', 'data', 'USAGE') AS auth_data,
                    has_table_privilege(
                        'auth_runtime', 'data.current_dataset_state', 'SELECT'
                    ) AS auth_data_select,
                    has_sequence_privilege(
                        'auth_runtime', 'daily_tracks.work_queue_sequence', 'USAGE'
                    ) AS auth_sequence,
                    has_schema_privilege(
                        'auth_runtime', 'thesistrace_meta', 'USAGE'
                    ) AS auth_metadata,
                    has_table_privilege(
                        'auth_runtime', 'thesistrace_meta.schema_contract', 'UPDATE'
                    ) AS auth_metadata_update
                """
            ).fetchone()
            assert row is not None
            assert row == {
                "auth_data": False,
                "auth_data_select": False,
                "auth_metadata": False,
                "auth_metadata_update": False,
                "auth_sequence": False,
                "core_auth": False,
                "core_auth_select": False,
                "core_create": False,
                "core_data": True,
                "core_metadata_select": True,
                "core_metadata_update": False,
                "core_select": True,
                "core_sequence": True,
                "core_truncate": False,
            }
    finally:
        with database.transaction() as transaction:
            transaction.execute("DROP SCHEMA IF EXISTS auth CASCADE")
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
