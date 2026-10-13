from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, initialize_schemas, verify_schemas
from thesistrace.migrations.execution_timing_0009 import SOURCE, TARGET, migrate


@pytest.fixture
def timing_source_database(core_settings, execution_timing_source_schemas):
    name = "timing_migration_" + uuid4().hex
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    database = PostgresDatabase(make_conninfo(**params))
    database.open()
    try:
        initialize_schemas(database, execution_timing_source_schemas)
        with database.transaction() as tx:
            researcher = uuid4()
            tx.execute("INSERT INTO researchers.researchers(id) VALUES (%s)", (researcher,))
            tx.execute(
                "INSERT INTO research_runs.run_ownership(researcher_id,run_id) "
                "VALUES (%s,'old-run')",
                (researcher,),
            )
            tx.execute(
                "INSERT INTO research_folders.folders(researcher_id,id,name,is_default) "
                "VALUES (%s,'folder_default','Default',true)",
                (researcher,),
            )
            tx.execute(
                "INSERT INTO research_runs.runs(researcher_id,id,folder_id,name,"
                "requested_start_date,requested_end_date,status,immutable_input) "
                "VALUES (%s,'old-run','folder_default','Old run','2026-10-13',"
                "'2026-10-13','succeeded','{\"research_kind\":\"factor_evaluation\"}')",
                (researcher,),
            )
            tx.execute(
                "INSERT INTO research_runs.attempts(id,run_id,ordinal,fence,generation_pin_id,"
                "data_generation_id,data_through_session,status,finished_at,lease_expires_at) "
                "VALUES ('old-attempt','old-run',1,1,'old-pin','old-generation','2026-10-13',"
                "'succeeded',now(),now())"
            )
        yield database
    finally:
        database.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def measurement(seconds=487):
    return (
        {
            "owner": "ordinary_attempt",
            "attempt_id": "old-attempt",
            "processing_seconds": seconds,
            "chunk_ordinal": 56,
        },
    )


def test_upgrade_preserves_history_backfills_measured_time_and_is_idempotent(
    timing_source_database, execution_timing_target_schemas,
):
    db = timing_source_database
    with db.transaction() as tx:
        before = tx.execute("SELECT * FROM research_runs.attempts").fetchone()
    assert migrate(db, measurements=measurement())["status"] == "validated"
    assert migrate(db, apply=True, measurements=measurement())["backfilled"] == 1
    verify_schemas(db, execution_timing_target_schemas)
    assert migrate(db, apply=True, measurements=measurement())["backfilled"] == 0
    with db.transaction() as tx:
        after = tx.execute("SELECT * FROM research_runs.attempts").fetchone()
        assert {key: after[key] for key in before} == before
        assert after["processing_seconds"] == 487
        assert after["processing_chunk_ordinal"] == 56
        assert (
            tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()["n"]
            == 1
        )


def test_missing_historical_measurement_remains_unknown(timing_source_database):
    migrate(timing_source_database, apply=True)
    with timing_source_database.transaction() as tx:
        assert (
            tx.execute("SELECT processing_seconds FROM research_runs.attempts").fetchone()[
                "processing_seconds"
            ]
            is None
        )


@pytest.mark.parametrize("damage", ["late", "invalid_evidence", "source_drift", "unknown"])
def test_invalid_or_failed_upgrade_preserves_source_contract(timing_source_database, damage):
    db = timing_source_database
    with db.transaction() as tx:
        if damage == "late":
            tx.execute(
                "CREATE TABLE thesistrace_meta.migration_history (id text PRIMARY KEY,"
                "source_fingerprint text,target_fingerprint text,"
                "updated_rows integer CHECK(updated_rows<0))"
            )
        elif damage == "source_drift":
            tx.execute("ALTER TABLE research_runs.attempts DROP CONSTRAINT attempts_fence_check")
        elif damage == "unknown":
            tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint='unknown'")
    values = measurement(-1) if damage == "invalid_evidence" else measurement()
    with pytest.raises((ValueError, psycopg.errors.CheckViolation)):
        migrate(db, apply=True, measurements=values)
    with db.transaction() as tx:
        assert tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
            "fingerprint"
        ] == ("unknown" if damage == "unknown" else SOURCE)
        columns = tx.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid='research_runs.attempts'::regclass "
            "AND attnum>0 AND NOT attisdropped"
        ).fetchall()
        assert "processing_seconds" not in {r["attname"] for r in columns}


def test_repeated_upgrade_rejects_conflicting_history(timing_source_database):
    db = timing_source_database
    migrate(db, apply=True, measurements=measurement())
    with pytest.raises(ValueError, match="conflicts"):
        migrate(db, apply=True, measurements=measurement(500))
    with db.transaction() as tx:
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )
        assert (
            tx.execute("SELECT processing_seconds FROM research_runs.attempts").fetchone()[
                "processing_seconds"
            ]
            == 487
        )
