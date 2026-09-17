"""Explicit upgrade to structured disclosure requirements; retain existing data."""

from __future__ import annotations

import argparse
import json
import os
import re
from importlib.resources import files

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
from thesistrace.migrations.financial_indicator import _shape

SOURCE = "7243074d627ca77e20ea9d5f10bed2a9ae413ca7db730d3bd37e1ff7ad5369a2"
TARGET = "5c82cb46665a54816e186fe74105c25ef287cc661e43fcdc8a58e4d94450ee8c"
MIGRATION = "0005_financial_disclosures"
_OPERATION = "financial_daily_refresh_operations"
_ADDED = ("financial_report_targets", "financial_report_rechecks")


def _ddl(statement, table):
    match = re.search(rf"^CREATE TABLE data\.{table} \([\s\S]+?^\);", statement, re.M)
    if match is None:
        raise ValueError("Migration table definition is missing")
    return match.group()


def migrate(database: PostgresDatabase, *, apply: bool = False) -> dict:
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    source = files(__package__).joinpath("0005_source_data.sql").read_text()
    target = next(d.statement for d in CORE_SCHEMA_DEFINITIONS if d.name == "data")
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '60s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        for table in (_OPERATION, *_ADDED):
            present = tx.execute("SELECT to_regclass(%s) t", (f"data.{table}",)).fetchone()["t"]
            if current == SOURCE and table in _ADDED:
                if present is not None:
                    raise ValueError("Unexpected disclosure ledger in source schema")
                continue
            tx.execute(
                _ddl(source if current == SOURCE else target, table)
                .replace("CREATE TABLE data.", "CREATE TEMP TABLE ")
                .removesuffix(";")
                + " ON COMMIT DROP"
            )
            if present is None or _shape(tx, f"data.{table}") != _shape(tx, f"pg_temp.{table}"):
                raise ValueError("Financial schema differs from declared migration contract")
        if current == TARGET:
            return {"migration": MIGRATION, "status": "already_current", "updated": 0}
        if tx.execute(
            "SELECT 1 FROM data.financial_daily_refresh_operations WHERE status='running' LIMIT 1"
        ).fetchone():
            raise ValueError("Drain financial refresh operations before upgrading")
        preserved = tx.execute(
            "SELECT count(*) n FROM data.financial_indicator_report_targets"
        ).fetchone()["n"]
        report = dict(
            migration=MIGRATION,
            source=SOURCE,
            target=TARGET,
            status="applied" if apply else "validated",
            updated=0,
            preserved_announcement_targets=preserved,
        )
        if not apply:
            return report
        tx.execute(
            "ALTER TABLE data.financial_daily_refresh_operations "
            "ADD COLUMN statement_instrument_ids jsonb"
        )
        for table in _ADDED:
            tx.execute(_ddl(target, table))
            if tx.execute("SELECT 1 FROM pg_roles WHERE rolname='core_runtime'").fetchone():
                tx.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON data.{table} TO core_runtime")
        # Historical announcement receipts and all immutable references remain untouched.
        # The first new refresh reconciles the actual catalog against accepted report bytes.
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history ("
            "id text PRIMARY KEY, source_fingerprint text NOT NULL, "
            "target_fingerprint text NOT NULL, updated_rows integer NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id, source_fingerprint, target_fingerprint, updated_rows) VALUES (%s, %s, %s, 0)",
            (MIGRATION, SOURCE, TARGET),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint=%s WHERE singleton", (TARGET,)
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after backup and stopping writers"
    )
    arguments = parser.parse_args()
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(migrate(database, apply=arguments.apply)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
