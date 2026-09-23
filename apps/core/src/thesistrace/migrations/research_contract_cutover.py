"""Explicit research-contract retirement; never invoked by application startup."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from psycopg import sql
from psycopg.types.json import Jsonb

from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
from thesistrace.migrations.research_cutover_inventory import DEPENDENTS, read_inventory
from thesistrace.publication.service import lock_publication_mutation
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_run.service import SEMANTIC_VERSIONS


def select_scope(
    *,
    runs: Sequence[Mapping],
    tracks: Sequence[Mapping],
    batches: Sequence[Mapping],
    items: Sequence[Mapping],
    source: Mapping[str, str],
    target: Mapping[str, str],
) -> dict[str, list[str]]:
    """Choose exact frozen contracts without validating them as current runtime inputs.

    Deleted Run origins remain independently selectable through a Track's copied input.
    A Batch is indivisible: retirement must not cascade into retained research.
    """
    if (set(source) != {"factor", "strategy", "kernel"} or source == target
            or any(not isinstance(value, str) or not value for value in source.values())):
        raise ValueError("Cutover requires a complete, non-current source contract")
    run_by_id = {row["id"]: row for row in runs}
    batch_by_id = {row["id"]: row for row in batches}
    selected_runs = {
        row["id"] for row in runs if row["immutable_input"].get("semantic_versions") == source
    }
    selected_tracks = set()
    for track in tracks:
        seed = run_by_id.get(track["seed_run_id"])
        if seed is not None and seed["researcher_id"] != track["researcher_id"]:
            raise ValueError("Track/Run ownership does not match")
        selected = track["origin"]["immutable_input"].get("semantic_versions") == source
        if track["seed_run_id"] in selected_runs and not selected:
            raise ValueError("A retained Track still depends on selected research")
        if selected:
            if seed is not None and seed["id"] not in selected_runs:
                raise ValueError("Selected Track and retained seed have inconsistent contracts")
            selected_tracks.add(track["id"])
    selected_batches = set()
    for item in items:
        batch = batch_by_id.get(item["batch_id"])
        run = run_by_id.get(item["research_run_id"])
        if (batch is None or batch["researcher_id"] != item["researcher_id"]
                or (run is not None and run["researcher_id"] != item["researcher_id"])):
            raise ValueError("Batch/Run ownership does not match")
        if item["research_run_id"] in selected_runs:
            selected_batches.add(item["batch_id"])
    for batch in batches:
        # A completed Batch can outlive every deleted item Run.
        if batch.get("scope", {}).get("semantic_versions") == source:
            selected_batches.add(batch["id"])
    for item in items:
        if item["batch_id"] not in selected_batches:
            continue
        run_id = item["research_run_id"]
        if run_id in selected_runs:
            continue
        batch_contract = batch_by_id[item["batch_id"]].get("scope", {}).get("semantic_versions")
        if run_id in run_by_id or batch_contract != source or item.get("run_deleted_at") is None:
            raise ValueError(
                "Selected Batch contains retained research or an unverified deleted Run"
            )
    return {"run_ids": sorted(selected_runs), "track_ids": sorted(selected_tracks),
            "batch_ids": sorted(selected_batches)}


def preview(database, publication, *, source: Mapping[str, str]) -> dict:
    """Read a consistent identity-bound scope; no authority or storage is mutated."""
    with database.transaction() as tx:
        tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _read_preview(tx, source, publication)[0]


def _read_environment(tx, publication):
    schema = tx.execute(
        "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton"
    ).fetchone()["fingerprint"]
    if schema != _fingerprint(CORE_SCHEMA_DEFINITIONS):
        raise ValueError(
            "Cutover requires the declared current schema; migrate explicitly first"
        )
    environment = tx.execute(
        "SELECT current_database() AS database, "
        "(SELECT oid FROM pg_database WHERE datname = current_database()) AS database_oid, "
        "system_identifier::text AS cluster FROM pg_control_system()"
    ).fetchone()
    return schema, {**environment, "publication": publication.storage_identity}


def _read_preview(tx, source, publication):
    schema, environment = _read_environment(tx, publication)
    records = {
        key: [row["record"] for row in tx.execute(query)]
        for key, query in (
            ("runs", "SELECT to_jsonb(r) AS record FROM research_runs.runs r ORDER BY id"),
            ("tracks", "SELECT to_jsonb(t) AS record FROM daily_tracks.tracks t ORDER BY id"),
            ("batches", "SELECT to_jsonb(b) AS record "
                        "FROM research_batches.batches b ORDER BY id"),
            ("items", "SELECT to_jsonb(i) AS record FROM research_batches.items i "
                      "ORDER BY batch_id, ordinal"),
        )
    }
    scope = select_scope(**records, source=source, target=SEMANTIC_VERSIONS)
    selected = {
        key: [row for row in records[key] if row["id"] in scope[id_key]]
        for key, id_key in (("runs", "run_ids"), ("tracks", "track_ids"),
                            ("batches", "batch_ids"))
    }
    selected["items"] = [row for row in records["items"]
                         if row["batch_id"] in scope["batch_ids"]]
    inventory, manifests, objects = read_inventory(tx, scope, selected)
    report = {
        "format": "research-cutover-preview/v1", "status": "preview",
        "environment": dict(environment), "source_schema": schema, "target_schema": schema,
        "source_contract": dict(source), "target_contract": dict(SEMANTIC_VERSIONS),
        "scope": scope, "counts": {key: len(value) for key, value in selected.items()},
        "inventory_counts": {table: len(rows) for table, rows in inventory.items()},
        "manifest_references": manifests, "objects": objects,
        "selected_records_sha256": hashlib.sha256(canonical_json_bytes({
            "rows": inventory, "manifests": manifests, "objects": objects,
        })).hexdigest(),
    }
    return report, inventory


def write_record(path: Path, value: Mapping, *, reuse_identical: bool = False) -> str:
    """Persist new operator evidence before any authority change; never overwrite it."""
    content = canonical_json_bytes(value)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not reuse_identical:
            raise
        with path.open("rb") as stream:
            if stream.read() != content:
                raise ValueError("Existing backup differs from the verified inventory") from None
            os.fsync(stream.fileno())
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return hashlib.sha256(content).hexdigest()


def apply_cutover(database, publication, *, plan: Mapping, backup_path: Path) -> dict:
    """Back up and atomically retire exactly a verified preview; leave bytes queued."""
    identity = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    backup_path = backup_path.absolute()
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout = '5s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        lock_publication_mutation(tx)
        tables = {table for table, _, _ in DEPENDENTS} | {
            "research_runs.runs", "daily_tracks.tracks", "research_batches.batches",
            "research_runs.start_tracking_receipts", "data.generation_pins",
            "publication.holding_units", "publication.manifests", "publication.manifest_objects",
            "publication.objects", "publication.object_deletions", "publication.payload_retention",
            "publication.expired_payloads",
        }
        tx.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
            sql.SQL(", ").join(sql.Identifier(*table.split(".")) for table in sorted(tables))
        ))
        tx.execute("""
            CREATE TABLE IF NOT EXISTS thesistrace_meta.research_cutovers (
                id text PRIMARY KEY, plan jsonb NOT NULL, backup_path text NOT NULL,
                backup_sha256 text NOT NULL, receipt jsonb NOT NULL,
                committed_at timestamptz NOT NULL DEFAULT clock_timestamp()
            )
        """)
        previous = tx.execute("SELECT * FROM thesistrace_meta.research_cutovers WHERE id = %s",
                              (identity,)).fetchone()
        if previous is not None:
            schema, environment = _read_environment(tx, publication)
            if (schema != plan["target_schema"] or environment != plan["environment"]
                    or plan["target_contract"] != SEMANTIC_VERSIONS):
                raise ValueError("Committed cutover environment or target contract changed")
            if (previous["plan"] != plan or previous["backup_path"] != str(backup_path)
                    or hashlib.sha256(backup_path.read_bytes()).hexdigest()
                    != previous["backup_sha256"]):
                raise ValueError("Committed cutover backup does not match its receipt")
            return previous["receipt"]
        actual, inventory = _read_preview(tx, plan["source_contract"], publication)
        if actual != plan:
            raise ValueError("Cutover preview is stale or belongs to another environment")
        if not any(plan["scope"].values()):
            raise ValueError("Cutover preview contains no selected research")
        backup_sha = write_record(backup_path, {"plan": actual, "rows": inventory},
                                  reuse_identical=True)
        scope = actual["scope"]
        # Delete referencing receipts first; keep Run ownership tombstones and Dataset pins.
        tx.execute("DELETE FROM research_runs.start_tracking_receipts "
                   "WHERE seed_run_id = ANY(%s) OR track_id = ANY(%s)",
                   (scope["run_ids"], scope["track_ids"]))
        tx.execute("DELETE FROM publication.holding_units "
                   "WHERE (source_kind = 'research_run' AND source_id = ANY(%s)) "
                   "OR (source_kind = 'daily_track' AND source_id = ANY(%s))",
                   (scope["run_ids"], scope["track_ids"]))
        tx.execute("DELETE FROM daily_tracks.tracks WHERE id = ANY(%s)", (scope["track_ids"],))
        for table in ("admission_receipts", "cancel_receipts", "private_alpha_factor_artifacts"):
            tx.execute(sql.SQL("DELETE FROM research_batches.{} WHERE batch_id = ANY(%s)")
                       .format(sql.Identifier(table)), (scope["batch_ids"],))
        tx.execute("DELETE FROM research_batches.batches WHERE id = ANY(%s)", (scope["batch_ids"],))
        for table in ("admission_requests", "cancel_receipts", "execution_checkpoints", "attempts"):
            tx.execute(sql.SQL("DELETE FROM research_runs.{} WHERE run_id = ANY(%s)")
                       .format(sql.Identifier(table)), (scope["run_ids"],))
        tx.execute("DELETE FROM research_runs.runs WHERE id = ANY(%s)", (scope["run_ids"],))
        for manifest in actual["manifest_references"]:
            publication.release_manifest_in_transaction(
                tx, manifest["sha256"], still_referenced=manifest["retained"],
            )
        receipt = {"id": identity, "status": "committed", "backup_sha256": backup_sha,
                   "scope": scope, "pending_objects": [row["sha256"] for row in actual["objects"]
                                                        if not row["retained"]]}
        tx.execute("INSERT INTO thesistrace_meta.research_cutovers "
                   "(id, plan, backup_path, backup_sha256, receipt) VALUES (%s, %s, %s, %s, %s)",
                   (identity, Jsonb(actual), str(backup_path), backup_sha, Jsonb(receipt)))
        return receipt


def _verified_receipt(tx, cutover_id, publication):
    schema, environment = _read_environment(tx, publication)
    row = tx.execute("SELECT * FROM thesistrace_meta.research_cutovers WHERE id = %s FOR UPDATE",
                     (cutover_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown committed cutover")
    plan = row["plan"]
    if (schema != plan["target_schema"] or environment != plan["environment"]
            or plan["target_contract"] != SEMANTIC_VERSIONS):
        raise ValueError("Committed cutover environment or target contract changed")
    if hashlib.sha256(Path(row["backup_path"]).read_bytes()).hexdigest() != row["backup_sha256"]:
        raise ValueError("Committed cutover backup does not match its receipt")
    return row["receipt"]


def resume_cutover(database, publication, *, cutover_id: str) -> dict:
    """Commit progress per object; a crash retries only this receipt's remaining bytes."""
    while True:
        with database.transaction() as tx:
            tx.execute("SET LOCAL lock_timeout = '5s'")
            tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
            receipt = _verified_receipt(tx, cutover_id, publication)
            if receipt["status"] == "complete":
                return receipt
            lock_publication_mutation(tx)
            pending = receipt["pending_objects"]
            if pending:
                digest = pending[0]
                result = publication.collect_pending_deletion_in_transaction(
                    tx, object_sha256=digest,
                )
                if result is None:
                    # Ordinary maintenance may have finished this exact object already,
                    # or another retained manifest may have acquired it after cutover.
                    referenced = tx.execute("SELECT 1 FROM publication.manifest_objects "
                                            "WHERE object_sha256 = %s LIMIT 1",
                                            (digest,)).fetchone()
                    present = tx.execute("SELECT 1 FROM publication.objects WHERE sha256 = %s",
                                         (digest,)).fetchone()
                    if referenced is not None:
                        result = "retained"
                    elif present is None:
                        result = "already_collected"
                    else:
                        raise ValueError("Cutover object lost its deletion queue entry")
                receipt.setdefault("object_results", {})[digest] = result
                receipt["pending_objects"] = pending[1:]
            receipt["status"] = "collecting" if receipt["pending_objects"] else "complete"
            tx.execute("UPDATE thesistrace_meta.research_cutovers SET receipt = %s WHERE id = %s",
                       (Jsonb(receipt), cutover_id))


