from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import LiteralString

from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from psycopg import Error as PsycopgError
from psycopg import sql

from thesistrace._postgres import PostgresDatabase, PostgresTransaction
from thesistrace.data.lifecycle import (
    CURRENT_DATA_CUTOVER_LOCK,
    MOUNTED_DATA_MUTATION_LOCK,
)
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.publication.service import PUBLICATION_MUTATION_LOCK

_RESET_LOCK = "thesistrace-development-reset"
_DEVELOPMENT_ENVIRONMENT = "development"


class DevelopmentResetError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DevelopmentResetOutcome:
    status: str
    deleted_object_count: int
    preserved_object_count: int
    deleted_path_count: int


@dataclass(frozen=True)
class _MountEntry:
    relative_path: str
    entry_kind: str
    device: int
    inode: int


class DevelopmentReset:
    """Explicit pre-production cutover reset with a fixed destructive plan."""

    def __init__(
        self,
        database: PostgresDatabase,
        s3: BaseClient,
        *,
        bucket: str,
        mount_root: Path | str,
    ) -> None:
        self._database = database
        self._s3 = s3
        self._bucket = bucket
        self._mount_root = _safe_mount(Path(mount_root))
        endpoint = getattr(getattr(s3, "meta", None), "endpoint_url", None)
        if not isinstance(endpoint, str) or not endpoint:
            raise DevelopmentResetError("RESET_STORAGE_TARGET_INVALID")
        self._storage_identity = json.dumps(
            {"bucket": bucket, "endpoint": endpoint.rstrip("/")},
            sort_keys=True,
            separators=(",", ":"),
        )

    def execute(
        self,
        *,
        idempotency_key: str,
        environment_name: str,
        confirmation: str,
    ) -> DevelopmentResetOutcome:
        key = _identity(idempotency_key)
        _guard_environment(environment_name, confirmation)
        with _opened_mount(self._mount_root) as mount_descriptor:
            mount_metadata = os.fstat(mount_descriptor)
            fingerprint = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "command": "development-reset/v1",
                        "environment": environment_name,
                        "mount_root": str(self._mount_root),
                        "mount_device": mount_metadata.st_dev,
                        "mount_inode": mount_metadata.st_ino,
                        "storage_identity": self._storage_identity,
                    }
                )
            ).hexdigest()
            with self._database.session_advisory_locks(
                CURRENT_DATA_CUTOVER_LOCK,
                _RESET_LOCK,
                MOUNTED_DATA_MUTATION_LOCK,
                PUBLICATION_MUTATION_LOCK,
            ):
                already_succeeded = self._ensure_plan(
                    key,
                    fingerprint,
                    environment_name,
                    mount_descriptor=mount_descriptor,
                    mount_device=mount_metadata.st_dev,
                    mount_inode=mount_metadata.st_ino,
                )
                if already_succeeded:
                    return self._outcome(key)
                try:
                    self._reset_postgres(key)
                    self._delete_objects(key)
                    self._delete_mount(key, mount_descriptor)
                    self._succeed(key)
                except DevelopmentResetError as error:
                    self._fail(key, error.code)
                    raise
                except PsycopgError as error:
                    self._fail(key, "RESET_POSTGRES_FAILED")
                    raise DevelopmentResetError("RESET_POSTGRES_FAILED") from error
                return self._outcome(key)

    def _ensure_plan(
        self,
        key: str,
        fingerprint: str,
        environment_name: str,
        *,
        mount_descriptor: int,
        mount_device: int,
        mount_inode: int,
    ) -> bool:
        with self._database.transaction() as transaction:
            existing = transaction.execute(
                """
                SELECT fingerprint, environment_name, mount_root,
                       mount_device, mount_inode, storage_identity, status
                FROM data.development_reset_operations
                WHERE idempotency_key = %s
                FOR UPDATE
                """,
                (key,),
            ).fetchone()
        if existing is not None:
            expected = {
                "fingerprint": fingerprint,
                "environment_name": environment_name,
                "mount_root": str(self._mount_root),
                "mount_device": mount_device,
                "mount_inode": mount_inode,
                "storage_identity": self._storage_identity,
            }
            if {name: existing[name] for name in expected} != expected:
                raise DevelopmentResetError("RESET_IDEMPOTENCY_CONFLICT")
            if existing["status"] == "succeeded":
                return True
            self._validate_fixed_paths(key, mount_descriptor)
            with self._database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.development_reset_operations
                    SET status = 'running', failure_code = NULL,
                        finished_at = NULL, updated_at = now()
                    WHERE idempotency_key = %s
                    """,
                    (key,),
                )
            return False

        paths = _inventory_mount(mount_descriptor)
        with self._database.transaction() as transaction:
            manifests = _target_manifests(transaction)
            _validate_manifest_records(transaction, manifests)
            objects = _manifest_objects(transaction, manifests)
        self._validate_objects(objects)
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                INSERT INTO data.development_reset_operations (
                    idempotency_key, fingerprint, environment_name,
                    mount_root, mount_device, mount_inode, storage_identity, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'running')
                """,
                (
                    key,
                    fingerprint,
                    environment_name,
                    str(self._mount_root),
                    mount_device,
                    mount_inode,
                    self._storage_identity,
                ),
            )
            with transaction.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO data.development_reset_manifests (
                        idempotency_key, manifest_sha256
                    ) VALUES (%s, %s)
                    """,
                    [(key, manifest) for manifest in manifests],
                )
                cursor.executemany(
                    """
                    INSERT INTO data.development_reset_objects (
                        idempotency_key, object_sha256, status
                    ) VALUES (%s, %s, 'pending')
                    """,
                    [(key, object_sha256) for object_sha256 in objects],
                )
                cursor.executemany(
                    """
                    INSERT INTO data.development_reset_paths (
                        idempotency_key, relative_path, entry_kind,
                        entry_device, entry_inode, status
                    ) VALUES (%s, %s, %s, %s, %s, 'pending')
                    """,
                    [
                        (
                            key,
                            entry.relative_path,
                            entry.entry_kind,
                            entry.device,
                            entry.inode,
                        )
                        for entry in paths
                    ],
                )
        return False

    def _reset_postgres(self, key: str) -> None:
        with self._database.transaction() as transaction:
            operation = transaction.execute(
                """
                SELECT postgres_done FROM data.development_reset_operations
                WHERE idempotency_key = %s FOR UPDATE
                """,
                (key,),
            ).fetchone()
            if operation is None:
                raise RuntimeError("Development Reset operation disappeared")
            if operation["postgres_done"]:
                return
            transaction.execute("DELETE FROM definitions.run_receipts")
            _truncate_existing(
                transaction,
                (
                    "daily_tracks.session_progression_attempts",
                    "daily_tracks.session_tracking_states",
                    "daily_tracks.session_progressions",
                    "daily_tracks.session_checkpoints",
                    "daily_tracks.progression_attempts",
                    "daily_tracks.retry_receipts",
                    "daily_tracks.stop_receipts",
                    "daily_tracks.checkpoints",
                    "daily_tracks.progressions",
                    "daily_tracks.tracks",
                    "research_runs.start_tracking_receipts",
                    "research_runs.rerun_receipts",
                    "research_runs.cancel_receipts",
                    "research_runs.attempts",
                    "research_runs.runs",
                ),
            )
            if _relation_exists(transaction, "data.state"):
                transaction.execute(
                    """
                    UPDATE data.state
                    SET status = 'idle', latest_update_outcome = NULL,
                        latest_release_id = NULL, updated_at = now()
                    WHERE singleton = 1
                    """
                )
            for table in (
                "release_fields",
                "fields",
                "update_attempts",
                "update_receipts",
                "releases",
                "generation_pins",
                "generation_candidates",
                "bootstrap_operations",
                "refresh_operations",
                "collection_roots",
                "collection_targets",
                "collection_operations",
            ):
                relation = f"data.{table}"
                if _relation_exists(transaction, relation):
                    transaction.execute(f"DELETE FROM {relation}")
            transaction.execute(
                "UPDATE data.current_dataset_state SET last_refresh_at = NULL WHERE singleton = 1"
            )
            transaction.execute(
                """
                DELETE FROM publication.manifest_objects
                WHERE manifest_sha256 IN (
                    SELECT manifest_sha256
                    FROM data.development_reset_manifests
                    WHERE idempotency_key = %s
                )
                """,
                (key,),
            )
            transaction.execute(
                """
                DELETE FROM publication.manifests
                WHERE sha256 IN (
                    SELECT manifest_sha256
                    FROM data.development_reset_manifests
                    WHERE idempotency_key = %s
                )
                """,
                (key,),
            )
            transaction.execute(
                """
                UPDATE data.development_reset_objects AS target
                SET status = 'preserved', updated_at = now()
                WHERE target.idempotency_key = %s
                  AND EXISTS (
                      SELECT 1 FROM publication.manifest_objects AS link
                      WHERE link.object_sha256 = target.object_sha256
                  )
                """,
                (key,),
            )
            transaction.execute(
                """
                DELETE FROM publication.objects AS object
                WHERE object.sha256 IN (
                    SELECT target.object_sha256
                    FROM data.development_reset_objects AS target
                    WHERE target.idempotency_key = %s AND target.status = 'pending'
                )
                  AND NOT EXISTS (
                      SELECT 1 FROM publication.manifest_objects AS link
                      WHERE link.object_sha256 = object.sha256
                  )
                """,
                (key,),
            )
            transaction.execute(
                """
                UPDATE data.development_reset_operations
                SET postgres_done = true, updated_at = now()
                WHERE idempotency_key = %s
                """,
                (key,),
            )

    def _delete_objects(self, key: str) -> None:
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT object_sha256 FROM data.development_reset_objects
                WHERE idempotency_key = %s AND status = 'pending'
                ORDER BY object_sha256
                """,
                (key,),
            ).fetchall()
        for row in rows:
            digest = str(row["object_sha256"])
            with self._database.transaction() as transaction:
                retained = transaction.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM publication.manifest_objects
                        WHERE object_sha256 = %s
                    ) AS retained
                    """,
                    (digest,),
                ).fetchone()
                if retained is not None and retained["retained"]:
                    transaction.execute(
                        """
                        UPDATE data.development_reset_objects
                        SET status = 'preserved', updated_at = now()
                        WHERE idempotency_key = %s AND object_sha256 = %s
                          AND status = 'pending'
                        """,
                        (key, digest),
                    )
                    continue
            try:
                self._s3.delete_object(Bucket=self._bucket, Key=_object_key(digest))
            except (BotoCoreError, ClientError) as error:
                raise DevelopmentResetError("RESET_OBJECT_DELETE_FAILED") from error
            with self._database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.development_reset_objects
                    SET status = 'deleted', updated_at = now()
                    WHERE idempotency_key = %s AND object_sha256 = %s
                      AND status = 'pending'
                    """,
                    (key, digest),
                )

    def _delete_mount(self, key: str, mount_descriptor: int) -> None:
        self._validate_fixed_paths(key, mount_descriptor)
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT relative_path, entry_kind, entry_device, entry_inode
                FROM data.development_reset_paths
                WHERE idempotency_key = %s AND status = 'pending'
                ORDER BY CASE entry_kind WHEN 'file' THEN 0 ELSE 1 END,
                         length(relative_path) DESC, relative_path DESC
                """,
                (key,),
            ).fetchall()
        for row in rows:
            relative = str(row["relative_path"])
            try:
                _delete_relative(
                    mount_descriptor,
                    relative,
                    str(row["entry_kind"]),
                    int(row["entry_device"]),
                    int(row["entry_inode"]),
                )
            except DevelopmentResetError:
                raise
            except OSError as error:
                raise DevelopmentResetError("RESET_MOUNT_DELETE_FAILED") from error
            with self._database.transaction() as transaction:
                transaction.execute(
                    """
                    UPDATE data.development_reset_paths
                    SET status = 'deleted', updated_at = now()
                    WHERE idempotency_key = %s AND relative_path = %s
                      AND status = 'pending'
                    """,
                    (key, relative),
                )

    def _validate_fixed_paths(self, key: str, mount_descriptor: int) -> None:
        current = {
            (entry.relative_path, entry.entry_kind): (entry.device, entry.inode)
            for entry in _inventory_mount(mount_descriptor)
        }
        with self._database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT relative_path, entry_kind, entry_device, entry_inode, status
                FROM data.development_reset_paths
                WHERE idempotency_key = %s
                """,
                (key,),
            ).fetchall()
        planned = {
            (str(row["relative_path"]), str(row["entry_kind"])): (
                int(row["entry_device"]),
                int(row["entry_inode"]),
            )
            for row in rows
        }
        if not current.keys() <= planned.keys():
            raise DevelopmentResetError("RESET_MOUNT_TARGET_CHANGED")
        for row in rows:
            identity = (str(row["relative_path"]), str(row["entry_kind"]))
            observed = current.get(identity)
            if observed is not None and observed != planned[identity]:
                raise DevelopmentResetError("RESET_MOUNT_TARGET_CHANGED")
            if row["status"] == "deleted" and observed is not None:
                raise DevelopmentResetError("RESET_MOUNT_TARGET_CHANGED")

    def _validate_objects(self, objects: tuple[str, ...]) -> None:
        for digest in objects:
            try:
                response = self._s3.head_object(Bucket=self._bucket, Key=_object_key(digest))
            except (BotoCoreError, ClientError) as error:
                raise DevelopmentResetError("RESET_OBJECT_TARGET_INVALID") from error
            metadata = response.get("Metadata", {})
            if not isinstance(metadata, dict) or metadata.get("sha256") != digest:
                raise DevelopmentResetError("RESET_OBJECT_TARGET_INVALID")

    def _succeed(self, key: str) -> None:
        with self._database.transaction() as transaction:
            remaining = transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM data.development_reset_objects
                     WHERE idempotency_key = %s AND status = 'pending')
                  + (SELECT count(*) FROM data.development_reset_paths
                     WHERE idempotency_key = %s AND status = 'pending') AS count
                """,
                (key, key),
            ).fetchone()
            if remaining is None or int(remaining["count"]) != 0:
                raise RuntimeError("Development Reset completed with pending targets")
            transaction.execute(
                """
                UPDATE data.development_reset_operations
                SET status = 'succeeded', failure_code = NULL,
                    finished_at = now(), updated_at = now()
                WHERE idempotency_key = %s
                """,
                (key,),
            )

    def _fail(self, key: str, code: str) -> None:
        with self._database.transaction() as transaction:
            transaction.execute(
                """
                UPDATE data.development_reset_operations
                SET status = 'failed', failure_code = %s,
                    finished_at = now(), updated_at = now()
                WHERE idempotency_key = %s AND status = 'running'
                """,
                (code, key),
            )

    def _outcome(self, key: str) -> DevelopmentResetOutcome:
        with self._database.transaction() as transaction:
            row = transaction.execute(
                """
                SELECT status,
                    (SELECT count(*) FROM data.development_reset_objects
                     WHERE idempotency_key = %s AND status = 'deleted') AS deleted_objects,
                    (SELECT count(*) FROM data.development_reset_objects
                     WHERE idempotency_key = %s AND status = 'preserved') AS preserved_objects,
                    (SELECT count(*) FROM data.development_reset_paths
                     WHERE idempotency_key = %s AND status = 'deleted') AS deleted_paths
                FROM data.development_reset_operations
                WHERE idempotency_key = %s
                """,
                (key, key, key, key),
            ).fetchone()
        if row is None:
            raise RuntimeError("Development Reset operation disappeared")
        return DevelopmentResetOutcome(
            status=str(row["status"]),
            deleted_object_count=int(row["deleted_objects"]),
            preserved_object_count=int(row["preserved_objects"]),
            deleted_path_count=int(row["deleted_paths"]),
        )


def _guard_environment(environment_name: str, confirmation: str) -> None:
    if environment_name != _DEVELOPMENT_ENVIRONMENT:
        raise DevelopmentResetError("RESET_ENVIRONMENT_REFUSED")
    if confirmation != f"reset:{environment_name}":
        raise DevelopmentResetError("RESET_CONFIRMATION_MISMATCH")


def _safe_mount(path: Path) -> Path:
    if not path.is_absolute() or not str(path).strip():
        raise DevelopmentResetError("RESET_MOUNT_UNSAFE")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise DevelopmentResetError("RESET_MOUNT_UNSAFE") from error
    workspace = Path(__file__).resolve().parents[3]
    broad_roots = {
        Path(resolved.anchor),
        Path("/tmp"),
        Path("/private/tmp"),
        Path.home(),
        workspace,
        *workspace.parents,
    }
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or resolved in broad_roots
        or resolved.name != "canonical-data"
    ):
        raise DevelopmentResetError("RESET_MOUNT_UNSAFE")
    return resolved


@contextmanager
def _opened_mount(root: Path) -> Iterator[int]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as error:
        raise DevelopmentResetError("RESET_MOUNT_UNSAFE") from error
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _inventory_mount(root_descriptor: int) -> tuple[_MountEntry, ...]:
    entries: list[_MountEntry] = []

    def visit(directory_descriptor: int, relative: PurePosixPath) -> None:
        try:
            with os.scandir(directory_descriptor) as directory_entries:
                children = sorted(directory_entries, key=lambda entry: entry.name)
        except OSError as error:
            raise DevelopmentResetError("RESET_MOUNT_UNSAFE") from error
        for child in children:
            child_relative = relative / child.name
            if child.is_symlink():
                raise DevelopmentResetError("RESET_MOUNT_UNSAFE")
            metadata = child.stat(follow_symlinks=False)
            if child.is_dir(follow_symlinks=False):
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                child_descriptor = os.open(child.name, flags, dir_fd=directory_descriptor)
                try:
                    opened = os.fstat(child_descriptor)
                    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                        raise DevelopmentResetError("RESET_MOUNT_TARGET_CHANGED")
                    visit(child_descriptor, child_relative)
                finally:
                    os.close(child_descriptor)
                entries.append(
                    _MountEntry(
                        child_relative.as_posix(),
                        "directory",
                        metadata.st_dev,
                        metadata.st_ino,
                    )
                )
            elif child.is_file(follow_symlinks=False):
                entries.append(
                    _MountEntry(
                        child_relative.as_posix(),
                        "file",
                        metadata.st_dev,
                        metadata.st_ino,
                    )
                )
            else:
                raise DevelopmentResetError("RESET_MOUNT_UNSAFE")

    visit(root_descriptor, PurePosixPath())
    return tuple(entries)


def _delete_relative(
    root_descriptor: int,
    relative: str,
    kind: str,
    expected_device: int,
    expected_inode: int,
) -> None:
    path = PurePosixPath(relative)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.dup(root_descriptor)
    try:
        for component in path.parts[:-1]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        try:
            metadata = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        if (metadata.st_dev, metadata.st_ino) != (expected_device, expected_inode):
            raise DevelopmentResetError("RESET_MOUNT_TARGET_CHANGED")
        if kind == "file" and stat.S_ISREG(metadata.st_mode):
            os.unlink(path.name, dir_fd=descriptor)
        elif kind == "directory" and stat.S_ISDIR(metadata.st_mode):
            os.rmdir(path.name, dir_fd=descriptor)
        else:
            raise DevelopmentResetError("RESET_MOUNT_TARGET_CHANGED")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _target_manifests(transaction: PostgresTransaction) -> tuple[str, ...]:
    manifests: set[str] = set()

    def collect(statement: LiteralString) -> None:
        manifests.update(
            str(row["manifest_sha256"])
            for row in transaction.execute(statement).fetchall()
        )

    collect(
        """
        SELECT result_manifest_sha256 AS manifest_sha256
        FROM research_runs.runs
        WHERE result_manifest_sha256 IS NOT NULL
        """
    )
    collect(
        """
        SELECT sha256 AS manifest_sha256
        FROM publication.manifests
        WHERE kind = 'data.release'
        """
    )
    if _relation_exists(transaction, "data.releases"):
        collect("SELECT manifest_sha256 FROM data.releases")
    if _column_exists(transaction, "daily_tracks", "tracks", "head_manifest_sha256"):
        collect(
            """
            SELECT head_manifest_sha256 AS manifest_sha256
            FROM daily_tracks.tracks
            WHERE head_manifest_sha256 IS NOT NULL
            """
        )
    if _relation_exists(transaction, "daily_tracks.checkpoints"):
        collect("SELECT manifest_sha256 FROM daily_tracks.checkpoints")
    collect("SELECT manifest_sha256 FROM daily_tracks.session_checkpoints")
    return tuple(sorted(manifests))


def _truncate_existing(
    transaction: PostgresTransaction,
    relations: tuple[str, ...],
) -> None:
    selected = tuple(
        relation for relation in relations if _relation_exists(transaction, relation)
    )
    if selected:
        transaction.execute(
            sql.SQL("TRUNCATE {}").format(
                sql.SQL(", ").join(
                    sql.Identifier(*relation.split(".", maxsplit=1))
                    for relation in selected
                )
            )
        )


def _relation_exists(transaction: PostgresTransaction, relation: str) -> bool:
    row = transaction.execute("SELECT to_regclass(%s) AS value", (relation,)).fetchone()
    return bool(row and row["value"] is not None)


def _column_exists(
    transaction: PostgresTransaction,
    schema: str,
    table: str,
    column: str,
) -> bool:
    row = transaction.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
        ) AS value
        """,
        (schema, table, column),
    ).fetchone()
    return bool(row and row["value"])


