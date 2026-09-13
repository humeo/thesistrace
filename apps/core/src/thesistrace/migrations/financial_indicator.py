"""Explicit data-preserving financial indicator ledger upgrade."""

from __future__ import annotations

import argparse
import json
import os
import re
from uuid import uuid4

from psycopg import sql

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS

SOURCE = "6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f"
TARGET = "624c319e2f0a11425c5a5219d8125a10234c6885ae66531df57cd384e589a693"
UPGRADE = "financial_indicator_226"
_OPERATIONS = "financial_daily_refresh_operations"
_TABLES = (
    "financial_indicator_report_targets",
    "financial_indicator_reconciliation",
    "financial_indicator_collections",
)
_ADDED_COLUMNS = (
    "    indicator_collection jsonb,\n"
    "    indicator_candidate_manifest_sha256 text\n"
    "        CHECK (indicator_candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'),\n"
)


def _table_ddl(name: str) -> str:
    statement = next(d.statement for d in CORE_SCHEMA_DEFINITIONS if d.name == "data")
    match = re.search(rf"^CREATE TABLE data\.{re.escape(name)} \([\s\S]+?^\);", statement, re.M)
    if match is None:
        raise ValueError("Declared target table is missing")
    return match.group()


def _shape(tx, table: str):
    columns = tx.execute(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid) AS default_value "
        "FROM pg_attribute a LEFT JOIN pg_attrdef d "
        "ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attname",
        (table,),
    ).fetchall()
    constraints = tx.execute(
        "SELECT pg_get_constraintdef(oid) AS definition, convalidated "
        "FROM pg_constraint WHERE conrelid = %s::regclass",
        (table,),
    ).fetchall()
    return columns, sorted(
        (row["definition"].replace("data.", "").replace("pg_temp.", ""), row["convalidated"])
        for row in constraints
    )


def _verify_structure(tx, *, target: bool) -> None:
    for name in (_OPERATIONS, *_TABLES):
        present = tx.execute("SELECT to_regclass(%s) AS name", (f"data.{name}",)).fetchone()["name"]
        if not target and name in _TABLES:
            if present is not None:
                raise ValueError("Unexpected indicator table in source structure")
        elif present is None or _shape(tx, f"data.{name}") != _shape(tx, f"pg_temp.{name}"):
            raise ValueError(f"Table structure differs from declared contract: data.{name}")


def upgrade(database: PostgresDatabase, *, apply: bool = False) -> dict:
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Upgrade target does not match this checkout")
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '30s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported upgrade source fingerprint")
        for name in (_OPERATIONS, *_TABLES):
            ddl = _table_ddl(name)
            if current == SOURCE and name == _OPERATIONS:
                if _ADDED_COLUMNS not in ddl:
                    raise ValueError("Declared column change is missing")
                ddl = ddl.replace(_ADDED_COLUMNS, "")
            tx.execute(
                ddl.replace("CREATE TABLE data.", "CREATE TEMP TABLE ")
                .replace("REFERENCES data.", "REFERENCES pg_temp.")
                .removesuffix(";")
                + " ON COMMIT DROP"
            )
        _verify_structure(tx, target=current == TARGET)
        if current == TARGET:
            return {"upgrade": UPGRADE, "status": "already_current", "updated_rows": 0}
        report = {
            "upgrade": UPGRADE,
            "source": SOURCE,
            "target": TARGET,
            "status": "applied" if apply else "validated",
            "updated_rows": 0,
        }
        if not apply:
            return report
        for schema in ("data", "pg_temp"):
            tx.execute(
                sql.SQL(
                    "ALTER TABLE {}.financial_daily_refresh_operations "
                    "ADD COLUMN indicator_collection jsonb, "
                    "ADD COLUMN indicator_candidate_manifest_sha256 text "
                    "CHECK (indicator_candidate_manifest_sha256 ~ '^[0-9a-f]{{64}}$')"
                ).format(sql.Identifier(schema))
            )
        for name in _TABLES:
            tx.execute(_table_ddl(name))
        _verify_structure(tx, target=True)
        if tx.execute("SELECT 1 FROM pg_roles WHERE rolname = 'core_runtime'").fetchone():
            for name in _TABLES:
                tx.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON data.{} TO core_runtime"
                    ).format(sql.Identifier(name))
                )
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history ("
            "id text PRIMARY KEY, source_fingerprint text NOT NULL, "
            "target_fingerprint text NOT NULL, updated_rows integer NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id, source_fingerprint, target_fingerprint, updated_rows) VALUES (%s, %s, %s, 0)",
            (f"{UPGRADE}:{uuid4()}", SOURCE, TARGET),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint = %s WHERE singleton",
            (TARGET,),
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after backup and stopping writers"
    )
    args = parser.parse_args()
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(upgrade(database, apply=args.apply)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
