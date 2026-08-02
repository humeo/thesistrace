#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

import psycopg
from psycopg import sql

from thesistrace.hosted.backup_operations import (
    load_restore_snapshot,
    verify_restored_state,
)
from thesistrace.objects import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "scripts" / "hosted-stack"
BASE_COMPOSE = ROOT / "deploy" / "hosted" / "compose.yaml"
LOCAL_COMPOSE = ROOT / "deploy" / "hosted" / "compose.local.yaml"
RESTORE_DATABASE_NAME = "thesistrace_local_recovery_restore"


class LocalRecoveryAcceptanceError(RuntimeError):
    pass


class RecoveryOperations(Protocol):
    def capture_backup(self) -> tuple[dict[str, object], dict[str, object]]: ...

    def cold_restart_and_smoke(self) -> None: ...

    def live_snapshot(self) -> dict[str, object]: ...

    def restore_and_verify(
        self,
        expected_snapshot: dict[str, object],
    ) -> dict[str, object]: ...

    def cleanup(self) -> None: ...


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RuntimeRecoveryOperations:
    def __init__(self, *, state_dir: Path, port: int, project: str) -> None:
        self.state_dir = state_dir.resolve()
        self.port = port
        self.project = project
        self.backup_root = self.state_dir / "local-recovery-scratch"
        self.dump_path = self.backup_root / "postgres.dump"
        self.object_root = self.backup_root / "objects"
        self.password = self._password()

    def _password(self) -> str:
        try:
            password = (
                self.state_dir / "secrets" / "postgres_password"
            ).read_text().strip()
        except OSError as error:
            raise LocalRecoveryAcceptanceError(
                "local PostgreSQL administrator credential is unavailable"
            ) from error
        if not password:
            raise LocalRecoveryAcceptanceError(
                "local PostgreSQL administrator credential is empty"
            )
        return password

    def _connection_info(self, database_name: str) -> str:
        return psycopg.conninfo.make_conninfo(
            host="127.0.0.1",
            port=self.port,
            user="postgres",
            password=self.password,
            dbname=database_name,
            connect_timeout=10,
        )

    def _database_name(self) -> str:
        return os.environ.get("POSTGRES_DB", "insforge")

    def _postgres_environment(self) -> dict[str, str]:
        return {**os.environ, "PGPASSWORD": self.password}

    def _run(self, label: str, command: tuple[str, ...]) -> bytes:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=os.environ,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise LocalRecoveryAcceptanceError(
                f"{label} failed with exit {completed.returncode}:\n"
                + output[-8000:].decode("utf-8", errors="replace")
            )
        return output

    def _run_postgres(self, label: str, command: tuple[str, ...]) -> bytes:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=self._postgres_environment(),
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise LocalRecoveryAcceptanceError(
                f"{label} failed with exit {completed.returncode}:\n"
                + output[-8000:].decode("utf-8", errors="replace")
            )
        return output

    def _manage_restore_database(self, operation: str) -> None:
        if operation not in {"recreate", "drop"}:
            raise LocalRecoveryAcceptanceError(
                f"unsupported restore database operation: {operation}"
            )
        with psycopg.connect(
            self._connection_info("postgres"),
            autocommit=True,
        ) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (RESTORE_DATABASE_NAME,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(RESTORE_DATABASE_NAME)
                )
            )
            if operation == "recreate":
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(RESTORE_DATABASE_NAME)
                    )
                )

    def _object_store_container(self) -> str:
        value = self._run(
            "object-store container discovery",
            (
                "docker",
                "compose",
                "--project-directory",
                str(ROOT),
                "--file",
                str(BASE_COMPOSE),
                "--file",
                str(LOCAL_COMPOSE),
                "--project-name",
                self.project,
                "ps",
                "--quiet",
                "object-store",
            ),
        ).decode("utf-8", errors="replace").strip()
        if not value or "\n" in value:
            raise LocalRecoveryAcceptanceError(
                "local object-store container could not be identified uniquely"
            )
        return value

    def capture_backup(self) -> tuple[dict[str, object], dict[str, object]]:
        if self.backup_root.parent != self.state_dir:
            raise LocalRecoveryAcceptanceError("local recovery scratch path escaped state")
        shutil.rmtree(self.backup_root, ignore_errors=True)
        self.object_root.mkdir(parents=True, mode=0o700)
        snapshot = load_restore_snapshot(self._connection_info(self._database_name()))
        self._run_postgres(
            "compact PostgreSQL backup",
            (
                "pg_dump",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--username",
                "postgres",
                "--dbname",
                self._database_name(),
                "--format",
                "custom",
                "--file",
                str(self.dump_path),
            ),
        )
        self._run(
            "immutable ObjectStore backup",
            (
                "docker",
                "cp",
                f"{self._object_store_container()}:/var/lib/thesistrace/objects/.",
                str(self.object_root),
            ),
        )
        (self.backup_root / "snapshot.json").write_bytes(
            canonical_json_bytes(snapshot)
        )
        backup_bytes = sum(
            path.stat().st_size
            for path in self.backup_root.rglob("*")
            if path.is_file()
        )
        return snapshot, {
            "database_dump_sha256": _file_sha256(self.dump_path),
            "backup_bytes": backup_bytes,
        }

    def cold_restart_and_smoke(self) -> None:
        self._run("local core pause", (str(STACK), "local-pause"))
        self._run("local core cold start", (str(STACK), "local-up"))
        self._run(
            "local Public-Origin smoke after cold restart",
            (sys.executable, str(ROOT / "scripts" / "hosted-smoke.py")),
        )

    def live_snapshot(self) -> dict[str, object]:
        return load_restore_snapshot(self._connection_info(self._database_name()))

    def restore_and_verify(
        self,
        expected_snapshot: dict[str, object],
    ) -> dict[str, object]:
        self._manage_restore_database("recreate")
        self._run_postgres(
            "compact PostgreSQL restore",
            (
                "pg_restore",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--username",
                "postgres",
                "--dbname",
                RESTORE_DATABASE_NAME,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                str(self.dump_path),
            ),
        )
        restored = load_restore_snapshot(
            self._connection_info(RESTORE_DATABASE_NAME)
        )
        if canonical_json_bytes(restored) != canonical_json_bytes(expected_snapshot):
            raise LocalRecoveryAcceptanceError(
                "restored PostgreSQL state differs from the captured snapshot"
            )
        return verify_restored_state(
            object_root=self.object_root,
            snapshot=restored,
        )

    def cleanup(self) -> None:
        self._manage_restore_database("drop")
        if self.backup_root.parent != self.state_dir:
            raise LocalRecoveryAcceptanceError("local recovery cleanup escaped state")
        shutil.rmtree(self.backup_root, ignore_errors=True)


