"""Explicit diagnostic retention upgrade; preserves immutable identities and bytes."""

from __future__ import annotations

import argparse
import json
import os
from importlib.resources import files
from uuid import uuid4

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
from thesistrace.publication.service import (
    _load_manifest,
    _manifest_objects,
    _object_descriptor,
    lock_publication_mutation,
)

SOURCE = "1dd7bce497ec4421c87f37be66c0defc63f433d7d836e6affb1a925fa6e5b05f"
TARGET = "1bb894bbece0ade8cb122d4054be492fb26ef56d1d9e85237a002f195e386a4f"
MIGRATION = "0003_payload_retention"
EVENT_SECTIONS = frozenset({
    "strategy_targets", "strategy_orders", "strategy_child_orders", "strategy_fills",
    "strategy_adjustments", "strategy_execution_constraints",
})


def _shape(tx, schema):
    columns = tx.execute(
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) AS type, "
        "a.attnotnull, pg_get_expr(d.adbin, d.adrelid) AS default_value "
        "FROM pg_class c JOIN pg_namespace n ON c.relnamespace = n.oid "
        "JOIN pg_attribute a ON a.attrelid = c.oid "
        "LEFT JOIN pg_attrdef d ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "WHERE n.nspname = %s AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY c.relname, a.attnum",
        (schema,),
    ).fetchall()
    constraints = tx.execute(
        "SELECT c.relname, pg_get_constraintdef(k.oid) AS definition, k.convalidated "
        "FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
        "JOIN pg_namespace n ON c.relnamespace = n.oid WHERE n.nspname = %s "
        "ORDER BY c.relname, k.conname",
        (schema,),
    ).fetchall()
    return json.dumps([columns, constraints], sort_keys=True).replace(schema + ".", "publication.")


def migrate(database, *, apply=False):
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    source_ddl = files(__package__).joinpath("0003_source_publication.sql").read_text()
    ddl = files(__package__).joinpath("0003_payload_retention.sql").read_text()
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SET LOCAL statement_timeout = '60s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        lock_publication_mutation(tx)
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        expected = "retention_expected_" + uuid4().hex
        expected_ddl = source_ddl + (ddl if current == TARGET else "")
        tx.execute(expected_ddl.replace("publication", expected))
        if _shape(tx, "publication") != _shape(tx, expected):
            raise ValueError("Publication schema differs from declared migration contract")
        tx.execute(f"DROP SCHEMA {expected} CASCADE")
        if current == TARGET:
            return {"migration": MIGRATION, "status": "already_current", "updated": 0}
        units = []
        for row in tx.execute(
            "SELECT sha256, kind, manifest_bytes, created_at FROM publication.manifests "
            "WHERE kind IN ('research.result', 'daily-track.checkpoint') ORDER BY sha256"
        ).fetchall():
            manifest = _load_manifest(bytes(row["manifest_bytes"]), row["sha256"])
            objects = _manifest_objects(manifest)
            inventory = {str(item["name"]) for item in objects}
            present = inventory & EVENT_SECTIONS
            if present and not EVENT_SECTIONS - {"strategy_execution_constraints"} <= present:
                raise ValueError("Source trading event inventory is incomplete")
            names = {name for name in inventory if name.split(".part-")[0] in EVENT_SECTIONS}
            if any(name.split(".part-")[0] not in present for name in names):
                raise ValueError("Source trading event descriptor is missing")
            if not names:
                continue
            links = tx.execute(
                "SELECT mo.ordinal, mo.logical_name, mo.object_sha256, o.byte_size "
                "FROM publication.manifest_objects mo JOIN publication.objects o "
                "ON o.sha256 = mo.object_sha256 WHERE mo.manifest_sha256 = %s ORDER BY ordinal",
                (row["sha256"],),
            ).fetchall()
            expected_links = []
            for ordinal, obj in enumerate(objects):
                name, digest, size, *_ = _object_descriptor(obj)
                expected_links.append(
                    dict(ordinal=ordinal, logical_name=name, object_sha256=digest, byte_size=size)
                )
            if links != expected_links or manifest["kind"] != row["kind"]:
                raise ValueError("Source publication inventory is invalid")
            units.append((row["sha256"], sorted(names), row["created_at"]))
        report = dict(
            migration=MIGRATION,
            source=SOURCE,
            target=TARGET,
            status="applied" if apply else "validated",
            updated=len(units),
        )
        if not apply:
            return report
        tx.execute(ddl)
        for sha, names, created in units:
            tx.execute(
                "INSERT INTO publication.payload_retention "
                "(manifest_sha256, payload_names, published_at, expires_at) "
                "VALUES (%s, %s, %s, %s + interval '7 days')",
                (sha, names, created, created),
            )
        if tx.execute("SELECT 1 FROM pg_roles WHERE rolname = 'core_runtime'").fetchone():
            tx.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON publication.payload_retention, "
                "publication.expired_payloads TO core_runtime"
            )
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history ("
            "id text PRIMARY KEY, source_fingerprint text NOT NULL, "
            "target_fingerprint text NOT NULL, "
            "updated_rows integer NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id, source_fingerprint, target_fingerprint, updated_rows) VALUES (%s, %s, %s, %s)",
            (MIGRATION, SOURCE, TARGET, len(units)),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint = %s WHERE singleton",
            (TARGET,),
        )
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        print(json.dumps(migrate(database, apply=args.apply)))
    finally:
        database.close()


if __name__ == "__main__":
    main()
