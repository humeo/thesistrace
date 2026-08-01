import json
import sys
from pathlib import Path

import pytest

from thesistrace.hosted import backup_cli


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

    monkeypatch.setattr(backup_cli, "PostgresManagementStore", Store)
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

    monkeypatch.setattr(backup_cli, "PostgresManagementStore", UnavailableStore)
    outbox = tmp_path / "audit-outbox"
    staged = backup_cli._stage_recovery_audit(
        outbox,
        event_id="audit_recovery_database_failure",
        action="backup.create",
        outcome="rejected",
        subject_id="backup-attempt-20260801T000000Z",
        reason_code="OPERATION_INTERRUPTED",
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        backup_cli._flush_recovery_audits(outbox, "postgresql://operator")

    assert staged.is_file()


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
