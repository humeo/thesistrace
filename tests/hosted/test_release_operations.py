import asyncio
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings, settings_from_environment
from thesistrace.hosted.release_cli import TemporalMaintenanceControl
from thesistrace.hosted.release_gate import ReleaseGateError
from thesistrace.hosted.release_gate import main as release_gate_main
from thesistrace.hosted.release_operations import (
    MaintenanceCoordinator,
    ReleaseBundle,
    activate_candidate_release,
    activate_previous_release,
    install_release_bundle,
    open_recovery_bundle,
    provision_role_secrets,
    seal_recovery_bundle,
    stage_release_bundle,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeGate:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.events: list[str] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.events.append(f"gate:{enabled}")


class FakeSchedules:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def pause(self) -> None:
        self.events.append("schedules:paused")

    def resume(self) -> None:
        self.events.append("schedules:resumed")


class FakeActivities:
    def __init__(self, counts: list[int]) -> None:
        self.counts = counts

    def running_count(self) -> int:
        if len(self.counts) > 1:
            return self.counts.pop(0)
        return self.counts[0]


class FakeWorkers:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def stop_normally(self) -> None:
        self.events.append("workers:stopped")

    def start(self) -> None:
        self.events.append("workers:started")


class FakeAsyncItems:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def __aiter__(self):
        async def iterate():
            for item in self.items:
                yield item

        return iterate()


class FakeScheduleHandle:
    def __init__(self, events: list[str], schedule_id: str) -> None:
        self.events = events
        self.schedule_id = schedule_id

    async def pause(self, *, note: str) -> None:
        self.events.append(f"pause:{self.schedule_id}:{note}")

    async def unpause(self, *, note: str) -> None:
        self.events.append(f"unpause:{self.schedule_id}:{note}")


class FakeTemporalClient:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.workflow_queries: list[str] = []

    async def list_schedules(self) -> FakeAsyncItems:
        return FakeAsyncItems(
            [SimpleNamespace(id="daily-publication"), SimpleNamespace(id="tracking")]
        )

    def get_schedule_handle(self, schedule_id: str) -> FakeScheduleHandle:
        return FakeScheduleHandle(self.events, schedule_id)

    def list_workflows(self, query: str) -> FakeAsyncItems:
        self.workflow_queries.append(query)
        return FakeAsyncItems(
            [
                SimpleNamespace(id="workflow-1", run_id="run-1"),
                SimpleNamespace(id="workflow-2", run_id="run-2"),
            ]
        )

    def get_workflow_handle(self, workflow_id: str, *, run_id: str):
        assert (workflow_id, run_id) in {
            ("workflow-1", "run-1"),
            ("workflow-2", "run-2"),
        }
        pending_count = 2 if workflow_id == "workflow-1" else 1

        class Handle:
            async def describe(self):
                return SimpleNamespace(
                    raw_description=SimpleNamespace(
                        pending_activities=[object()] * pending_count
                    )
                )

        return Handle()


def test_release_manifest_pins_every_compatible_component() -> None:
    bundle = ReleaseBundle.from_manifest(ROOT / "deploy" / "hosted" / "release.json", ROOT)
    assert set(bundle.components) == {
        "web",
        "caddy",
        "api",
        "worker",
        "insforge",
        "temporal",
        "product_migrations",
        "configuration",
    }
    assert bundle.compatibility_epoch == "hosted-v2-expand-contract-1"
    assert len(bundle.manifest_sha256) == 64
    assert bundle.components["api"]["artifact"] == (
        f"thesistrace/app:{bundle.bundle_id}"
    )
    assert bundle.components["web"]["artifact"] == (
        f"thesistrace/edge:{bundle.bundle_id}"
    )


def test_temporal_maintenance_pauses_every_listed_schedule() -> None:
    client = FakeTemporalClient()

    count = asyncio.run(TemporalMaintenanceControl(client).pause_schedules())

    assert count == 2
    assert client.events == [
        "pause:daily-publication:ThesisTrace release maintenance",
        "pause:tracking:ThesisTrace release maintenance",
    ]


def test_temporal_maintenance_resumes_every_listed_schedule() -> None:
    client = FakeTemporalClient()

    count = asyncio.run(TemporalMaintenanceControl(client).resume_schedules())

    assert count == 2
    assert client.events == [
        "unpause:daily-publication:ThesisTrace release maintenance complete",
        "unpause:tracking:ThesisTrace release maintenance complete",
    ]


def test_temporal_maintenance_counts_pending_activities_in_running_workflows() -> None:
    client = FakeTemporalClient()

    count = asyncio.run(TemporalMaintenanceControl(client).running_activity_count())

    assert count == 3
    assert client.workflow_queries == [
        'ExecutionStatus="Running" AND ('
        'WorkflowType="DatasetPublicationWorkflow" OR '
        'WorkflowType="ScheduledDatasetPublicationWorkflow" OR '
        'WorkflowType="ResearchWorkflow" OR '
        'WorkflowType="TrackingReleaseWorkflow" OR '
        'WorkflowType="TrackingAdvanceWorkflow" OR '
        'WorkflowType="TrackingEquivalenceWorkflow" OR '
        'WorkflowType="TrackingGenerationRebuildWorkflow")'
    ]


def test_release_bundle_install_is_immutable_and_retains_one_previous(
    tmp_path: Path,
) -> None:
    source = ROOT / "deploy" / "hosted" / "release.json"
    first = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.0")
    second = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.1")

    first_id = install_release_bundle(tmp_path, first)
    assert install_release_bundle(tmp_path, first) == first_id
    second_id = install_release_bundle(tmp_path, second)

    current = json.loads((tmp_path / "current.json").read_text())
    previous = json.loads((tmp_path / "previous.json").read_text())
    assert current["bundle_id"] == second_id
    assert previous["bundle_id"] == first_id
    assert len(list((tmp_path / "bundles").glob("*/bundle.json"))) == 2


def test_staged_release_does_not_replace_current_until_activation(
    tmp_path: Path,
) -> None:
    source = ROOT / "deploy" / "hosted" / "release.json"
    first = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.0")
    second = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.1")
    first_id = install_release_bundle(tmp_path, first)

    second_id = stage_release_bundle(tmp_path, second)

    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == first_id
    assert json.loads((tmp_path / "candidate.json").read_text())["bundle_id"] == second_id
    assert not (tmp_path / "previous.json").exists()

    assert activate_candidate_release(tmp_path) == {
        "status": "activated",
        "bundle_id": second_id,
    }
    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == second_id
    assert json.loads((tmp_path / "previous.json").read_text())["bundle_id"] == first_id
    assert not (tmp_path / "candidate.json").exists()


def test_release_gate_rejects_unpinned_or_modified_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = ReleaseBundle.from_manifest(
        ROOT / "deploy" / "hosted" / "release.json",
        ROOT,
    )
    bundle_id = install_release_bundle(tmp_path, bundle)
    monkeypatch.setenv("THESISTRACE_RELEASE_VERSION", bundle.version)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ID", bundle_id)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ROOT", str(tmp_path))
    release_gate_main()

    path = tmp_path / "bundles" / bundle_id / "bundle.json"
    path.chmod(0o600)
    changed = json.loads(path.read_text())
    changed["components"]["api"]["version"] = "modified"
    path.write_text(json.dumps(changed))
    try:
        release_gate_main()
    except ReleaseGateError as error:
        assert "checksum" in str(error)
    else:
        raise AssertionError("modified release bundle passed the release gate")


