"""Backfill strategy filter metrics from immutable published results."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from importlib.resources import files

import boto3
from psycopg.types.json import Jsonb

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
from thesistrace.publication import Publication, PublishedRef
from thesistrace.research_run.models import FactorEvaluationResearchRunKeyMetrics

SOURCE = "0a00180015bde4a1701eb9fb9e1c4b85c09d308a86ef67ca544759e1f8c2e89e"
TARGET = "c11a7990cddff9a0346faca65d8f69dab299a615c02539ca8b2b45c4d28a5e48"
MIGRATION = "0001_strategy_rank_ic"


def migrate(
    database: PostgresDatabase, load_metrics: Callable[[dict], dict], *, apply: bool = False
) -> dict:
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '60s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        tx.execute("LOCK TABLE research_runs.runs IN SHARE ROW EXCLUSIVE MODE")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        version = "source" if current == SOURCE else "target"
        clause = files(__package__).joinpath(f"0001_{version}.sql").read_text()
        tx.execute(
            "CREATE TEMP TABLE migration_expected (key_metrics jsonb, "
            f"immutable_input jsonb, {clause}) ON COMMIT DROP"
        )
        definitions = tx.execute("""
            SELECT pg_get_constraintdef(oid) AS definition, convalidated
            FROM pg_constraint WHERE conname = 'runs_key_metrics_check'
              AND conrelid IN ('research_runs.runs'::regclass,
                               'pg_temp.migration_expected'::regclass)
        """).fetchall()
        if len(definitions) != 2 or definitions[0] != definitions[1]:
            raise ValueError("Actual metric constraint differs from the declared schema")
        if current == TARGET:
            return {"migration": MIGRATION, "status": "already_current", "updated": 0}
        rows = tx.execute("""
            SELECT id, key_metrics, result_manifest_sha256, result_provenance
            FROM research_runs.runs
            WHERE immutable_input->>'research_kind' = 'strategy_backtest'
              AND key_metrics IS NOT NULL ORDER BY id
        """).fetchall()
        changes = []
        for row in rows:
            metrics = FactorEvaluationResearchRunKeyMetrics.model_validate(
                {
                    "research_kind": "factor_evaluation",
                    **load_metrics(row),
                }
            ).model_dump(exclude={"research_kind"})
            changes.append((Jsonb({**row["key_metrics"], **metrics}), row["id"]))
        report = {
            "migration": MIGRATION,
            "source": SOURCE,
            "target": TARGET,
            "updated": len(changes),
            "status": "applied" if apply else "validated",
        }
        if not apply:
            return report
        tx.execute("ALTER TABLE research_runs.runs DROP CONSTRAINT runs_key_metrics_check")
        for parameters in changes:
            tx.execute("UPDATE research_runs.runs SET key_metrics = %s WHERE id = %s", parameters)
        target = files(__package__).joinpath("0001_target.sql").read_text()
        tx.execute(f"ALTER TABLE research_runs.runs ADD {target}")
        tx.execute("""CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history (
            id text PRIMARY KEY, source_fingerprint text NOT NULL,
            target_fingerprint text NOT NULL, updated_rows integer NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())""")
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id, source_fingerprint, target_fingerprint, updated_rows) "
            "VALUES (%s, %s, %s, %s)",
            (MIGRATION, SOURCE, TARGET, len(changes)),
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
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )
        publication = Publication(database, s3, bucket=settings.s3_bucket)

        def load_metrics(row: dict) -> dict:
            bundle = publication.read(
                PublishedRef(
                    manifest_sha256=row["result_manifest_sha256"],
                    kind="research.result",
                    provenance=row["result_provenance"],
                )
            )
            horizons = json.loads(bundle.payloads["factor_summary"].content)["horizons"]
            return {
                f"{name}_session_rank_ic": horizons[horizon]["summary"]["rank_ic"]["mean"]
                for name, horizon in (("one", "1"), ("five", "5"), ("twenty", "20"))
            }

        print(json.dumps(migrate(database, load_metrics, apply=args.apply)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
