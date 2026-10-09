from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.migrations.independent_strategies_0007 import SOURCE, TARGET, migrate


@pytest.fixture
def source_database(core_settings, unified_refresh_target_schemas):
    name = "independent_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    try:
        initialize_schemas(database, unified_refresh_target_schemas)
        with database.transaction() as tx:
            researcher = uuid4()
            tx.execute("INSERT INTO researchers.researchers(id) VALUES (%s)", (researcher,))
            tx.execute(
                "INSERT INTO research_batches.batches(researcher_id,id,batch_kind,status,scope) "
                "VALUES (%s,'old-batch','strategy_sweep','succeeded','{}')",
                (researcher,),
            )
            tx.execute(
                "INSERT INTO publication.objects(sha256,byte_size) VALUES (%s,123)", ("b" * 64,)
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_upgrade_preserves_history_and_repeat_verifies_new_contract(source_database):
    with source_database.transaction() as tx:
        before = tx.execute("SELECT * FROM research_batches.batches").fetchall()
    assert migrate(source_database)["status"] == "validated"
    with source_database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
    assert migrate(source_database, apply=True)["preserved_batches"] == 1
    verify_core_schema(source_database)
    assert migrate(source_database, apply=True)["status"] == "already_current"
    with source_database.transaction() as tx:
        assert tx.execute("SELECT * FROM research_batches.batches").fetchall() == before
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )
        assert (
            tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()["n"]
            == 1
        )
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )
        tx.execute("UPDATE research_batches.batches SET batch_kind='independent_strategies'")


def test_late_failure_rolls_back_columns_indexes_receipt_and_contract(source_database):
    with source_database.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text,target_fingerprint text,"
            "updated_rows integer CHECK(updated_rows<0))"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        migrate(source_database, apply=True)
    assert migrate(source_database)["status"] == "validated"
    with source_database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()["n"]
            == 0
        )
        assert (
            tx.execute("SELECT batch_kind FROM research_batches.batches").fetchone()["batch_kind"]
            == "strategy_sweep"
        )


@pytest.mark.parametrize("damage", ["unknown", "source", "target", "index", "active"])
def test_rejects_drift_and_active_writers(source_database, damage):
    if damage in {"target", "index"}:
        migrate(source_database, apply=True)
    with source_database.transaction() as tx:
        if damage == "unknown":
            tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint='unknown'")
        elif damage in {"source", "target"}:
            tx.execute(
                "ALTER TABLE research_batches.task_attempts "
                "DROP CONSTRAINT task_attempts_role_check"
            )
        elif damage == "index":
            tx.execute(
                "DROP INDEX research_batches.research_batch_independent_task_attempts_running_idx"
            )
        else:
            tx.execute("UPDATE research_batches.batches SET status='running'")
    with pytest.raises(ValueError):
        migrate(source_database, apply=True)