def test_release_gate_accepts_staged_candidate_without_changing_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = ROOT / "deploy" / "hosted" / "release.json"
    current = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.0")
    candidate = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.1")
    current_id = install_release_bundle(tmp_path, current)
    candidate_id = stage_release_bundle(tmp_path, candidate)
    monkeypatch.setenv("THESISTRACE_RELEASE_VERSION", candidate.version)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ID", candidate_id)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ROOT", str(tmp_path))

    release_gate_main()

    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == current_id


def test_rollback_activates_only_the_immediately_previous_compatible_bundle(
    tmp_path: Path,
) -> None:
    source = ROOT / "deploy" / "hosted" / "release.json"
    first = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.0")
    second = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.1")
    first_id = install_release_bundle(tmp_path, first)
    install_release_bundle(tmp_path, second)

    stage_release_bundle(
        tmp_path,
        ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.2"),
    )
    result = activate_previous_release(tmp_path)
    assert result == {"status": "activated", "bundle_id": first_id}
    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == first_id
    assert not (tmp_path / "candidate.json").exists()

    incompatible = ReleaseBundle.from_manifest(
        source,
        ROOT,
        version_override="3.0.0",
        compatibility_epoch_override="hosted-v3-breaking-1",
    )
    install_release_bundle(tmp_path, incompatible)
    assert activate_previous_release(tmp_path) == {
        "status": "restore_required",
        "reason": "persisted-data compatibility epoch changed",
    }


