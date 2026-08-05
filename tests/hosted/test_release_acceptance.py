import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]




def smtp_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "configure_smtp.py"
    spec = importlib.util.spec_from_file_location("hosted_configure_smtp", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module












def test_smtp_configuration_keeps_credentials_out_of_result(
    tmp_path: Path,
) -> None:
    module = smtp_module()
    config = tmp_path / "smtp.json"
    smtp_password = tmp_path / "smtp-password"
    admin_password = tmp_path / "admin-password"
    config.write_text(
        json.dumps(
            {
                "enabled": True,
                "host": "smtp.example.com",
                "port": 587,
                "username": "mailer@example.com",
                "senderEmail": "research@example.com",
                "senderName": "ThesisTrace",
                "minIntervalSeconds": 60,
            }
        ),
        encoding="utf-8",
    )
    smtp_password.write_text("smtp-secret", encoding="utf-8")
    admin_password.write_text("admin-secret", encoding="utf-8")
    requests: list[tuple[str, dict[str, object]]] = []

    def requester(
        url: str,
        payload: dict[str, object],
        token: str | None = None,
    ) -> dict[str, object]:
        requests.append((url, payload))
        if url.endswith("/api/auth/admin/sessions"):
            assert payload["password"] == "admin-secret"
            return {"accessToken": "admin-token"}
        assert token == "admin-token"
        assert payload["password"] == "smtp-secret"
        return {
            "enabled": True,
            "host": "smtp.example.com",
            "port": 587,
            "username": "mailer@example.com",
            "senderEmail": "research@example.com",
            "senderName": "ThesisTrace",
            "minIntervalSeconds": 60,
            "hasPassword": True,
        }

    result = module.configure_smtp(
        config_path=config,
        smtp_password_path=smtp_password,
        admin_password_path=admin_password,
        admin_username="admin",
        origin="http://insforge:7130",
        requester=requester,
    )

    assert result == {
        "enabled": True,
        "has_password": True,
        "host": "smtp.example.com",
        "port": 587,
        "sender_email": "research@example.com",
    }
    assert len(requests) == 2


def test_smtp_configuration_appends_a_sanitized_operator_audit(
    tmp_path: Path,
) -> None:
    module = smtp_module()
    outbox = tmp_path / "audit-outbox"

    module.record_smtp_audit(
        outbox=outbox,
        event_id="audit_operator_smtp_test",
        actor="operator-1",
        outcome="succeeded",
        reason_code=None,
    )

    event = json.loads((outbox / "audit_operator_smtp_test.json").read_bytes())
    assert event["actor"] == "operator-1"
    assert event["action"] == "smtp.configure"
    assert event["subject_type"] == "smtp_configuration"
    assert "password" not in json.dumps(event).casefold()


def test_smtp_configuration_stages_a_durable_audit_before_remote_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = smtp_module()
    outbox = tmp_path / "audit-outbox"
    recorded: list[dict[str, object]] = []

    class Store:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://operator"

        def append_management_audit_event_idempotent(self, event) -> None:
            recorded.append(event)

    def configure(**_kwargs):
        provisional = json.loads(next(outbox.iterdir()).read_bytes())
        assert provisional["outcome"] == "rejected"
        assert provisional["reason_code"] == "OPERATION_INTERRUPTED"
        return {
            "enabled": True,
            "has_password": True,
            "host": "smtp.example.com",
            "port": 587,
            "sender_email": "research@example.com",
        }

    monkeypatch.setattr(module, "database_url_from_environment", lambda: "postgresql://operator")
    monkeypatch.setattr(module, "configure_smtp", configure)
    monkeypatch.setattr(
        "thesistrace.hosted.operator_audit.PostgresManagementStore",
        Store,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure-smtp",
            "--config",
            str(tmp_path / "smtp.json"),
            "--smtp-password-file",
            str(tmp_path / "smtp-password"),
            "--admin-password-file",
            str(tmp_path / "admin-password"),
            "--actor",
            "operator-1",
            "--audit-outbox",
            str(outbox),
        ],
    )

    module.main()

    assert recorded[0]["outcome"] == "succeeded"
    assert list(outbox.iterdir()) == []




def test_operator_runbook_marks_hosted_launch_as_archived() -> None:
    runbook = (ROOT / "docs" / "runbook" / "hosted-compose.md").read_text()
    assert "Archived Hosted Compose operations" in runbook
    assert "not an active product or verification contract" in runbook
    for contract in (
        "hosted-smtp-configure",
        "source-authorization record",
        "invitation issue",
        "dataset-publication request",
        "quota override",
        "hosted-maintenance-enter",
        "hosted-rollback",
        "hosted-backup",
        "hosted-restore",
        "hosted-release-acceptance",
        "ACTOR=operator-name",
        "THESISTRACE_TEST_DATABASE_URL",
        "does not provide high availability",
        "alert-delivery service",
    ):
        assert contract in runbook

    health = (ROOT / "docs" / "runbook" / "hosted-health.md").read_text()
    assert "Daily inspection" in health
    assert "no alert-delivery service" in health

    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    makefile = (ROOT / "Makefile").read_text()
    assert "hosted-release-acceptance:" not in makefile
    assert "hosted-local-acceptance:" not in makefile
    assert "acceptance-record-launch)" not in launcher
    assert "smtp-configure)" in launcher
    assert "/run/operator/smtp_password" in launcher
    assert "--smtp-password-file /run/operator/smtp_password" in launcher
    assert "--audit-outbox /run/operator/audit-outbox" in launcher
