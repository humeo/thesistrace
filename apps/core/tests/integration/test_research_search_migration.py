from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas, verify_schemas
from thesistrace.migrations.billing_0011 import release_schemas
from thesistrace.migrations.research_search_0010 import SOURCE, TARGET, migrate


@pytest.fixture
def source_database(core_settings, execution_timing_target_schemas):
    name = "search_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    try:
        initialize_schemas(database, execution_timing_target_schemas)
        with database.transaction() as tx:
            researcher = uuid4()
            tx.execute("INSERT INTO researchers.researchers(id) VALUES (%s)", (researcher,))
            tx.execute(
                "INSERT INTO research_folders.folders(researcher_id,id,name,is_default) "
                "VALUES (%s,'folder_default','Default',true)", (researcher,),
            )
            tx.execute(
                "INSERT INTO research_runs.run_ownership(researcher_id,run_id) "
                "VALUES (%s,'old-run')", (researcher,),
            )
            tx.execute(
                "INSERT INTO research_runs.runs(researcher_id,id,folder_id,name,"
                "requested_start_date,requested_end_date,status,immutable_input) VALUES "
                "(%s,'old-run','folder_default','中文动量', '2026-01-01','2026-01-02','cancelled',"
                "'{\"research_kind\":\"factor_evaluation\",\"hypothesis\":\"Keep Turnover Low\","
                "\"formula_source\":\"CLOSE\"}')", (researcher,),
            )
            tx.execute("INSERT INTO publication.objects(sha256,byte_size) VALUES (%s,123)",
                       ("b" * 64,))
            tx.execute("GRANT USAGE ON SCHEMA research_runs TO core_runtime")
            tx.execute("GRANT SELECT, UPDATE ON research_runs.runs TO core_runtime")
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_upgrade_backfills_search_preserves_data_and_verifies_on_repeat(source_database):
    with source_database.transaction() as tx:
        before = tx.execute("SELECT * FROM research_runs.runs").fetchone()
    assert migrate(source_database)["status"] == "validated"
    with source_database.transaction() as tx:
        assert tx.execute("SELECT * FROM research_runs.runs").fetchone() == before
        assert tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
            "fingerprint"
        ] == SOURCE
    assert migrate(source_database, apply=True)["preserved_runs"] == 1
    verify_schemas(source_database,release_schemas("0011-source.zip"))
    assert migrate(source_database, apply=True)["status"] == "already_current"
    with source_database.transaction() as tx:
        after = tx.execute("SELECT * FROM research_runs.runs").fetchone()
        assert after.pop("search_notes") == "keep turnover low"
        assert after.pop("search_formula") == "close"
        assert after == before
        assert tx.execute("SELECT byte_size FROM publication.objects").fetchone()[
            "byte_size"
        ] == 123
        assert tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()[
            "n"
        ] == 1
        assert tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
            "fingerprint"
        ] == TARGET
        tx.execute("SET LOCAL ROLE core_runtime")
        tx.execute("UPDATE research_runs.runs SET name='Renamed', immutable_input="
                   "immutable_input || '{\"hypothesis\":null,\"formula_source\":\"OPEN\"}'")
        assert tx.execute(
            "SELECT name,search_notes,search_formula FROM research_runs.runs"
        ).fetchone() == {"name": "Renamed", "search_notes": None, "search_formula": "open"}


def test_late_failure_rolls_back_backfill_index_extension_and_receipt(source_database):
    with source_database.transaction() as tx:
        before = tx.execute("SELECT * FROM research_runs.runs").fetchone()
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text,target_fingerprint text,"
            "updated_rows integer CHECK(updated_rows<0))"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        migrate(source_database, apply=True)
    assert migrate(source_database)["status"] == "validated"
    with source_database.transaction() as tx:
        assert tx.execute("SELECT * FROM research_runs.runs").fetchone() == before
        assert tx.execute("SELECT 1 FROM pg_extension WHERE extname='pg_trgm'").fetchone() is None
        assert tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()[
            "n"
        ] == 0
        assert tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
            "fingerprint"
        ] == SOURCE


@pytest.mark.parametrize("damage", ["unknown", "source", "index", "generated", "target"])
def test_rejects_unknown_versions_and_structure_drift(source_database, damage):
    if damage in {"index", "generated", "target"}:
        migrate(source_database, apply=True)
    with source_database.transaction() as tx:
        if damage == "unknown":
            tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint='unknown'")
        elif damage == "index":
            tx.execute("DROP INDEX research_runs.research_runs_search_idx")
        elif damage == "generated":
            tx.execute("ALTER TABLE research_runs.runs ALTER COLUMN search_notes DROP EXPRESSION")
        else:
            tx.execute("ALTER TABLE research_runs.runs ALTER COLUMN name DROP NOT NULL")
    with pytest.raises(ValueError):
        migrate(source_database, apply=True)
