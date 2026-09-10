"""Explicit, reversible creation of durable Publication maintenance state."""

from __future__ import annotations

import argparse
import json
import os
from importlib.resources import files
from uuid import uuid4

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS

SOURCE = "c11a7990cddff9a0346faca65d8f69dab299a615c02539ca8b2b45c4d28a5e48"
TARGET = "6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f"
MIGRATION = "0002_publication_maintenance"
_TABLE = "publication.maintenance_state"


def _shape(tx, table):
    columns = tx.execute(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid) AS default_value "
        "FROM pg_attribute a LEFT JOIN pg_attrdef d "
        "ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
        (table,),
    ).fetchall()
    constraints = tx.execute(
        "SELECT pg_get_constraintdef(oid) AS definition, convalidated "
        "FROM pg_constraint WHERE conrelid = %s::regclass ORDER BY pg_get_constraintdef(oid)",
        (table,),
    ).fetchall()
    return columns, constraints


def migrate(database: PostgresDatabase, *, apply: bool = False, reverse: bool = False) -> dict:
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    ddl = files(__package__).joinpath("0002_publication_maintenance.sql").read_text()
    expected_ddl = (
        ddl.split("INSERT INTO")[0]
        .strip()
        .removesuffix(";")
        .replace(
            "CREATE TABLE publication.maintenance_state", "CREATE TEMP TABLE maintenance_expected"
        )
        + " ON COMMIT DROP"
    )
    source, target = (TARGET, SOURCE) if reverse else (SOURCE, TARGET)
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '30s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        if not tx.execute(
            "SELECT pg_try_advisory_xact_lock("
            "hashtext('thesistrace-publication-maintenance')) AS acquired"
        ).fetchone()["acquired"]:
            raise ValueError("Stop Publication maintenance before migrating")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        tx.execute(expected_ddl)
        present = tx.execute("SELECT to_regclass(%s) AS name", (_TABLE,)).fetchone()["name"]
        if current == SOURCE:
            if present is not None:
                raise ValueError("Unexpected maintenance table in source schema")
        else:
            if present is None or _shape(tx, _TABLE) != _shape(tx, "pg_temp.maintenance_expected"):
                raise ValueError("Maintenance table differs from declared target structure")
            jobs = {r["job"] for r in tx.execute("SELECT job FROM publication.maintenance_state")}
            if jobs != {"orphan_scan", "queued_deletions"}:
                raise ValueError("Maintenance job records are incomplete")
        if current == target:
            return {"migration": MIGRATION, "status": "already_current", "updated": 0}
        report = {
            "migration": MIGRATION,
            "source": source,
            "target": target,
            "direction": "reverse" if reverse else "forward",
            "updated": 2,
            "status": "applied" if apply else "validated",
        }
        if not apply:
            return report
        if reverse:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS thesistrace_meta.maintenance_rollback_archive ("
                "id text PRIMARY KEY, archived_at timestamptz NOT NULL DEFAULT now(), "
                "state jsonb NOT NULL)"
            )
            tx.execute(
                "INSERT INTO thesistrace_meta.maintenance_rollback_archive(id, state) "
                "SELECT %s, jsonb_agg(to_jsonb(s) ORDER BY job) "
                "FROM publication.maintenance_state s",
                (str(uuid4()),),
            )
            tx.execute("DROP TABLE publication.maintenance_state")
        else:
            tx.execute(ddl)
            if _shape(tx, _TABLE) != _shape(tx, "pg_temp.maintenance_expected"):
                raise ValueError("Created maintenance table does not match target")
            if tx.execute("SELECT 1 FROM pg_roles WHERE rolname = 'core_runtime'").fetchone():
                tx.execute(
                    "GRANT SELECT, INSERT, UPDATE, DELETE "
                    "ON publication.maintenance_state TO core_runtime"
                )
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history ("
            "id text PRIMARY KEY, source_fingerprint text NOT NULL, "
            "target_fingerprint text NOT NULL, updated_rows integer NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id, source_fingerprint, target_fingerprint, updated_rows) VALUES (%s, %s, %s, 2)",
            (f"{MIGRATION}:{report['direction']}:{uuid4()}", source, target),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint = %s WHERE singleton",
            (target,),
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after backup and stopping writers"
    )
    parser.add_argument(
        "--reverse", action="store_true", help="Archive state and restore source schema"
    )
    arguments = parser.parse_args()
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(migrate(database, apply=arguments.apply, reverse=arguments.reverse)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
