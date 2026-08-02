import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def acceptance_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "release_acceptance.py"
    spec = importlib.util.spec_from_file_location("hosted_release_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def smtp_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "configure_smtp.py"
    spec = importlib.util.spec_from_file_location("hosted_configure_smtp", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_smoke_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted-release-smoke.py"
    spec = importlib.util.spec_from_file_location("hosted_release_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capacity_evidence(release_bundle_id: str) -> dict[str, object]:
    return {
        "release_bundle_id": release_bundle_id,
        "universe": "top3000",
        "compute_workers": [
            {
                "status": "succeeded",
                "activity_attempt": 1,
                "p99_memory_mib": 600,
                "peak_memory_mib": 650,
            }
            for _index in range(4)
        ],
        "dataset_publication": {
            "status": "succeeded",
            "worker_slot": "data-1",
            "activity_attempt": 1,
        },
        "nonworker_services": {"memory_limit_mib": 5120, "cpu_limit": 2},
        "swap_used": False,
        "oom_kill": False,
        "unexpected_restart": False,
        "missing_heartbeat": False,
        "duplicate_publication": False,
        "incorrect_result": False,
        "production_paths": {
            "parquet": True,
            "result_bundle": True,
            "working_cache": True,
            "postgresql": True,
            "temporal": True,
            "object_store": True,
        },
    }


def recovery_evidence(release_bundle_id: str) -> dict[str, object]:
    return {
        "format": "thesistrace-recovery-exercise-v1",
        "status": "passed",
        "release_bundle_id": release_bundle_id,
        "workflow_probe_id": "probe-1",
        "objectives": {
            "committed_state_loss_within_6h": True,
            "detection_within_24h": True,
            "public_origin_smoke": True,
            "recovery_execution_within_8h": True,
            "workflow_recovery": True,
        },
    }


def test_release_acceptance_rejects_stale_capacity_and_recovery_evidence(
    tmp_path: Path,
) -> None:
    module = acceptance_module()
    capacity = tmp_path / "capacity.json"
    recovery = tmp_path / "recovery.json"
    capacity.write_text(json.dumps(capacity_evidence("release-1")))
    recovery.write_text(json.dumps(recovery_evidence("release-1")))

    assert module.validate_capacity(capacity, "release-1")["status"] == "passed"
    assert module.validate_recovery(recovery, "release-1")["status"] == "passed"
    with pytest.raises(module.ReleaseAcceptanceError, match="another Release"):
        module.validate_capacity(capacity, "release-2")
    with pytest.raises(module.ReleaseAcceptanceError, match="another Release"):
        module.validate_recovery(recovery, "release-2")


def test_release_acceptance_names_every_exhaustion_and_recovery_boundary() -> None:
    module = acceptance_module()
    exhaustion = " ".join(module.resource_exhaustion_commands())
    assert "research_workflow" in exhaustion
    assert "dataset_publication_workflow" in exhaustion
    assert "tracking_workflow" in exhaustion
    assert "tracking_operations_workflow" in exhaustion
    assert "equivalence" in exhaustion or "tracking_operations" in exhaustion
    assert "rebuild" in exhaustion or "tracking_operations" in exhaustion

    recovery = " ".join(module.recovery_matrix_commands())
    for boundary in (
        "outbox",
        "relay",
        "activity_redelivery",
        "publication",
        "maintenance",
        "interrupted_deploy",
    ):
        assert boundary in recovery

    public_smoke = (ROOT / "scripts" / "hosted-release-smoke.py").read_text()
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    for boundary in (
        '"api"',
        '"execution-relay"',
        '"compute-worker-1"',
        '"data-worker"',
        '"maintenance-enter"',
        '"acceptance-restart-node"',
    ):
        assert boundary in public_smoke
    assert "compose stop --timeout 0" in launcher


def test_public_smoke_uses_the_published_anon_key_for_registration(monkeypatch) -> None:
    module = public_smoke_module()
    calls: list[tuple[str, str | None]] = []

    def fake_request(origin: str, path: str, *, token: str | None = None, **_kwargs):
        calls.append((path, token))
        if path == "/api/auth/anon-key":
            return 200, {"anonKey": "anon_acceptance"}
        return 200, {"accessToken": "registered"}

    monkeypatch.setattr(module, "request", fake_request)

    assert module.register_user("user@example.com", "password", "https://localhost") == (
        "registered",
        "anon_acceptance",
    )
    assert calls == [
        ("/api/auth/anon-key", None),
        ("/api/auth/users?client_type=server", "anon_acceptance"),
    ]


def test_private_acceptance_seeding_requires_an_explicit_mode() -> None:
    script = ROOT / "scripts" / "hosted" / "seed_acceptance_state.py"
    completed = subprocess.run(
        [sys.executable, str(script), "assert-clean"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "disabled" in completed.stderr

    launch_recorder = ROOT / "scripts" / "hosted" / "record_launch_qualification.py"
    completed = subprocess.run(
        [sys.executable, str(launch_recorder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "acceptance-only" in completed.stderr

    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    assert 'THESISTRACE_ACCEPTANCE_MODE:-0}" != "1"' in launcher
    assert "acceptance-record-launch)" in launcher
    assert 'THESISTRACE_COMPOSE_PROJECT_NAME:-thesistrace-hosted' in launcher


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


def test_release_acceptance_attests_evidence_with_the_host_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = acceptance_module()
    key_path = tmp_path / "secrets" / "launch_qualification_key"
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(b"release-acceptance-attestation-key")
    monkeypatch.setenv("THESISTRACE_HOST_STATE_DIR", str(tmp_path))

    attestation = module.attest_launch_evidence({"status": "passed"})

    assert len(attestation) == 64


def test_operator_runbook_covers_every_launch_operation() -> None:
    runbook = (ROOT / "docs" / "runbook" / "hosted-compose.md").read_text()
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
    assert "smtp-configure)" in launcher
    assert "/run/operator/smtp_password" in launcher
    assert "--smtp-password-file /run/operator/smtp_password" in launcher
    assert "--audit-outbox /run/operator/audit-outbox" in launcher
