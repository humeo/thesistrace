from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import CheckViolation

from thesistrace._postgres import PostgresDatabase, initialize_schemas
from thesistrace.entrypoints.schema import verify_core_schema


@pytest.fixture
def indicator_source_database(core_settings, historical_core_schema):
    name = "indicator_upgrade_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    options = conninfo_to_dict(core_settings.database_url)
    options["dbname"] = name
    database = PostgresDatabase(make_conninfo(**options))
    database.open()
    try:
        initialize_schemas(database, historical_core_schema)
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO publication.objects(sha256, byte_size) VALUES (%s, 123)",
                ("a" * 64,),
            )
            tx.execute(
                "INSERT INTO data.financial_daily_refresh_operations ("
                "idempotency_key, fingerprint, source_generation_manifest_sha256, "
                "prior_financial_manifest_sha256, discovery_baseline_session, "
                "prior_attempted_through_session, prior_complete_through_session, "
                "target_session, status, failure_code, created_at, updated_at, finished_at) "
                "VALUES ('retained-refresh', %s, %s, %s, '2026-08-01', '2026-08-01', "
                "'2026-08-01', '2026-08-02', 'failed', 'UPSTREAM_UNAVAILABLE', "
                "'2026-08-02', '2026-08-02', '2026-08-02')",
                ("b" * 64, "c" * 64, "d" * 64),
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_indicator_upgrade_preserves_data_and_verifies_repeat(indicator_source_database):
    from thesistrace.migrations.financial_indicator import upgrade

    database = indicator_source_database
    with database.transaction() as tx:
        before = tx.execute("SELECT * FROM data.financial_daily_refresh_operations").fetchall()
    assert upgrade(database)["status"] == "validated"
    assert upgrade(database, apply=True)["status"] == "applied"
    assert upgrade(database, apply=True)["status"] == "already_current"
    verify_core_schema(database)
    with database.transaction() as tx:
        after = tx.execute("SELECT * FROM data.financial_daily_refresh_operations").fetchall()
        for row in after:
            assert row.pop("indicator_collection") is None
            assert row.pop("indicator_candidate_manifest_sha256") is None
        assert after == before
        assert (
            tx.execute("SELECT byte_size FROM publication.objects").fetchone()["byte_size"] == 123
        )
        assert (
            tx.execute("SELECT count(*) AS n FROM thesistrace_meta.migration_history").fetchone()[
                "n"
            ]
            == 1
        )
        tx.execute(
            "INSERT INTO data.financial_indicator_reconciliation VALUES ('equity:A.SH', "
            "'2026-08-02', %s)",
            ("e" * 64,),
        )
        tx.execute(
            "INSERT INTO data.financial_indicator_collections VALUES (%s, 'equity:A.SH', "
            "'2026-08-02')",
            ("e" * 64,),
        )
    assert upgrade(database, apply=True)["status"] == "already_current"
    with database.transaction() as tx:
        assert (
            tx.execute("SELECT count(*) AS n FROM data.financial_indicator_collections").fetchone()[
                "n"
            ]
            == 1
        )


def test_indicator_upgrade_late_failure_rolls_back_every_change(indicator_source_database):
    from thesistrace.migrations.financial_indicator import SOURCE, upgrade

    database = indicator_source_database
    with database.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history (id text PRIMARY KEY "
            "CHECK (id = 'reject-upgrade'), source_fingerprint text, "
            "target_fingerprint text, updated_rows integer)"
        )
    with pytest.raises(CheckViolation):
        upgrade(database, apply=True)
    with database.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute(
                "SELECT to_regclass('data.financial_indicator_reconciliation') AS name"
            ).fetchone()["name"]
            is None
        )
        row = tx.execute("SELECT * FROM data.financial_daily_refresh_operations").fetchone()
        assert "indicator_collection" not in row
        assert row["idempotency_key"] == "retained-refresh"


@pytest.mark.parametrize("already_applied", [False, True])
def test_indicator_upgrade_rejects_structure_drift(indicator_source_database, already_applied):
    from thesistrace.migrations.financial_indicator import upgrade

    database = indicator_source_database
    if already_applied:
        upgrade(database, apply=True)
    with database.transaction() as tx:
        tx.execute("ALTER TABLE data.financial_daily_refresh_operations ADD COLUMN unexpected text")
    with pytest.raises(ValueError, match="structure"):
        upgrade(database, apply=True)


def test_indicator_upgrade_rejects_unknown_contract(indicator_source_database):
    from thesistrace.migrations.financial_indicator import upgrade

    database = indicator_source_database
    with database.transaction() as tx:
        tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint = %s", ("f" * 64,))
    with pytest.raises(ValueError, match="source"):
        upgrade(database, apply=True)
