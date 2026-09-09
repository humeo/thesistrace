from importlib.resources import files

import pytest
from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace.migrations.rank_ic_0001 import MIGRATION, SOURCE, TARGET, migrate


@pytest.fixture
def migration_database(core_settings):
    db = PostgresDatabase(core_settings.database_url)
    db.open()
    with db.transaction() as tx:
        # This test uses the isolated runner's database, never the development database.
        tx.execute("DROP SCHEMA IF EXISTS research_runs CASCADE")
        tx.execute("DROP SCHEMA IF EXISTS thesistrace_meta CASCADE")
        tx.execute("CREATE SCHEMA research_runs")
        tx.execute("CREATE SCHEMA thesistrace_meta")
        clause = files("thesistrace.migrations").joinpath("0001_source.sql").read_text()
        tx.execute(
            "CREATE TABLE research_runs.runs (id text PRIMARY KEY, "
            "immutable_input jsonb, key_metrics jsonb, result_manifest_sha256 text, "
            f"result_provenance jsonb, {clause})"
        )
        tx.execute(
            "CREATE TABLE thesistrace_meta.schema_contract "
            "(singleton boolean PRIMARY KEY, fingerprint text)"
        )
        tx.execute("INSERT INTO thesistrace_meta.schema_contract VALUES (true, %s)", (SOURCE,))
        for run_id in ("first", "second"):
            tx.execute(
                "INSERT INTO research_runs.runs VALUES (%s, %s, %s, %s, %s)",
                (
                    run_id,
                    Jsonb({"research_kind": "strategy_backtest"}),
                    Jsonb(
                        {
                            "research_kind": "strategy_backtest",
                            "annualized_excess_return": 0.1,
                            "sharpe": 1.5,
                            "maximum_drawdown": 0.2,
                        }
                    ),
                    "immutable-result",
                    Jsonb({"research_run_id": run_id}),
                ),
            )
    try:
        yield db
    finally:
        with db.transaction() as tx:
            tx.execute("DROP SCHEMA research_runs CASCADE")
            tx.execute("DROP SCHEMA thesistrace_meta CASCADE")
        db.close()


def metrics(row):
    return {
        "one_session_rank_ic": 0.125 if row["id"] == "first" else -0.25,
        "five_session_rank_ic": None,
        "twenty_session_rank_ic": 0.5,
    }


def snapshot(db):
    with db.transaction() as tx:
        return tx.execute("SELECT * FROM research_runs.runs ORDER BY id").fetchall()


def test_migration_dry_run_apply_preserves_evidence_and_repeat_is_noop(migration_database):
    db = migration_database
    before = snapshot(db)
    assert migrate(db, metrics)["status"] == "validated"
    assert snapshot(db) == before
    assert migrate(db, metrics, apply=True)["updated"] == 2
    after = snapshot(db)
    for old, new in zip(before, after, strict=True):
        assert {k: v for k, v in old.items() if k != "key_metrics"} == {
            k: v for k, v in new.items() if k != "key_metrics"
        }
        assert new["key_metrics"] == {**old["key_metrics"], **metrics(old)}
    with db.transaction() as tx:
        assert tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract"
        ).fetchone() == {"fingerprint": TARGET}
        assert tx.execute(
            "SELECT id, updated_rows FROM thesistrace_meta.migration_history"
        ).fetchone() == {"id": MIGRATION, "updated_rows": 2}
        assert tx.execute(
            "SELECT id FROM research_runs.runs WHERE "
            "(key_metrics->>'one_session_rank_ic')::float > 0"
        ).fetchall() == [{"id": "first"}]
    assert migrate(db, lambda _row: pytest.fail("must not reload"), apply=True)["status"] == (
        "already_current"
    )


@pytest.mark.parametrize("failure", ["unknown_version", "missing_result", "late_write"])
def test_migration_failure_leaves_rows_constraint_and_version_unchanged(
    migration_database, failure
):
    db = migration_database
    if failure == "unknown_version":
        with db.transaction() as tx:
            tx.execute("UPDATE thesistrace_meta.schema_contract SET fingerprint = 'unknown'")
    if failure == "late_write":
        with db.transaction() as tx:
            tx.execute(
                "CREATE TABLE thesistrace_meta.migration_history "
                "(id text PRIMARY KEY, source_fingerprint text, target_fingerprint text, "
                "updated_rows integer CHECK (updated_rows = 0))"
            )
    before = snapshot(db)

    def read(row):
        if failure == "missing_result" and row["id"] == "second":
            raise ValueError("missing immutable result")
        return metrics(row)

    with pytest.raises(CheckViolation if failure == "late_write" else ValueError):
        migrate(db, read, apply=True)
    assert snapshot(db) == before
    with db.transaction() as tx:
        assert tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract"
        ).fetchone() == {"fingerprint": "unknown" if failure == "unknown_version" else SOURCE}
        # The old constraint still rejects a new metric after rollback.
        with pytest.raises(CheckViolation):
            tx.execute(
                "UPDATE research_runs.runs SET key_metrics = key_metrics || "
                "'{\"one_session_rank_ic\":0.1}'::jsonb"
            )
