from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas
from thesistrace.entrypoints.schema import verify_core_schema
from thesistrace.migrations.financial_disclosures_0005 import SOURCE, TARGET, migrate


@pytest.fixture
def source_database(core_settings, execution_opportunity_target_schemas):
    name = "disclosure_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    try:
        initialize_schemas(database, execution_opportunity_target_schemas)
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO data.financial_indicator_report_targets "
                "(instrument_id, report_period, announced_on) "
                "VALUES ('preserved', NULL, '2026-09-11')"
            )
            tx.execute(
                "INSERT INTO publication.objects(sha256, byte_size) VALUES (%s, 123)", ("a" * 64,)
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_upgrade_preserves_legacy_evidence_and_does_not_fabricate_report_completion(
    source_database,
):
    db = source_database
    with db.transaction() as tx:
        original = tx.execute("SELECT * FROM data.financial_indicator_report_targets").fetchall()
    assert migrate(db)["status"] == "validated"
    assert migrate(db, apply=True)["status"] == "applied"
    verify_core_schema(db)
    with db.transaction() as tx:
        assert (
            tx.execute("SELECT * FROM data.financial_indicator_report_targets").fetchall()
            == original
        )
        assert (
            tx.execute("SELECT count(*) n FROM data.financial_report_targets").fetchone()["n"] == 0
        )
        tx.execute(
            "INSERT INTO data.financial_report_targets VALUES "
            "('preserved', 'fina_indicator', '2026-06-30', '2026-08-29', NULL)"
        )
    assert migrate(db, apply=True)["status"] == "already_current"
    with db.transaction() as tx:
        assert (
            tx.execute(
                "SELECT resolved_evidence_sha256 r FROM data.financial_report_targets"
            ).fetchone()["r"]
            is None
        )
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )


def test_late_failure_rolls_back_ddl_receipt_and_fingerprint(source_database):
    with source_database.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history "
            "(id text PRIMARY KEY, source_fingerprint text, target_fingerprint text, "
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
        assert (
            tx.execute("SELECT to_regclass('data.financial_report_targets') t").fetchone()["t"]
            is None
        )
        assert (
            tx.execute("SELECT count(*) n FROM data.financial_indicator_report_targets").fetchone()[
                "n"
            ]
            == 1
        )


@pytest.mark.parametrize("damage", ["unknown", "source", "target"])
def test_migration_rejects_unknown_contract_and_drift(source_database, damage):
    if damage == "target":
        migrate(source_database, apply=True)
    with source_database.transaction() as tx:
        if damage == "unknown":
            tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint='unknown'")
        elif damage == "source":
            tx.execute(
                "ALTER TABLE data.financial_daily_refresh_operations "
                "ALTER COLUMN target_session DROP NOT NULL"
            )
        else:
            tx.execute(
                "ALTER TABLE data.financial_report_targets ALTER COLUMN actual_date DROP NOT NULL"
            )
    with pytest.raises(ValueError):
        migrate(source_database, apply=True)
