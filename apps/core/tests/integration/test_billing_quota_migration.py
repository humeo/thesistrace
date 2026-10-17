from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.migrations.billing_0011 import SOURCE, migrate, release_schemas


@pytest.fixture
def billing_source(core_settings):
    name = "billing_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    try:
        initialize_schemas(database, release_schemas("0011-source.zip"))
        with database.transaction() as tx:
            researcher = uuid4()
            tx.execute("INSERT INTO researchers.researchers(id) VALUES (%s)", (researcher,))
            tx.execute(
                "INSERT INTO research_runs.run_ownership(researcher_id,run_id) "
                "VALUES (%s,'deleted-history')",
                (researcher,),
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_billing_upgrade_preserves_deleted_history_and_repeats(billing_source):
    assert migrate(billing_source)["status"] == "validated"
    assert migrate(billing_source, apply=True)["preserved_runs"] == 1
    verify_core_schema(billing_source)
    assert migrate(billing_source, apply=True)["status"] == "already_current"
    with billing_source.transaction() as tx:
        assert tx.execute(
            "SELECT run_id,quota_started,quota_state FROM research_runs.run_ownership"
        ).fetchone() == dict(run_id="deleted-history", quota_started=True, quota_state="consumed")
        tx.execute("GRANT USAGE ON SCHEMA research_runs TO core_runtime")
        tx.execute("SET LOCAL ROLE core_runtime")
        assert tx.execute(
            "SELECT "
            "has_function_privilege(current_user,'research_runs.settle_run_quota()','EXECUTE')"
            " yes"
        ).fetchone()["yes"]


def test_billing_upgrade_late_receipt_failure_rolls_back_every_change(billing_source):
    with billing_source.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history(id text PRIMARY "
            "KEY,source_fingerprint text,target_fingerprint text,updated_rows "
            "integer CHECK(updated_rows<0))"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        migrate(billing_source, apply=True)
    assert migrate(billing_source)["status"] == "validated"
    with billing_source.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                "table_schema='research_runs' AND table_name='run_ownership' AND "
                "column_name='quota_state'"
            ).fetchone()
            is None
        )
