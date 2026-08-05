import argparse
import fcntl
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from thesistrace.config import database_url_from_environment
from thesistrace.hosted.backup_operations import (
    SOURCE_LAYOUT,
    BackupOperationError,
    initialize_backup_target,
    load_restore_snapshot,
    perform_backup,
    require_initialized_backup_target,
    restore_recovery_set,
    restore_release_configuration_modes,
    restore_secret_recovery_bundle,
    validate_backup_target,
    verify_authenticated_recovery_selection,
    verify_restored_state,
    write_recovery_exercise,
)
from thesistrace.hosted.operator_audit import (
    OPERATOR_AUDIT_ACTIONS,
    RECOVERY_AUDIT_ACTIONS,
    flush_operator_audits,
    stage_operator_audit,
)
from thesistrace.objects import canonical_json_bytes


class RecoveryOperationBusy(RuntimeError):
    pass


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Operate coordinated Hosted backups")
    commands = result.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("target-init")
    initialize.add_argument("--target", type=Path, required=True)
    initialize.add_argument("--repository-root", type=Path, required=True)
    initialize.add_argument("--state-root", type=Path, required=True)

    validate = commands.add_parser("target-check")
    validate.add_argument("--target", type=Path, required=True)
    validate.add_argument("--repository-root", type=Path, required=True)
    validate.add_argument("--state-root", type=Path, required=True)

    create = commands.add_parser("create")
    create.add_argument("--target", type=Path, required=True)
    create.add_argument("--source-root", type=Path, required=True)
    create.add_argument("--release-bundle-id", required=True)
    create.add_argument("--passphrase-file", type=Path, required=True)
    create.add_argument("--status-path", type=Path, required=True)

    restore = commands.add_parser("restore")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--restore-root", type=Path, required=True)
    restore.add_argument("--working-cache", type=Path, required=True)
    restore.add_argument("--secret-root", type=Path, required=True)
    restore.add_argument("--backup-passphrase-file", type=Path, required=True)
    restore.add_argument("--recovery-passphrase-file", type=Path, required=True)
    restore.add_argument("--incident-at", required=True)
    restore.add_argument("--selection-output", type=Path, required=True)

    restore_modes = commands.add_parser("restore-release-modes")
    restore_modes.add_argument("--release-state", type=Path, required=True)

    verify = commands.add_parser("verify-restore")
    verify.add_argument(
        "--object-root",
        type=Path,
        default=Path("/var/lib/thesistrace/objects"),
    )
    verify.add_argument("--output", type=Path)
    verify.add_argument("--recovery-selection", type=Path, required=True)
    verify.add_argument("--expected-backup-id", required=True)

    runtime = commands.add_parser("verify-runtime")
    runtime.add_argument("--api-url", required=True)
    runtime.add_argument("--health-url", required=True)
    runtime.add_argument("--timeout-seconds", type=int, default=120)

    audit_stage = commands.add_parser("audit-stage")
    audit_stage.add_argument("--outbox", type=Path, required=True)
    audit_stage.add_argument("--event-id", required=True)
    audit_stage.add_argument(
        "--action",
        choices=OPERATOR_AUDIT_ACTIONS,
        required=True,
    )
    audit_stage.add_argument(
        "--outcome",
        choices=("succeeded", "rejected"),
        required=True,
    )
    audit_stage.add_argument("--subject-id", required=True)
    audit_stage.add_argument("--reason-code")

    audit_flush = commands.add_parser("audit-flush")
    audit_flush.add_argument("--outbox", type=Path, required=True)

    lock_run = commands.add_parser("lock-run")
    lock_run.add_argument("--lock", type=Path, required=True)
    lock_run.add_argument("--outbox", type=Path, required=True)
    lock_run.add_argument("--event-id", required=True)
    lock_run.add_argument(
        "--action",
        choices=RECOVERY_AUDIT_ACTIONS,
        required=True,
    )
    lock_run.add_argument("--subject-id", required=True)
    lock_run.add_argument("argv", nargs=argparse.REMAINDER)

    exercise = commands.add_parser("record-exercise")
    exercise.add_argument("--recovery-selection", type=Path, required=True)
    exercise.add_argument("--verification", type=Path, required=True)
    exercise.add_argument("--evidence-dir", type=Path, required=True)
    exercise.add_argument("--incident-at", required=True)
    exercise.add_argument("--detected-at", required=True)
    exercise.add_argument("--restore-started-at", required=True)
    exercise.add_argument("--restore-completed-at", required=True)
    exercise.add_argument("--public-origin-smoke", action="store_true")
    return result


def _passphrase(path: Path) -> str:
    try:
        value = path.read_text().rstrip("\n")
    except OSError as error:
        raise BackupOperationError("backup passphrase file is unavailable") from error
    if len(value) < 16:
        raise BackupOperationError("backup passphrase must contain at least 16 characters")
    return value


def _wait_for_available_runtime(
    api_url: str,
    health_url: str,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            for url in (api_url, health_url):
                with urllib.request.urlopen(url, timeout=5) as response:
                    payload = json.loads(response.read())
                if response.status != 200 or payload.get("status") != "available":
                    raise BackupOperationError("runtime health is degraded")
            return
        except (
            BackupOperationError,
            OSError,
            ValueError,
            urllib.error.URLError,
        ) as error:
            last_error = error
        time.sleep(2)
    raise BackupOperationError(f"runtime health did not become available: {last_error}")


def _acquire_recovery_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor)
        raise RecoveryOperationBusy("another recovery operation is active") from error
    return descriptor


