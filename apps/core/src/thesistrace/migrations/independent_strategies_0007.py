"""Data-preserving upgrade for independent Strategy Batches and task progress."""

from __future__ import annotations

import argparse
import json
import os
import re
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from thesistrace._postgres import PostgresDatabase
from thesistrace.migrations.financial_indicator import _shape

SOURCE = "84827a4b8a6c9bb9d0171e4a7aa42cfefb061216a98295a1e7d784632c237070"
TARGET = "423422281705fa7018c712268141c15fc58de13de7d1b46523a449e84a66c00d"
MIGRATION = "0007_independent_strategies"
_TABLES = ("batches", "task_attempts", "cancel_receipts")


def _table_ddl(statement: str, table: str) -> str:
    match = re.search(rf"^CREATE TABLE research_batches\.{table} \([\s\S]+?^\);", statement, re.M)
    if match is None:
        raise ValueError("Migration table definition is missing")
    return match.group()


def _index_ddl(statement: str, table: str) -> list[str]:
    return re.findall(
        rf"^CREATE (?:UNIQUE )?INDEX \w+\s+ON research_batches\.{table}\b[\s\S]+?;",
        statement,
        re.M,
    )


def _indexes(tx, schema: str, table: str):
    rows = tx.execute(
        "SELECT pg_get_indexdef(indexrelid) AS definition, indisvalid, indisready "
        "FROM pg_index WHERE indrelid = %s::regclass",
        (f"{schema}.{table}",),
    ).fetchall()
    return sorted(
        (
            row["definition"].replace(f" ON {schema}.", " ON research_batches."),
            row["indisvalid"],
            row["indisready"],
        )
        for row in rows
    )


def _verify_structure(tx, statement: str) -> None:
    # A private, transaction-local schema permits the original foreign keys to
    # reference permanent tables. It is removed before commit, including dry runs.
    expected = "migration_0007_" + uuid4().hex
    tx.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(expected)))
    for table in _TABLES:
        tx.execute(
            _table_ddl(statement, table).replace(
                "CREATE TABLE research_batches.", f"CREATE TABLE {expected}.", 1
            )
        )
        for index in _index_ddl(statement, table):
            tx.execute(index.replace("ON research_batches.", f"ON {expected}."))
        if _shape(tx, f"research_batches.{table}") != _shape(tx, f"{expected}.{table}"):
            raise ValueError(f"Batch table differs from declared contract: {table}")
        if _indexes(tx, "research_batches", table) != _indexes(tx, expected, table):
            raise ValueError(f"Batch indexes differ from declared contract: {table}")
    tx.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(expected)))


def migrate(database: PostgresDatabase, *, apply: bool = False) -> dict:
    source = files(__package__).joinpath("0007_source_research_batch.sql").read_text()
    target = files(__package__).joinpath("0007_target_research_batch.sql").read_text()
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '60s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        tx.execute(
            "LOCK TABLE research_batches.batches, research_batches.task_attempts, "
            "research_batches.cancel_receipts IN ACCESS EXCLUSIVE MODE"
        )
        _verify_structure(tx, source if current == SOURCE else target)
        if current == TARGET:
            return dict(migration=MIGRATION, status="already_current", updated=0)
        if tx.execute(
            "SELECT 1 FROM research_batches.batches WHERE status IN ('running','cancelling') "
            "UNION ALL SELECT 1 FROM research_batches.starting_claims "
            "UNION ALL SELECT 1 FROM research_batches.attempts WHERE status='running' LIMIT 1"
        ).fetchone():
            raise ValueError("Drain active Batches and stop writers before upgrading")
        report = dict(
            migration=MIGRATION,
            source=SOURCE,
            target=TARGET,
            status="applied" if apply else "validated",
            updated=0,
            preserved_batches=tx.execute(
                "SELECT count(*) n FROM research_batches.batches"
            ).fetchone()["n"],
        )
        if not apply:
            return report
        tx.execute(
            "ALTER TABLE research_batches.task_attempts "
            "ADD COLUMN live_completed_sessions integer, ADD COLUMN live_total_sessions integer"
        )
        for table in _TABLES:
            # CHECK bodies are parsed by PostgreSQL, not reconstructed from a
            # second handwritten constraint definition.
            ddl = _table_ddl(target, table)
            checks = re.findall(
                r"CONSTRAINT (\w+) CHECK \([\s\S]+?"
                r"(?=,\n    (?:CONSTRAINT|UNIQUE|FOREIGN|PRIMARY)|\n\);)",
                ddl,
            )
            for name in re.findall(r"CONSTRAINT (\w+) CHECK", _table_ddl(source, table)):
                tx.execute(f"ALTER TABLE research_batches.{table} DROP CONSTRAINT {name}")
            for name in checks:
                start = ddl.index(f"CONSTRAINT {name} CHECK")
                end = re.search(r",\n    (?:CONSTRAINT|UNIQUE|FOREIGN|PRIMARY)|\n\);", ddl[start:])
                if end is None:
                    raise ValueError("Migration constraint definition is incomplete")
                tx.execute(
                    f"ALTER TABLE research_batches.{table} ADD {ddl[start : start + end.start()]}"
                )
        tx.execute("DROP INDEX research_batches.research_batch_task_attempts_running_idx")
        for statement in _index_ddl(target, "task_attempts"):
            tx.execute(statement)
        _verify_structure(tx, target)
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text NOT NULL, target_fingerprint text NOT NULL, "
            "updated_rows integer NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id,source_fingerprint,target_fingerprint,updated_rows) VALUES (%s,%s,%s,0)",
            (MIGRATION, SOURCE, TARGET),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint=%s WHERE singleton", (TARGET,)
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-backup", type=Path)
    args = parser.parse_args()
    if args.apply and (
        args.database_backup is None
        or not args.database_backup.is_file()
        or args.database_backup.stat().st_size == 0
    ):
        parser.error("Provide a verified PostgreSQL backup with --database-backup before --apply")
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(migrate(database, apply=args.apply)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
