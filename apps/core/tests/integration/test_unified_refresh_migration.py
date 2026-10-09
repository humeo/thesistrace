from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.migrations.unified_refresh_0006 import SOURCE, TARGET, migrate


@pytest.fixture(autouse=True)
def release_contract(monkeypatch, unified_refresh_target_schemas):
    monkeypatch.setattr(
        "thesistrace.migrations.unified_refresh_0006.CORE_SCHEMA_DEFINITIONS",
        unified_refresh_target_schemas,
    )
    monkeypatch.setattr(
        "thesistrace.entrypoints.schema.CORE_SCHEMA_DEFINITIONS", unified_refresh_target_schemas
    )


@pytest.fixture
def source_database(core_settings, financial_disclosures_target_schemas):
    name = "unified_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    try:
        initialize_schemas(database, financial_disclosures_target_schemas)
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO data.refresh_operations "
                "(idempotency_key,kind,fingerprint,status,as_of,finished_at) "
                "VALUES ('old-market','market',%s,'cancelled','2026-09-17',now())",
                ("a" * 64,),
            )
            tx.execute(
                "INSERT INTO publication.objects(sha256,byte_size) VALUES (%s,123)", ("b" * 64,)
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_explicit_upgrade_preserves_history_and_is_repeatable(source_database):
    assert migrate(source_database)["status"] == "validated"
    assert migrate(source_database, apply=True)["status"] == "applied"
    verify_core_schema(source_database)
    assert migrate(source_database, apply=True)["status"] == "already_current"
    with source_database.transaction() as tx:
        receipt = tx.execute(
            "SELECT * FROM data.refresh_operations WHERE idempotency_key='old-market'"
        ).fetchone()
        assert receipt["kind"] == "market" and receipt["status"] == "cancelled"
        assert receipt["preparation"] == {} and receipt["retry_of"] is None
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )


def test_late_failure_rolls_back_receipt_schema_and_contract(source_database):
    with source_database.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history "
            "(id text PRIMARY KEY,source_fingerprint text,target_fingerprint text,"
            "updated_rows integer CHECK (updated_rows<0))"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        migrate(source_database, apply=True)
    with source_database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        receipt = tx.execute("SELECT * FROM data.refresh_operations").fetchone()
        assert "preparation" not in receipt and receipt["idempotency_key"] == "old-market"


def test_running_operations_block_migration(source_database):
    with source_database.transaction() as tx:
        tx.execute("UPDATE data.refresh_operations SET status='accepted',finished_at=NULL")
    with pytest.raises(ValueError, match="Drain"):
        migrate(source_database, apply=True)