def main() -> None:
    arguments = parser().parse_args()
    output: dict[str, object]
    if arguments.command == "target-init":
        target = initialize_backup_target(
            arguments.target,
            repository_root=arguments.repository_root,
            state_root=arguments.state_root,
        )
        output = {"status": "initialized", "target": str(target)}
    elif arguments.command == "target-check":
        target = validate_backup_target(
            arguments.target,
            repository_root=arguments.repository_root,
            state_root=arguments.state_root,
        )
        output = {"status": "ready", "target": str(target)}
    elif arguments.command == "create":
        require_initialized_backup_target(arguments.target)
        created = perform_backup(
            target=arguments.target,
            sources={
                name: arguments.source_root / name for name in SOURCE_LAYOUT
            },
            release_bundle_id=arguments.release_bundle_id,
            passphrase=_passphrase(arguments.passphrase_file),
            status_path=arguments.status_path,
        )
        output = {
            "status": "complete",
            "backup_id": created.manifest["backup_id"],
            "manifest": str(created.manifest_path),
        }
    elif arguments.command == "restore":
        manifest = restore_recovery_set(
            manifest_path=arguments.manifest,
            restore_root=arguments.restore_root,
            working_cache=arguments.working_cache,
            passphrase=_passphrase(arguments.backup_passphrase_file),
            incident_at=datetime.fromisoformat(arguments.incident_at),
            selection_output=arguments.selection_output,
        )
        recovered = restore_secret_recovery_bundle(
            arguments.restore_root / "secrets" / "current.recovery",
            secret_root=arguments.secret_root,
            passphrase=_passphrase(arguments.recovery_passphrase_file),
        )
        output = {
            "status": "restored",
            "backup_id": manifest["backup_id"],
            "secret_count": len(recovered),
        }
    elif arguments.command == "restore-release-modes":
        output = {
            "status": "restored",
            "configuration_file_count": restore_release_configuration_modes(
                arguments.release_state
            ),
        }
    elif arguments.command == "verify-restore":
        database_url = database_url_from_environment()
        if not database_url:
            raise BackupOperationError("restore verification database credentials are required")
        try:
            selection = json.loads(arguments.recovery_selection.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise BackupOperationError(
                "authenticated recovery selection is unavailable"
            ) from error
        if not isinstance(selection, dict):
            raise BackupOperationError("authenticated recovery selection is invalid")
        output = {
            "status": "verified",
            **verify_restored_state(
                object_root=arguments.object_root,
                snapshot=load_restore_snapshot(database_url),
            ),
            **verify_authenticated_recovery_selection(
                selection,
                expected_backup_id=arguments.expected_backup_id,
            ),
        }
        if arguments.output is not None:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = arguments.output.with_suffix(".tmp")
            temporary.write_bytes(canonical_json_bytes(output))
            temporary.replace(arguments.output)
    elif arguments.command == "verify-runtime":
        _wait_for_available_runtime(
            arguments.api_url,
            arguments.health_url,
            arguments.timeout_seconds,
        )
        output = {"status": "verified"}
    elif arguments.command == "audit-stage":
        path = stage_operator_audit(
            arguments.outbox,
            event_id=arguments.event_id,
            actor="operator",
            action=arguments.action,
            outcome=arguments.outcome,
            subject_id=arguments.subject_id,
            reason_code=arguments.reason_code,
        )
        output = {"status": "staged", "path": str(path)}
    elif arguments.command == "audit-flush":
        database_url = database_url_from_environment()
        if not database_url:
            raise BackupOperationError("management audit database credentials are required")
        output = {
            "status": "recorded",
            "flushed": flush_operator_audits(arguments.outbox, database_url),
        }
    elif arguments.command == "lock-run":
        try:
            descriptor = _acquire_recovery_lock(arguments.lock)
        except RecoveryOperationBusy:
            stage_operator_audit(
                arguments.outbox,
                event_id=arguments.event_id,
                actor="operator",
                action=arguments.action,
                outcome="rejected",
                subject_id=arguments.subject_id,
                reason_code="RECOVERY_OPERATION_BUSY",
            )
            print(
                json.dumps(
                    {
                        "status": "rejected",
                        "reason_code": "RECOVERY_OPERATION_BUSY",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            raise SystemExit(75) from None
        argv = list(arguments.argv)
        if argv[:1] == ["--"]:
            argv = argv[1:]
        if not argv:
            os.close(descriptor)
            raise BackupOperationError("recovery lock command is required")
        os.set_inheritable(descriptor, True)
        environment = dict(os.environ)
        environment["THESISTRACE_RECOVERY_LOCK_HELD"] = "1"
        os.execvpe(argv[0], argv, environment)
    else:
        try:
            verification = json.loads(arguments.verification.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise BackupOperationError(
                "restore verification evidence is unavailable"
            ) from error
        if not isinstance(verification, dict):
            raise BackupOperationError("restore verification evidence is invalid")
        evidence = write_recovery_exercise(
            recovery_selection_path=arguments.recovery_selection,
            evidence_dir=arguments.evidence_dir,
            incident_at=datetime.fromisoformat(arguments.incident_at),
            detected_at=datetime.fromisoformat(arguments.detected_at),
            restore_started_at=datetime.fromisoformat(arguments.restore_started_at),
            restore_completed_at=datetime.fromisoformat(arguments.restore_completed_at),
            verification=verification,
            public_origin_smoke=arguments.public_origin_smoke,
        )
        output = {"status": "recorded", "evidence": str(evidence)}
    output["observed_at"] = datetime.now(UTC).isoformat()
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
