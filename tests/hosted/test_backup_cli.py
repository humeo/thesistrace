import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from thesistrace.hosted import backup_cli, operator_audit


class AvailableResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return b'{"status":"available"}'


def test_runtime_gate_requires_available_api_health(monkeypatch) -> None:
    requested: list[str] = []

    def available(url: str, **_kwargs) -> AvailableResponse:
        requested.append(url)
        return AvailableResponse()

    monkeypatch.setattr(
        backup_cli.urllib.request,
        "urlopen",
        available,
    )

    backup_cli._wait_for_available_runtime(
        "http://api/health",
        "http://health-service/health/recovery",
        1,
    )

    assert requested == [
        "http://api/health",
        "http://health-service/health/recovery",
    ]


def test_management_audit_outbox_is_sanitized_retryable_and_persisted(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    class Store:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://operator"

        def append_management_audit_event_idempotent(
            self,
            event: dict[str, object],
        ) -> None:
            events.append(event)

    monkeypatch.setattr(operator_audit, "PostgresManagementStore", Store)
    outbox = tmp_path / "audit-outbox"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup-cli",
            "audit-stage",
            "--outbox",
            str(outbox),
            "--event-id",
            "audit_recovery_test",
            "--action",
            "backup.restore",
            "--subject-id",
            "backup_20260801T000000Z_aaaaaaaaaaaa",
            "--outcome",
            "rejected",
            "--reason-code",
            "OPERATION_INTERRUPTED",
        ],
    )

    backup_cli.main()
    staged = json.loads((outbox / "audit_recovery_test.json").read_bytes())
    assert staged["outcome"] == "rejected"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup-cli",
            "audit-stage",
            "--outbox",
            str(outbox),
            "--event-id",
            "audit_recovery_test",
            "--action",
            "backup.restore",
            "--subject-id",
            "backup_20260801T000000Z_aaaaaaaaaaaa",
            "--outcome",
            "succeeded",
        ],
    )
    backup_cli.main()
    monkeypatch.setattr(
        backup_cli,
        "database_url_from_environment",
        lambda: "postgresql://operator",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["backup-cli", "audit-flush", "--outbox", str(outbox)],
    )
    backup_cli.main()

    assert events[0] == {
        "id": "audit_recovery_test",
        "occurred_at": events[0]["occurred_at"],
        "actor": "operator",
        "action": "backup.restore",
        "outcome": "succeeded",
        "reason_code": None,
        "subject_type": "hosted_recovery",
        "subject_id": "backup_20260801T000000Z_aaaaaaaaaaaa",
        "details": {},
    }
    assert list(outbox.iterdir()) == []
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == (
        "recorded"
    )


