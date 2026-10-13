"""Explicit data-preserving upgrade to measured ResearchRun execution time."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from thesistrace._postgres import PostgresDatabase
from thesistrace.migrations.financial_indicator import _shape

SOURCE = "423422281705fa7018c712268141c15fc58de13de7d1b46523a449e84a66c00d"
TARGET = "d6ee5f41c2c3c9fa8a49d5adf530eb4e98c9f9c8cb3fd5fff1408a1a157115a9"
MIGRATION = "0009_execution_timing"
TABLES = {
    "ordinary_attempt": "research_runs.attempts",
    "batch_task": "research_batches.task_attempts",
}


def _verify_structure(tx, *, target: bool) -> None:
    expected = "migration_0009_" + uuid4().hex
    tx.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(expected)))
    for table in TABLES.values():
        schema, name = table.split(".")
        statement = (
            files(__package__).joinpath("0009_target_execution_tables.sql").read_text()
            if target
            else files(__package__).joinpath(f"0009_source_{schema}.sql").read_text()
        )
        match = re.search(rf"^CREATE TABLE {schema}\.{name} \([\s\S]+?^\);", statement, re.M)
        if match is None:
            raise ValueError("Declared migration table is missing")
        tx.execute(
            match.group().replace(f"CREATE TABLE {table}", f"CREATE TABLE {expected}.{name}", 1)
        )
        for constraint in re.findall(
            rf"^ALTER TABLE ONLY {re.escape(table)}\s[\s\S]+?;", statement, re.M
        ):
            tx.execute(
                constraint.replace(f"ALTER TABLE ONLY {table}", f"ALTER TABLE {expected}.{name}", 1)
            )
        if _shape(tx, table) != _shape(tx, f"{expected}.{name}"):
            raise ValueError(f"Execution timing table differs from declared contract: {table}")
    tx.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(expected)))


def read_measurements(path: Path | None) -> tuple[dict, ...]:
    if path is None:
        return ()
    document = json.loads(path.read_text())
    if (
        document.get("schema_version") != "research-execution-measurements-v1"
        or document.get("source_schema_fingerprint") != SOURCE
        or set(document) != {"schema_version", "source_schema_fingerprint", "measurements"}
    ):
        raise ValueError("Execution measurement evidence contract is invalid")
    measurements = document["measurements"]
    if not isinstance(measurements, list):
        raise ValueError("Execution measurements must be a list")
    seen = set()
    for row in measurements:
        if not isinstance(row, dict) or set(row) != {
            "owner",
            "attempt_id",
            "processing_seconds",
            "chunk_ordinal",
        }:
            raise ValueError("Execution measurement row is invalid")
        owner, attempt = row["owner"], row["attempt_id"]
        seconds, ordinal = row["processing_seconds"], row["chunk_ordinal"]
        if (
            owner not in TABLES
            or not isinstance(attempt, str)
            or not attempt
            or type(seconds) not in {int, float}
            or not math.isfinite(seconds)
            or seconds < 0
            or type(ordinal) is not int
            or ordinal < 0
            or (owner == "batch_task" and ordinal != 0)
            or (owner, attempt) in seen
        ):
            raise ValueError("Execution measurement values are invalid or duplicated")
        seen.add((owner, attempt))
    return tuple(measurements)


def _backfill(tx, measurements, *, apply: bool, target: bool) -> int:
    updated = 0
    for row in measurements:
        table = TABLES[row["owner"]]
        current = tx.execute(
            sql.SQL("SELECT status{} FROM {} WHERE id=%s FOR UPDATE").format(
                sql.SQL(", processing_seconds" if target else ""),
                sql.Identifier(*table.split(".")),
            ),
            (row["attempt_id"],),
        ).fetchone()
        if current is None or current["status"] not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("Execution measurement must reference a terminal known Attempt")
        measured = current.get("processing_seconds")
        if measured is not None:
            if not math.isclose(float(measured), row["processing_seconds"], abs_tol=1e-9):
                raise ValueError("Execution measurement conflicts with persisted evidence")
            continue
        updated += 1
        if apply:
            assignment = "processing_seconds=%s"
            values = [float(row["processing_seconds"])]
            if row["owner"] == "ordinary_attempt":
                assignment += ", processing_chunk_ordinal=%s"
                values.append(row["chunk_ordinal"])
            tx.execute(
                sql.SQL("UPDATE {} SET " + assignment + " WHERE id=%s").format(
                    sql.Identifier(*table.split(".")),
                ),
                (*values, row["attempt_id"]),
            )
    return updated


def migrate(database: PostgresDatabase, *, apply: bool = False, measurements=()) -> dict:
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout='5s'")
        tx.execute("SET LOCAL statement_timeout='60s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported execution timing migration source")
        tx.execute(
            "LOCK TABLE research_runs.attempts, research_batches.task_attempts "
            "IN ACCESS EXCLUSIVE MODE"
        )
        _verify_structure(tx, target=current == TARGET)
        if tx.execute(
            "SELECT 1 FROM research_runs.attempts WHERE status IN ('running','cancelling') "
            "UNION ALL SELECT 1 FROM research_batches.attempts WHERE status='running' "
            "UNION ALL SELECT 1 FROM research_batches.starting_claims LIMIT 1"
        ).fetchone():
            raise ValueError("Drain active research and stop writers before upgrading")
        report = {
            "migration": MIGRATION,
            "source": SOURCE,
            "target": TARGET,
            "status": "applied" if apply else "validated",
            "backfilled": 0,
        }
        if current == TARGET:
            report["status"] = "already_current"
            report["backfilled"] = _backfill(tx, measurements, apply=apply, target=True)
            return report
        if not apply:
            report["backfilled"] = _backfill(tx, measurements, apply=False, target=False)
            return report
        tx.execute(
            "ALTER TABLE research_runs.attempts ADD COLUMN processing_seconds double precision, "
            "ADD COLUMN processing_chunk_ordinal integer DEFAULT 0 NOT NULL, "
            "ADD CONSTRAINT attempts_processing_check CHECK ("
            "(processing_seconds IS NULL OR "
            "(processing_seconds>=0 AND processing_seconds<'Infinity'::float8)) "
            "AND processing_chunk_ordinal>=0)"
        )
        tx.execute(
            "ALTER TABLE research_batches.task_attempts "
            "ADD COLUMN processing_seconds double precision, "
            "ADD CONSTRAINT task_attempts_processing_check CHECK (processing_seconds IS NULL OR "
            "(processing_seconds>=0 AND processing_seconds<'Infinity'::float8))"
        )
        _verify_structure(tx, target=True)
        report["backfilled"] = _backfill(tx, measurements, apply=True, target=True)
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text NOT NULL,target_fingerprint text NOT NULL,"
            "updated_rows integer NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history"
            "(id,source_fingerprint,target_fingerprint,updated_rows) "
            "VALUES (%s,%s,%s,%s)",
            (MIGRATION, SOURCE, TARGET, report["backfilled"]),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint=%s WHERE singleton", (TARGET,)
        )
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-backup", type=Path)
    parser.add_argument("--measurements", type=Path)
    args = parser.parse_args()
    if args.apply and (
        args.database_backup is None
        or not args.database_backup.is_file()
        or args.database_backup.stat().st_size == 0
    ):
        parser.error("Provide a verified PostgreSQL backup with --database-backup before --apply")
    measurements = read_measurements(args.measurements)
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(migrate(database, apply=args.apply, measurements=measurements)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