def test_maintenance_pauses_admission_and_schedules_then_drains_before_stop() -> None:
    events: list[str] = []
    gate = FakeGate()
    gate.events = events
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    coordinator = MaintenanceCoordinator(
        gate=gate,
        schedules=FakeSchedules(events),
        activities=FakeActivities([2, 1, 0]),
        workers=FakeWorkers(events),
        clock=lambda: now[0],
        sleep=sleep,
    )
    result = coordinator.enter(max_drain_seconds=900, poll_interval=5)

    assert result.drained is True
    assert result.remaining_activities == 0
    assert result.interrupted_activity_state == "none"
    assert events == ["gate:True", "schedules:paused", "workers:stopped"]
    assert now[0] == 10

    coordinator.exit()
    assert events[-3:] == ["workers:started", "schedules:resumed", "gate:False"]


def test_maintenance_timeout_leaves_activity_nonterminal_for_redelivery() -> None:
    events: list[str] = []
    gate = FakeGate()
    gate.events = events
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    result = MaintenanceCoordinator(
        gate=gate,
        schedules=FakeSchedules(events),
        activities=FakeActivities([1]),
        workers=FakeWorkers(events),
        clock=lambda: now[0],
        sleep=sleep,
    ).enter(max_drain_seconds=900, poll_interval=300)

    assert result.drained is False
    assert result.remaining_activities == 1
    assert result.interrupted_activity_state == "nonterminal_redelivery"
    assert now[0] == 900
    assert events[-1] == "workers:stopped"


