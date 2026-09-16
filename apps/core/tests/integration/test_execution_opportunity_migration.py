from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas


@pytest.fixture
def source_database(core_settings, payload_retention_target_schemas):
    name = "execution_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    db = PostgresDatabase(make_conninfo(**params))
    db.open()
    try:
        initialize_schemas(db, payload_retention_target_schemas)
        with db.transaction() as tx:
            tx.execute("INSERT INTO researchers.researchers(id) VALUES (%s)", (uuid4(),))
            tx.execute(
                "INSERT INTO publication.objects(sha256, byte_size) VALUES (%s, 123)", ("a" * 64,)
            )
        yield db
    finally:
        db.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_upgrade_preserves_data_and_repeat_preserves_scheduling_state(source_database):
    from thesistrace.migrations.execution_opportunities_0004 import SOURCE, TARGET, migrate

    db = source_database
    with db.transaction() as tx:
        before = tx.execute("SELECT * FROM researchers.researchers").fetchall()
    assert migrate(db)["status"] == "validated"
    with db.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute("SELECT to_regclass('researchers.execution_opportunities') t").fetchone()[
                "t"
            ]
            is None
        )
    assert migrate(db, apply=True)["status"] == "applied"
    with db.transaction() as tx:
        assert tx.execute(
            "SELECT has_table_privilege('core_runtime', "
            "'researchers.execution_opportunities', 'SELECT,INSERT,UPDATE,DELETE') ok"
        ).fetchone()["ok"]
        assert tx.execute(
            "SELECT has_sequence_privilege('core_runtime', "
            "'researchers.execution_opportunity_sequence', 'USAGE,SELECT,UPDATE') ok"
        ).fetchone()["ok"]
        tx.execute(
            "INSERT INTO researchers.execution_opportunities VALUES "
            "('research', %s, nextval('researchers.execution_opportunity_sequence'))",
            (before[0]["id"],),
        )
        state = tx.execute("SELECT * FROM researchers.execution_opportunities").fetchall()
    assert migrate(db, apply=True)["status"] == "already_current"
    with db.transaction() as tx:
        assert tx.execute("SELECT * FROM researchers.execution_opportunities").fetchall() == state
        assert tx.execute("SELECT * FROM researchers.researchers").fetchall() == before
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )
        assert (
            tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()["n"]
            == 1
        )
        assert (
            tx.execute("SELECT nextval('researchers.execution_opportunity_sequence') n").fetchone()[
                "n"
            ]
            == 2
        )


def test_late_failure_rolls_back_table_sequence_receipt_and_contract(source_database):
    from thesistrace.migrations.execution_opportunities_0004 import SOURCE, migrate

    with source_database.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text, target_fingerprint text, "
            "updated_rows integer CHECK (updated_rows < 0))"
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
        for name in ("execution_opportunities", "execution_opportunity_sequence"):
            assert (
                tx.execute("SELECT to_regclass(%s) t", (f"researchers.{name}",)).fetchone()["t"]
                is None
            )
        assert (
            tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()["n"]
            == 0
        )
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )


@pytest.mark.parametrize("damage", ["unknown", "source", "table", "sequence"])
def test_rejects_unknown_contract_and_structure_drift(source_database, damage):
    from thesistrace.migrations.execution_opportunities_0004 import migrate

    if damage in {"table", "sequence"}:
        migrate(source_database, apply=True)
    with source_database.transaction() as tx:
        if damage == "unknown":
            tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint = 'unknown'")
        elif damage == "source":
            tx.execute("ALTER TABLE researchers.researchers ALTER COLUMN updated_at DROP NOT NULL")
        elif damage == "table":
            tx.execute(
                "ALTER TABLE researchers.execution_opportunities "
                "ALTER COLUMN last_sequence DROP NOT NULL"
            )
        else:
            tx.execute("ALTER SEQUENCE researchers.execution_opportunity_sequence INCREMENT BY 2")
    with pytest.raises(ValueError):
        migrate(source_database, apply=True)