def test_management_audit_outbox_survives_database_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class UnavailableStore:
        def __init__(self, _database_url: str) -> None:
            pass

        def append_management_audit_event_idempotent(
            self,
            _event: dict[str, object],
        ) -> None:
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(operator_audit, "PostgresManagementStore", UnavailableStore)
    outbox = tmp_path / "audit-outbox"
    staged = operator_audit.stage_operator_audit(
        outbox,
        event_id="audit_recovery_database_failure",
        actor="operator",
        action="backup.create",
        outcome="rejected",
        subject_id="backup-attempt-20260801T000000Z",
        reason_code="OPERATION_INTERRUPTED",
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        operator_audit.flush_operator_audits(outbox, "postgresql://operator")

    assert staged.is_file()


def test_acceptance_interruption_audit_uses_the_same_durable_outbox(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    class Store:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://operator"

        def append_management_audit_event_idempotent(
            self,
            event: dict[str, object],
        ) -> None:
            events.append(event)

    monkeypatch.setattr(operator_audit, "PostgresManagementStore", Store)
    outbox = tmp_path / "audit-outbox"
    staged = operator_audit.stage_operator_audit(
        outbox,
        event_id="audit_acceptance_stop_test",
        actor="operator",
        action="acceptance.service.interrupt",
        outcome="succeeded",
        subject_id="worker-1",
        reason_code=None,
    )

    assert staged.name == "audit_acceptance_stop_test.json"
    assert operator_audit.flush_operator_audits(
        outbox,
        "postgresql://operator",
    ) == 1
    assert events == [
        {
            "id": "audit_acceptance_stop_test",
            "occurred_at": events[0]["occurred_at"],
            "actor": "operator",
            "action": "acceptance.service.interrupt",
            "outcome": "succeeded",
            "reason_code": None,
            "subject_type": "hosted_acceptance",
            "subject_id": "worker-1",
            "details": {},
        }
    ]
    assert list(outbox.iterdir()) == []


def test_recovery_lock_rejects_a_concurrent_operator_and_records_busy(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "recovery.lock"
    first = backup_cli._acquire_recovery_lock(lock_path)
    try:
        with pytest.raises(backup_cli.RecoveryOperationBusy):
            backup_cli._acquire_recovery_lock(lock_path)
    finally:
        os.close(first)


def test_recovery_lock_survives_exec_and_busy_attempt_is_audited(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "recovery.lock"
    outbox = tmp_path / "audit-outbox"
    ready = tmp_path / "ready"
    common = [
        sys.executable,
        "-m",
        "thesistrace.hosted.backup_cli",
        "lock-run",
        "--lock",
        str(lock_path),
        "--outbox",
        str(outbox),
        "--action",
        "backup.create",
        "--subject-id",
        "recovery-operation",
    ]
    holder = subprocess.Popen(
        [
            *common,
            "--event-id",
            "audit_recovery_holder",
            "--",
            sys.executable,
            "-c",
            "from pathlib import Path; import sys,time; "
            "Path(sys.argv[1]).write_text('ready'); time.sleep(2)",
            str(ready),
        ]
    )
    try:
        deadline = time.monotonic() + 1
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        contender = subprocess.run(
            [
                *common,
                "--event-id",
                "audit_recovery_contender",
                "--",
                sys.executable,
                "-c",
                "raise AssertionError('must not execute')",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        holder.wait(timeout=5)

    assert contender.returncode == 75
    busy = json.loads(
        (outbox / "audit_recovery_contender.json").read_bytes()
    )
    assert busy["outcome"] == "rejected"
    assert busy["reason_code"] == "RECOVERY_OPERATION_BUSY"


def test_audit_stage_fsyncs_file_and_directory(monkeypatch, tmp_path: Path) -> None:
    synced: list[int] = []
    real_fsync = operator_audit.os.fsync

    def recording_fsync(descriptor: int) -> None:
        synced.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(operator_audit.os, "fsync", recording_fsync)

    operator_audit.stage_operator_audit(
        tmp_path / "outbox",
        event_id="audit_recovery_fsync",
        actor="operator",
        action="backup.create",
        outcome="rejected",
        subject_id="backup-attempt-fsync",
        reason_code="OPERATION_INTERRUPTED",
    )

    assert len(synced) >= 2


def test_workflow_recovery_evidence_is_recorded_atomically(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    verification = tmp_path / "restore-verification.json"
    verification.write_text(
        '{"latest_dataset_release_id":"dsr_latest","verified_objects":4}'
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup-cli",
            "record-workflow-recovery",
            "--verification",
            str(verification),
            "--workflow-id",
            "recovery-probe-launch-exercise",
        ],
    )

    backup_cli.main()

    assert json.loads(verification.read_bytes()) == {
        "latest_dataset_release_id": "dsr_latest",
        "verified_objects": 4,
        "workflow_probe_id": "recovery-probe-launch-exercise",
        "workflow_recovery_verified": True,
    }
    assert not verification.with_suffix(".tmp").exists()
    assert json.loads(capsys.readouterr().out)["status"] == "recorded"