def test_hosted_api_rejects_new_heavy_work_during_maintenance(tmp_path: Path) -> None:
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
        runtime_mode="local",
    )
    gate = FakeGate(enabled=True)
    with TestClient(create_app(settings, maintenance_gate=gate)) as client:
        response = client.post(
            "/api/v1/research-definitions/missing/runs",
            headers={"Idempotency-Key": "maintenance-test"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["reason_code"] == "MAINTENANCE_MODE"
        assert response.headers["Retry-After"] == "60"
        assert client.get("/api/v1/live").status_code == 200


def test_role_secrets_are_separate_mode_600_files_and_recovery_is_encrypted(
    tmp_path: Path,
) -> None:
    values = {
        "api_database_url": "postgresql://api:api-secret@postgres/db",
        "compute_database_url": "postgresql://compute:compute-secret@postgres/db",
        "tushare_token": "tushare-secret",
    }
    paths = provision_role_secrets(tmp_path / "secrets", values)
    assert set(paths) == set(values)
    for name, path in paths.items():
        assert path.read_text() == values[name]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.parent.name == "secrets"

    sealed = seal_recovery_bundle(
        tmp_path / "current.recovery",
        values,
        passphrase="recovery-passphrase",
    )
    payload = sealed.read_bytes()
    assert b"api-secret" not in payload
    assert b"tushare-secret" not in payload
    assert open_recovery_bundle(sealed, passphrase="recovery-passphrase") == values


def test_application_settings_load_role_secrets_from_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    password = tmp_path / "database-password"
    token = tmp_path / "object-token"
    password.write_text("p@ss word")
    token.write_text("object-secret")
    monkeypatch.delenv("THESISTRACE_DATABASE_URL", raising=False)
    monkeypatch.setenv("THESISTRACE_DATABASE_USER", "thesistrace_api")
    monkeypatch.setenv("THESISTRACE_DATABASE_PASSWORD_FILE", str(password))
    monkeypatch.setenv("THESISTRACE_OBJECT_STORE_TOKEN_FILE", str(token))

    settings = settings_from_environment()
    assert settings.database_url == (
        "postgresql://thesistrace_api:p%40ss%20word@postgres:5432/insforge"
    )
    assert settings.object_store_token == "object-secret"


def test_compose_contains_only_secret_file_references_not_secret_values() -> None:
    model = json.loads(
        subprocess.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(ROOT),
                "-f",
                str(ROOT / "deploy" / "hosted" / "compose.yaml"),
                "config",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    for service in model["services"].values():
        environment = service.get("environment", {})
        assert "change-me" not in json.dumps(environment)
        for key, value in environment.items():
            if any(marker in key for marker in ("PASSWORD", "TOKEN", "SECRET")):
                assert key.endswith("_FILE") or key.endswith("__FILE")
                assert str(value).startswith("/run/secrets/")


def test_compose_orders_all_one_shot_migrations_before_public_services() -> None:
    compose = (ROOT / "deploy" / "hosted" / "compose.yaml").read_text()
    for job in (
        "insforge-migrations:",
        "temporal-schema:",
        "thesistrace-migrations:",
        "release-gate:",
    ):
        assert job in compose
    assert "condition: service_completed_successfully" in compose
    assert "THESISTRACE_INJECT_MIGRATION_FAILURE" in compose
    assert "THESISTRACE_RELEASE_BUNDLE_ROOT" in compose
    assert "/run/thesistrace-release:ro" in compose

    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    assert "release_cli install-bundle" in launcher

    migration = (ROOT / "deploy" / "hosted" / "migrations" / "0021_platform_maintenance.sql")
    sql = migration.read_text()
    assert "platform_maintenance" in sql
    assert "maintenance_enabled" in sql
    relay = (ROOT / "src" / "thesistrace" / "hosted" / "execution_outbox.py").read_text()
    assert "maintenance_enabled" in relay
    assert "return []" in relay


def test_custom_images_and_launcher_use_the_immutable_release_bundle_id() -> None:
    compose = (ROOT / "deploy" / "hosted" / "compose.yaml").read_text()
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()

    assert compose.count("${THESISTRACE_RELEASE_BUNDLE_ID:-dev}") == 5
    assert "THESISTRACE_RELEASE_BUNDLE_ID" in launcher
    rollback_block = launcher.split("    rollback)", 1)[1].split("        ;;", 1)[0]
    assert "select_current_release" in rollback_block


def test_read_only_operations_do_not_install_a_new_release_bundle() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    prepare_block = launcher.split("prepare() {", 1)[1].split("\n}", 1)[0]
    smoke_block = launcher.split("    smoke)", 1)[1].split("        ;;", 1)[0]

    assert "release_cli install-bundle" not in prepare_block
    assert "select_current_release" in smoke_block
    assert "install_release" not in smoke_block


def test_existing_up_and_restart_never_rebuild_the_active_bundle() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    up_block = launcher.split("    up)", 1)[1].split("        ;;", 1)[0]
    restart_block = launcher.split("    restart)", 1)[1].split("        ;;", 1)[0]

    assert "if [ -f \"$release_state/current.json\" ]" in up_block
    assert "compose up --detach --wait --no-build" in up_block
    assert "compose up --build" not in restart_block
    assert "compose up --detach --wait --no-build" in restart_block


def test_maintenance_exit_restarts_only_workers_without_dependencies() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    exit_block = launcher.split("exit_maintenance() {", 1)[1].split("\n}", 1)[0]

    assert "compose up --detach --no-deps" in exit_block
    assert "compose start" not in exit_block


def test_compatible_rollback_does_not_rerun_migration_jobs() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    rollback_block = launcher.split("    rollback)", 1)[1].split("        ;;", 1)[0]

    assert (
        "compose up --no-start --force-recreate --no-build --no-deps"
        in rollback_block
    )
    assert "compose up --detach --wait --no-build --no-deps" in rollback_block
    for migration_service in (
        "insforge-migrations",
        "temporal-schema",
        "thesistrace-migrations",
        "release-gate",
    ):
        assert migration_service not in rollback_block
    assert "insforge deno" in rollback_block


def test_forward_deploy_drains_old_bundle_before_installing_new_bundle() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    deploy_block = launcher.split("    deploy)", 1)[1].split("        ;;", 1)[0]

    assert deploy_block.index("enter_maintenance") < deploy_block.index("stage_release")
    assert "compose build" in deploy_block
    migration_phase, steady_phase = deploy_block.split(
        "compose up --detach --wait --no-build --no-deps", 1
    )
    assert "release-gate" in migration_phase
    assert "api edge" not in migration_phase
    assert "api edge" in steady_phase
    assert "compose up --no-start --force-recreate --no-build --no-deps" in deploy_block
    assert deploy_block.index("activate_candidate") > deploy_block.index("compose build")
    assert deploy_block.rindex("exit_maintenance") > deploy_block.index(
        "activate_candidate"
    )