def _manifest_objects(
    transaction: PostgresTransaction,
    manifests: tuple[str, ...],
) -> tuple[str, ...]:
    if not manifests:
        return ()
    rows = transaction.execute(
        """
        SELECT DISTINCT object_sha256
        FROM publication.manifest_objects
        WHERE manifest_sha256 = ANY(%s)
        ORDER BY object_sha256
        """,
        (list(manifests),),
    ).fetchall()
    return tuple(str(row["object_sha256"]) for row in rows)


def _validate_manifest_records(
    transaction: PostgresTransaction,
    manifests: tuple[str, ...],
) -> None:
    if not manifests:
        return
    rows = transaction.execute(
        """
        SELECT sha256, manifest_bytes
        FROM publication.manifests
        WHERE sha256 = ANY(%s)
        ORDER BY sha256
        """,
        (list(manifests),),
    ).fetchall()
    if tuple(str(row["sha256"]) for row in rows) != manifests:
        raise DevelopmentResetError("RESET_PUBLICATION_TARGET_INVALID")
    for row in rows:
        manifest_bytes = bytes(row["manifest_bytes"])
        if hashlib.sha256(manifest_bytes).hexdigest() != row["sha256"]:
            raise DevelopmentResetError("RESET_PUBLICATION_TARGET_INVALID")
        try:
            manifest = json.loads(manifest_bytes)
            described = {
                str(item["sha256"]) for item in manifest["objects"] if isinstance(item, dict)
            }
        except (KeyError, TypeError, ValueError) as error:
            raise DevelopmentResetError("RESET_PUBLICATION_TARGET_INVALID") from error
        linked = {
            str(link["object_sha256"])
            for link in transaction.execute(
                """
                SELECT object_sha256 FROM publication.manifest_objects
                WHERE manifest_sha256 = %s
                """,
                (row["sha256"],),
            ).fetchall()
        }
        if described != linked:
            raise DevelopmentResetError("RESET_PUBLICATION_TARGET_INVALID")


def _object_key(digest: str) -> str:
    return f"publication/v1/sha256/{digest[:2]}/{digest}"


def _identity(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise DevelopmentResetError("RESET_IDEMPOTENCY_KEY_INVALID")
    return value


__all__ = (
    "DevelopmentReset",
    "DevelopmentResetError",
    "DevelopmentResetOutcome",
)
