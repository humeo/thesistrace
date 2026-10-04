"""Explicit, data-preserving upgrade to unified refresh receipts and Dataset Head v2."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
from importlib.resources import files
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.benchmark.snapshot import BENCHMARK_SNAPSHOT_FILENAME, _decode_snapshot
from thesistrace.data.benchmark_snapshot import PreparedBenchmarkSnapshots
from thesistrace.data.generation_files import AddressedFileStore
from thesistrace.data.head_store import (
    MountedDatasetHeadStore,
    _parse_head,
    _pointer_from_manifest,
    _replace_entry,
)
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
from thesistrace.migrations.financial_disclosures_0005 import _ddl
from thesistrace.migrations.financial_indicator import _shape
from thesistrace.publication.serialization import canonical_json_bytes

SOURCE = "5c82cb46665a54816e186fe74105c25ef287cc661e43fcdc8a58e4d94450ee8c"
TARGET = "84827a4b8a6c9bb9d0171e4a7aa42cfefb061216a98295a1e7d784632c237070"
MIGRATION = "0006_unified_refresh"
TABLES = ("refresh_operations", "financial_daily_refresh_operations")


def migrate(database: PostgresDatabase, *, apply: bool = False) -> dict:
    if _fingerprint(CORE_SCHEMA_DEFINITIONS) != TARGET:
        raise ValueError("Migration target does not match this checkout")
    source = files(__package__).joinpath("0006_source_data.sql").read_text()
    target = next(d.statement for d in CORE_SCHEMA_DEFINITIONS if d.name == "data")
    with database.transaction() as tx:
        tx.execute("SET LOCAL lock_timeout='5s'")
        tx.execute("SET LOCAL statement_timeout='60s'")
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('thesistrace-current-schema'))")
        current = tx.execute(
            "SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton FOR UPDATE"
        ).fetchone()["fingerprint"]
        if current not in {SOURCE, TARGET}:
            raise ValueError("Unsupported migration source fingerprint")
        for table in TABLES:
            tx.execute(
                _ddl(source if current == SOURCE else target, table)
                .replace("CREATE TABLE data.", "CREATE TEMP TABLE ")
                .removesuffix(";")
                + " ON COMMIT DROP"
            )
            if table == "refresh_operations":
                tx.execute(f"ALTER TABLE pg_temp.{table} ADD PRIMARY KEY (idempotency_key)")
            if _shape(tx, f"data.{table}") != _shape(tx, f"pg_temp.{table}"):
                raise ValueError("Refresh schema differs from declared migration contract")
        if current == TARGET:
            return dict(migration=MIGRATION, status="already_current", updated=0)
        if tx.execute(
            "SELECT 1 FROM data.refresh_operations WHERE status IN ('accepted','running') "
            "UNION ALL SELECT 1 FROM data.financial_daily_refresh_operations "
            "WHERE status='running' "
            "UNION ALL SELECT 1 FROM data.industry_refresh_operations "
            "WHERE status='running' LIMIT 1"
        ).fetchone():
            raise ValueError("Drain refresh operations and stop writers before upgrading")
        report = dict(
            migration=MIGRATION,
            source=SOURCE,
            target=TARGET,
            status="applied" if apply else "validated",
            updated=0,
        )
        if not apply:
            return report
        tx.execute(
            "ALTER TABLE data.refresh_operations "
            "ADD COLUMN preparation jsonb DEFAULT '{}'::jsonb NOT NULL, ADD COLUMN retry_of text"
        )
        for table in TABLES:
            for name in re.findall(r"CONSTRAINT (\w+) CHECK", _ddl(source, table)):
                tx.execute(f"ALTER TABLE data.{table} DROP CONSTRAINT {name}")
            ddl = _ddl(target, table)
            # Each top-level named CHECK is comma-delimited; embedded checks may span lines.
            checks = re.split(
                r",\s*(?=CONSTRAINT )", ddl[ddl.index("CONSTRAINT ") :].removesuffix("\n);")
            )
            for check in checks:
                tx.execute(f"ALTER TABLE data.{table} ADD {check}")
            if _shape(tx, f"data.{table}") != _shape_after(tx, target, table):
                raise ValueError("Migration did not produce the declared target")
        tx.execute(
            "CREATE TABLE IF NOT EXISTS thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text NOT NULL, target_fingerprint text NOT NULL, "
            "updated_rows integer NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        tx.execute(
            "INSERT INTO thesistrace_meta.migration_history "
            "(id,source_fingerprint,target_fingerprint,updated_rows) VALUES (%s,%s,%s,0)",
            (MIGRATION, SOURCE, TARGET),
        )
        tx.execute(
            "UPDATE thesistrace_meta.schema_contract SET fingerprint=%s WHERE singleton", (TARGET,)
        )
        return report


def _shape_after(tx, target, table):
    tx.execute(f"DROP TABLE pg_temp.{table}")
    tx.execute(
        _ddl(target, table).replace("CREATE TABLE data.", "CREATE TEMP TABLE ").removesuffix(";")
        + " ON COMMIT DROP"
    )
    if table == "refresh_operations":
        tx.execute(f"ALTER TABLE pg_temp.{table} ADD PRIMARY KEY (idempotency_key)")
    return _shape(tx, f"pg_temp.{table}")


def migrate_head(
    data_root: Path, benchmark_root: Path, *, backup: Path, apply: bool = False
) -> dict:
    """Separate resumable step: runtime refuses Head v1 until this explicit conversion succeeds."""
    roots = [root.resolve() for root in (data_root, benchmark_root, backup)]
    if any(
        a == b or a in b.parents or b in a.parents
        for i, a in enumerate(roots)
        for b in roots[i + 1 :]
    ):
        raise ValueError("Dataset, Benchmark and backup roots must be independent")
    path = data_root / "HEAD.json"
    if not path.exists():
        return dict(status="empty", head_version=2)
    with (data_root / ".head.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        content = path.read_bytes()
        old = json.loads(content)
        if old.get("version") == 2:
            pointer = _pointer_from_manifest(_parse_head(content))
            MountedDatasetHeadStore(data_root).resolve_descriptor(pointer)
            if pointer.benchmark_snapshot_sha256 is not None:
                PreparedBenchmarkSnapshots(benchmark_root).read(pointer.benchmark_snapshot_sha256)
            return dict(status="already_current", head_version=2)
        if old.get("version") != 1 or canonical_json_bytes(old) != content:
            raise ValueError("Unsupported Dataset Head source")
        snapshot_path = benchmark_root / BENCHMARK_SNAPSHOT_FILENAME
        snapshot_bytes = snapshot_path.read_bytes() if snapshot_path.exists() else None
        snapshot = None if snapshot_bytes is None else _decode_snapshot(snapshot_bytes)
        updated = canonical_json_bytes(
            old
            | {
                "version": 2,
                "benchmark_snapshot_sha256": None if snapshot is None else snapshot.sha256,
            }
        )
        pointer = _pointer_from_manifest(_parse_head(updated))
        MountedDatasetHeadStore(data_root).resolve_descriptor(pointer)
        if not apply:
            return dict(status="validated", head_version=2)
        backup.mkdir(parents=True, exist_ok=True)
        _backup(backup / "HEAD.v1.json", content)
        if snapshot_bytes is not None:
            _backup(backup / BENCHMARK_SNAPSHOT_FILENAME, snapshot_bytes)
            AddressedFileStore(benchmark_root).store(
                benchmark_root / "snapshots" / f"{snapshot.sha256}.json",
                snapshot.sha256,
                snapshot_bytes,
            )
        root_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            _replace_entry(root_fd, "HEAD.json", updated)
        finally:
            os.close(root_fd)
        return dict(
            status="applied",
            head_version=2,
            generation_manifest_sha256=pointer.generation_manifest_sha256,
        )


def _backup(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("Migration backup differs from source")
        return
    with path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _record_receipt(path: Path, report: dict) -> None:
    if path.exists():
        previous = json.loads(path.read_bytes())
        if previous.get("migration") != MIGRATION or (
            previous.get("database_backup_sha256") != report["database_backup_sha256"]
        ):
            raise ValueError("Migration receipt differs from this upgrade and backup")
        return
    _backup(path, canonical_json_bytes(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--backup-directory", type=Path, required=True)
    args = parser.parse_args()
    dump = args.backup_directory / "database.dump"
    if args.apply and (not dump.is_file() or dump.stat().st_size == 0):
        parser.error("Save a database backup to <backup-directory>/database.dump before --apply")
    database = PostgresDatabase(os.environ["THESISTRACE_DATABASE_URL"])
    database.open()
    try:
        # Validate both resources before changing either. A restart after the DB step
        # resumes the Head conversion; no running application reads a mixed contract.
        migrate_head(args.data_root, args.benchmark_root, backup=args.backup_directory)
        report = migrate(database, apply=args.apply)
        report["head"] = migrate_head(
            args.data_root, args.benchmark_root, backup=args.backup_directory, apply=args.apply
        )
        if args.apply:
            with dump.open("rb") as source_dump:
                report["database_backup_sha256"] = hashlib.file_digest(
                    source_dump, "sha256"
                ).hexdigest()
            _record_receipt(args.backup_directory / "0006-receipt.json", report)
        print(json.dumps(report))
    finally:
        database.close()


if __name__ == "__main__":
    main()