def cutover_status(database, publication, *, cutover_id: str) -> dict:
    """Inspect durable progress; an absent receipt means no authority commit occurred."""
    with database.transaction() as tx:
        table = tx.execute(
            "SELECT to_regclass('thesistrace_meta.research_cutovers') AS table_name",
        ).fetchone()["table_name"]
        if table is None or tx.execute(
            "SELECT 1 FROM thesistrace_meta.research_cutovers WHERE id = %s",
            (cutover_id,),
        ).fetchone() is None:
            return {"id": cutover_id, "status": "not_committed"}
        return _verified_receipt(tx, cutover_id, publication)


def main() -> None:
    import argparse
    import json

    import boto3

    from thesistrace._postgres import PostgresDatabase
    from thesistrace.entrypoints.runtime import CoreSettings
    from thesistrace.publication import Publication, publication_request_config

    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser("preview", help="Freeze a read-only scoped inventory")
    inspect.add_argument("--source-contract", required=True, type=Path)
    inspect.add_argument("--output", required=True, type=Path)
    execute = actions.add_parser("apply", help="Back up and commit metadata retirement only")
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--backup", required=True, type=Path)
    for action in ("resume", "status"):
        command = actions.add_parser(action)
        command.add_argument("--id", required=True, dest="cutover_id")
    args = parser.parse_args()
    settings = CoreSettings.from_environment()
    database = PostgresDatabase(settings.database_url)
    database.open()
    s3 = boto3.client(
        "s3", endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region, config=publication_request_config(),
    )
    try:
        publication = Publication(database, s3, bucket=settings.s3_bucket)
        if args.action == "preview":
            source = json.loads(args.source_contract.read_text())
            if not isinstance(source, dict):
                parser.error("Source contract must be a JSON object")
            report = preview(database, publication, source=source)
            digest = write_record(args.output, report)
            result = {"status": "preview", "record": str(args.output), "id": digest,
                      "sha256": digest, "counts": report["counts"]}
        elif args.action == "status":
            result = cutover_status(database, publication, cutover_id=args.cutover_id)
        elif args.action == "apply":
            result = apply_cutover(database, publication,
                                   plan=json.loads(args.plan.read_text()), backup_path=args.backup)
        else:
            result = resume_cutover(database, publication, cutover_id=args.cutover_id)
    finally:
        s3.close()
        database.close()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
