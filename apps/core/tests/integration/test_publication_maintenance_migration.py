import os
from importlib.resources import files
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, SchemaDefinition, initialize_schemas
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS


@pytest.fixture
def historical_database(core_settings):
    assert os.environ["THESISTRACE_TEST_PROJECT_NAME"].startswith("thesistrace-test-")
    name = "maintenance_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    options = conninfo_to_dict(core_settings.database_url)
    options["dbname"] = name
    database = PostgresDatabase(make_conninfo(**options))
    database.open()
    source = files("thesistrace.migrations").joinpath("0002_source_publication.sql").read_text()
    definitions = tuple(
        SchemaDefinition(d.name, source) if d.name == "publication" else d
        for d in CORE_SCHEMA_DEFINITIONS
    )
    try:
        initialize_schemas(database, definitions)
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO publication.objects(sha256, byte_size) VALUES (%s, 123)", ("a" * 64,)
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_explicit_upgrade_repeat_and_reverse_preserve_existing_data(historical_database):
    from thesistrace.migrations.publication_maintenance_0002 import SOURCE, TARGET, migrate

    database = historical_database
    with database.transaction() as tx:
        before = tx.execute("SELECT * FROM publication.objects").fetchall()
    assert migrate(database)["status"] == "validated"
    assert migrate(database, apply=True)["status"] == "applied"

    assert migrate(database, apply=True)["status"] == "already_current"
    with database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )
        assert (
            tx.execute("SELECT count(*) AS n FROM publication.maintenance_state").fetchone()["n"]
            == 2
        )
        assert tx.execute("SELECT * FROM publication.objects").fetchall() == before
    assert migrate(database, reverse=True)["status"] == "validated"
    assert migrate(database, reverse=True, apply=True)["status"] == "applied"
    assert migrate(database, reverse=True, apply=True)["status"] == "already_current"
    with database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute(
                "SELECT to_regclass(%s) AS table_name", ("publication.maintenance_state",)
            ).fetchone()["table_name"]
            is None
        )
        assert tx.execute("SELECT * FROM publication.objects").fetchall() == before
        archived = tx.execute(
            "SELECT state FROM thesistrace_meta.maintenance_rollback_archive"
        ).fetchone()["state"]
        assert {row["job"] for row in archived} == {"orphan_scan", "queued_deletions"}
    assert migrate(database, apply=True)["status"] == "applied"


def test_late_upgrade_failure_rolls_back_ddl_and_fingerprint(historical_database):
    from psycopg.errors import CheckViolation

    from thesistrace.migrations.publication_maintenance_0002 import SOURCE, migrate

    database = historical_database
    with database.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history ("
            "id text PRIMARY KEY, source_fingerprint text, target_fingerprint text, "
            "updated_rows integer CHECK (updated_rows = 0))"
        )
    with pytest.raises(CheckViolation):
        migrate(database, apply=True)
    with database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute("SELECT to_regclass('publication.maintenance_state') AS name").fetchone()[
                "name"
            ]
            is None
        )
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )


def test_reverse_failure_restores_table_and_does_not_archive_partial_state(historical_database):
    from psycopg.errors import CheckViolation

    from thesistrace.migrations.publication_maintenance_0002 import TARGET, migrate

    database = historical_database
    migrate(database, apply=True)
    with database.transaction() as tx:
        tx.execute(
            "ALTER TABLE thesistrace_meta.migration_history ADD CONSTRAINT "
            "reject_new_event CHECK (id NOT LIKE '%:reverse:%')"
        )
    with pytest.raises(CheckViolation):
        migrate(database, reverse=True, apply=True)
    with database.transaction() as tx:
        assert (
            tx.execute("SELECT count(*) AS n FROM publication.maintenance_state").fetchone()["n"]
            == 2
        )
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )
        assert (
            tx.execute(
                "SELECT to_regclass('thesistrace_meta.maintenance_rollback_archive') AS name"
            ).fetchone()["name"]
            is None
        )


def test_migration_rejects_target_structure_drift(historical_database):
    from thesistrace.migrations.publication_maintenance_0002 import migrate

    database = historical_database
    migrate(database, apply=True)
    with database.transaction() as tx:
        tx.execute(
            "ALTER TABLE publication.maintenance_state ALTER COLUMN failure_count DROP NOT NULL"
        )
    with pytest.raises(ValueError, match="differs"):
        migrate(database, reverse=True, apply=True)
