"""Explicit, data-preserving upgrade for indexed Research Run search."""

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
from thesistrace._postgres.schema import _fingerprint
from thesistrace.migrations.billing_0011 import release_schemas
from thesistrace.migrations.financial_indicator import _shape

SOURCE = "d6ee5f41c2c3c9fa8a49d5adf530eb4e98c9f9c8cb3fd5fff1408a1a157115a9"
TARGET = "a40cd7fedf6025c2c2f1ac096a26cbe60ab4c85a868d49f0cf9f087f697408e0"
MIGRATION = "0010_research_search"
_EXTENSION = "CREATE EXTENSION pg_trgm WITH SCHEMA research_runs;"


def _catalog(tx, schema):
    table = f"{schema}.runs"
    columns, constraints = _shape(tx, table)
    generated = tx.execute(
        "SELECT attname, attgenerated FROM pg_attribute "
        "WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped ORDER BY attname",
        (table,),
    ).fetchall()
    indexes = tx.execute(
        "SELECT pg_get_indexdef(indexrelid) AS definition, indisvalid, indisready "
        "FROM pg_index WHERE indrelid=%s::regclass ORDER BY pg_get_indexdef(indexrelid)",
        (table,),
    ).fetchall()
    return (
        columns,
        [(definition.replace(schema + ".", "research_runs."), valid)
         for definition, valid in constraints],
        generated,
        [{**row, "definition": row["definition"].replace(schema + ".", "research_runs.")}
         for row in indexes],
    )


def _verify_structure(tx, statement, *, target):
    if target and tx.execute(
        "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
        "WHERE e.extname='pg_trgm'"
    ).fetchone() != {"nspname": "research_runs"}:
        raise ValueError("Search extension differs from declared contract")
    expected = "migration_0010_" + uuid4().hex
    # PostgreSQL parses both complete table definitions. The transaction-local
    # schema includes ownership FKs, generated expressions and valid index flags.
    tx.execute(
        statement.replace(_EXTENSION, "")
        .replace("CREATE SCHEMA research_runs;", f"CREATE SCHEMA {expected};")
        .replace("research_runs.", expected + ".")
        .replace(expected + ".gin_trgm_ops", "research_runs.gin_trgm_ops")
    )
    if _catalog(tx, "research_runs") != _catalog(tx, expected):
        raise ValueError("Research Run structure differs from declared contract")
    tx.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(expected)))


def migrate(database: PostgresDatabase, *, apply: bool = False) -> dict:
    definitions = release_schemas("0011-source.zip")
    if _fingerprint(definitions) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    source = files(__package__).joinpath("0010_source_research_run.sql").read_text()
    target = next(d.statement for d in definitions if d.name == "research_runs")
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '120s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        tx.execute("LOCK TABLE research_runs.runs IN ACCESS EXCLUSIVE MODE")
        _verify_structure(tx, target if current == TARGET else source, target=current == TARGET)
        report = dict(migration=MIGRATION, source=SOURCE, target=TARGET, updated=0)
        if current == TARGET:
            return dict(report, status="already_current")
        count = tx.execute("SELECT count(*) n FROM research_runs.runs").fetchone()["n"]
        if not apply:
            return dict(report, status="validated", preserved_runs=count)
        tx.execute(_EXTENSION)
        additions = []
        for column in ("search_notes", "search_formula"):
            definition = re.search(rf"^    {column} text .+ STORED,", target, re.M)
            if definition is None:
                raise ValueError("Declared search column is missing")
            additions.append("ADD COLUMN " + definition[0].strip()[:-1])
        tx.execute("ALTER TABLE research_runs.runs " + ", ".join(additions))
        index = re.search(r"CREATE INDEX research_runs_search_idx[\s\S]+?;", target)
        if index is None:
            raise ValueError("Declared search index is missing")
        tx.execute(index[0])
        _verify_structure(tx, target, target=True)
        tx.execute("ANALYZE research_runs.runs")
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text NOT NULL, target_fingerprint text NOT NULL, "
            "updated_rows integer NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id,source_fingerprint,target_fingerprint,updated_rows) VALUES (%s,%s,%s,%s)",
            (MIGRATION, SOURCE, TARGET, count),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint=%s WHERE singleton", (TARGET,)
        )
        return dict(report, status="applied", updated=count, preserved_runs=count)


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