def run_local_recovery(operations: RecoveryOperations) -> dict[str, object]:
    try:
        before, backup = operations.capture_backup()
        operations.cold_restart_and_smoke()
        after = operations.live_snapshot()
        if canonical_json_bytes(after) != canonical_json_bytes(before):
            raise LocalRecoveryAcceptanceError(
                "authoritative state changed across the local cold restart"
            )
        restored = operations.restore_and_verify(before)
        latest_release = restored.get("latest_dataset_release_id")
        verified_objects = restored.get("verified_objects")
        dump_sha256 = backup.get("database_dump_sha256")
        backup_bytes = backup.get("backup_bytes")
        if (
            not isinstance(latest_release, str)
            or not latest_release
            or not isinstance(verified_objects, int)
            or verified_objects < 1
            or not isinstance(dump_sha256, str)
            or len(dump_sha256) != 64
            or not isinstance(backup_bytes, int)
            or backup_bytes <= 0
        ):
            raise LocalRecoveryAcceptanceError(
                "local backup/restore evidence is incomplete"
            )
        return {
            "status": "passed",
            "schema_version": "hosted-local-recovery-v1",
            "cold_restart": True,
            "database_restore": "disposable-runtime-postgresql",
            "authoritative_state_survived": True,
            "object_index_and_payload_verified": True,
            "latest_dataset_release_id": latest_release,
            "verified_objects": verified_objects,
            "database_dump_sha256": dump_sha256,
            "backup_bytes": backup_bytes,
            "off_node": False,
            "production_rpo_rto_claimed": False,
            "whole_node_resilience_claimed": False,
        }
    finally:
        operations.cleanup()


def main() -> None:
    if os.environ.get("THESISTRACE_LOCAL_ACCEPTANCE") != "1":
        raise LocalRecoveryAcceptanceError(
            "local recovery acceptance requires THESISTRACE_LOCAL_ACCEPTANCE=1"
        )
    state_dir = Path(
        os.environ.get("THESISTRACE_HOST_STATE_DIR", ROOT / ".hosted")
    )
    try:
        port = int(os.environ.get("THESISTRACE_LOCAL_POSTGRES_PORT", "25432"))
    except ValueError as error:
        raise LocalRecoveryAcceptanceError(
            "THESISTRACE_LOCAL_POSTGRES_PORT must be an integer"
        ) from error
    project = os.environ.get(
        "THESISTRACE_COMPOSE_PROJECT_NAME",
        "thesistrace-hosted-local",
    )
    evidence = run_local_recovery(
        RuntimeRecoveryOperations(
            state_dir=state_dir,
            port=port,
            project=project,
        )
    )
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalRecoveryAcceptanceError as error:
        raise SystemExit(str(error)) from error
