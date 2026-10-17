"""Explicit, data-preserving research quota and tracking selection upgrade."""

from __future__ import annotations

import argparse
import json
import os
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from psycopg import sql

from thesistrace._postgres import PostgresDatabase, SchemaDefinition
from thesistrace._postgres.schema import _fingerprint
from thesistrace.migrations.financial_indicator import _shape

SOURCE = "a40cd7fedf6025c2c2f1ac096a26cbe60ab4c85a868d49f0cf9f087f697408e0"
TARGET = "702d259e8393f789b1ac8a04e6192d443ccd56a46647e02a238b1ea0220e762e"
MIGRATION = "0011_billing_quotas"


def release_schemas(name: str) -> tuple[SchemaDefinition, ...]:
    with ZipFile(BytesIO(files(__package__).joinpath(name).read_bytes())) as archive:
        return tuple(
            SchemaDefinition(name=n.removesuffix(".sql"), statement=archive.read(n).decode())
            for n in archive.namelist()
        )


def _verify_structure(tx, definitions):
    prefixes = {
        name: f"billing_migration_{uuid4().hex}" for name in ("research_runs", "daily_tracks")
    }

    def normalized(value):
        result = str(value)
        for original, temporary in prefixes.items():
            result = result.replace(temporary, original)
        return result

    for definition in definitions:
        if definition.name not in prefixes:
            continue
        statement = definition.statement.replace(
            "CREATE EXTENSION pg_trgm WITH SCHEMA research_runs;", ""
        )
        for name, temporary in prefixes.items():
            statement = statement.replace(
                f"CREATE SCHEMA {name};", f"CREATE SCHEMA {temporary};"
            ).replace(name + ".", temporary + ".")
        statement = statement.replace(
            prefixes["research_runs"] + ".gin_trgm_ops", "research_runs.gin_trgm_ops"
        )
        tx.execute(statement)
    for schema, table in (
        ("research_runs", "run_ownership"),
        ("research_runs", "runs"),
        ("daily_tracks", "tracks"),
    ):
        if normalized(_shape(tx, f"{schema}.{table}")) != normalized(
            _shape(tx, f"{prefixes[schema]}.{table}")
        ):
            raise ValueError(f"Billing migration structure differs: {schema}.{table}")

    def triggers(schema):
        return tx.execute(
            "SELECT pg_get_triggerdef(oid) definition FROM pg_trigger WHERE "
            "tgrelid=%s::regclass AND NOT tgisinternal ORDER BY tgname",
            (schema + ".runs",),
        ).fetchall()

    if normalized(triggers("research_runs")) != normalized(triggers(prefixes["research_runs"])):
        raise ValueError("Billing quota triggers differ")

    def function(schema):
        return tx.execute(
            "SELECT pg_get_functiondef(p.oid) definition FROM pg_proc p JOIN "
            "pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s AND "
            "p.proname='settle_run_quota'",
            (schema,),
        ).fetchall()

    if normalized(function("research_runs")) != normalized(function(prefixes["research_runs"])):
        raise ValueError("Billing quota function differs")
    for temporary in reversed(tuple(prefixes.values())):
        tx.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(temporary)))


def migrate(database: PostgresDatabase, *, apply: bool = False) -> dict:
    source, target = release_schemas("0011-source.zip"), release_schemas("0011-target.zip")
    if _fingerprint(source) != SOURCE or _fingerprint(target) != TARGET:
        raise ValueError("Billing migration release assets differ")
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout='5s'")
        tx.execute("SET LOCAL statement_timeout='120s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        if tx.execute("SELECT current_user name").fetchone()["name"] != "thesistrace_owner":
            raise ValueError("Owner maintenance required")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported Billing migration source")
        tx.execute(
            "LOCK TABLE research_runs.runs, research_runs.run_ownership, "
            "daily_tracks.tracks IN ACCESS EXCLUSIVE MODE"
        )
        _verify_structure(tx, target if current == TARGET else source)
        counts = tx.execute(
            "SELECT (SELECT count(*) FROM research_runs.run_ownership) runs, "
            "(SELECT count(*) FROM daily_tracks.tracks) tracks"
        ).fetchone()
        report = dict(
            migration=MIGRATION,
            source=SOURCE,
            target=TARGET,
            preserved_runs=counts["runs"],
            preserved_tracks=counts["tracks"],
        )
        if current == TARGET:
            return dict(report, status="already_current")
        if not apply:
            return dict(report, status="validated")
        tx.execute(files(__package__).joinpath("0011-billing.sql").read_text())
        _verify_structure(tx, target)
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history (id"
            " text PRIMARY KEY, source_fingerprint text NOT NULL, "
            "target_fingerprint text NOT NULL, updated_rows integer NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO "
            "thesistrace_meta.migration_history(id,source_fingerprint,target_fingerprint,updated_rows)"
            " VALUES (%s,%s,%s,%s)",
            (MIGRATION, SOURCE, TARGET, counts["runs"] + counts["tracks"]),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint=%s WHERE singleton", (TARGET,)
        )
        return dict(report, status="applied")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-backup", type=Path)
    args = parser.parse_args()
    if args.apply and (
        args.database_backup is None
        or not args.database_backup.is_file()
        or args.database_backup.stat().st_size == 0
    ):
        parser.error("Provide a verified PostgreSQL backup before --apply")
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(migrate(database, apply=args.apply)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
