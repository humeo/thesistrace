"""Explicit, data-preserving upgrade for fair Research execution scheduling."""

from __future__ import annotations

import argparse
import json
import os
from importlib.resources import files

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS

SOURCE = "1bb894bbece0ade8cb122d4054be492fb26ef56d1d9e85237a002f195e386a4f"
TARGET = "7243074d627ca77e20ea9d5f10bed2a9ae413ca7db730d3bd37e1ff7ad5369a2"
MIGRATION = "0004_execution_opportunities"
_TABLE = "researchers.execution_opportunities"
_SEQUENCE = "researchers.execution_opportunity_sequence"


def _shape(tx, table):
    columns = tx.execute(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid) AS default_value "
        "FROM pg_attribute a LEFT JOIN pg_attrdef d "
        "ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attnum",
        (table,),
    ).fetchall()
    constraints = tx.execute(
        "SELECT pg_get_constraintdef(oid) AS definition, convalidated "
        "FROM pg_constraint WHERE conrelid = %s::regclass "
        "ORDER BY pg_get_constraintdef(oid)",
        (table,),
    ).fetchall()
    for constraint in constraints:
        constraint["definition"] = constraint["definition"].replace(
            "REFERENCES researchers_expected(", "REFERENCES researchers.researchers("
        )
    return columns, constraints


def _sequence_shape(tx, sequence):
    return tx.execute(
        "SELECT seqtypid::regtype::text, seqstart, seqincrement, seqmax, seqmin, "
        "seqcache, seqcycle FROM pg_sequence WHERE seqrelid = %s::regclass",
        (sequence,),
    ).fetchone()


def migrate(database: PostgresDatabase, *, apply: bool = False) -> dict:
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    ddl = files(__package__).joinpath("0004_execution_opportunities.sql").read_text()
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '30s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        tx.execute(
            "CREATE TEMP TABLE researchers_expected (id uuid PRIMARY KEY, "
            "created_at timestamptz DEFAULT now() NOT NULL, "
            "updated_at timestamptz DEFAULT now() NOT NULL) ON COMMIT DROP"
        )
        if _shape(tx, "researchers.researchers") != _shape(tx, "pg_temp.researchers_expected"):
            raise ValueError("Researcher structure differs from declared source")
        table_present = tx.execute("SELECT to_regclass(%s) t", (_TABLE,)).fetchone()["t"]
        sequence_present = tx.execute("SELECT to_regclass(%s) t", (_SEQUENCE,)).fetchone()["t"]
        if current == SOURCE and (table_present or sequence_present):
            raise ValueError("Unexpected scheduling objects in source schema")
        expected = ddl.split("CREATE TABLE", 1)[1]
        tx.execute(
            ("CREATE TEMP TABLE" + expected)
            .replace(_TABLE, "opportunities_expected")
            .replace("REFERENCES researchers.researchers", "REFERENCES researchers_expected")
            .strip()
            .removesuffix(";")
            + " ON COMMIT DROP"
        )
        tx.execute("CREATE TEMP SEQUENCE opportunities_sequence_expected AS bigint")
        expected_sequence = _sequence_shape(tx, "pg_temp.opportunities_sequence_expected")
        tx.execute("DROP SEQUENCE pg_temp.opportunities_sequence_expected")
        if current == SOURCE and apply:
            tx.execute(ddl)
            table_present, sequence_present = True, True
        if current == TARGET or apply:
            if not table_present or _shape(tx, _TABLE) != _shape(
                tx, "pg_temp.opportunities_expected"
            ):
                raise ValueError("Scheduling table differs from declared target")
            if not sequence_present or _sequence_shape(tx, _SEQUENCE) != expected_sequence:
                raise ValueError("Scheduling sequence differs from declared target")
        if current == TARGET:
            return {"migration": MIGRATION, "status": "already_current", "updated": 0}
        count = tx.execute("SELECT count(*) n FROM researchers.researchers").fetchone()["n"]
        report = {
            "migration": MIGRATION,
            "source": SOURCE,
            "target": TARGET,
            "status": "applied" if apply else "validated",
            "updated": 0,
            "preserved_researchers": count,
        }
        if not apply:
            return report
        if tx.execute("SELECT 1 FROM pg_roles WHERE rolname = 'core_runtime'").fetchone():
            tx.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON researchers.execution_opportunities TO core_runtime"
            )
            tx.execute(
                "GRANT USAGE, SELECT, UPDATE "
                "ON SEQUENCE researchers.execution_opportunity_sequence TO core_runtime"
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
            (MIGRATION, SOURCE, TARGET),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint = %s WHERE singleton",
            (TARGET,),
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after verified backup and stopping writers"
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
