import asyncio
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import thesistrace.hosted.release_cli as release_cli
from thesistrace.api import create_app
from thesistrace.config import Settings, settings_from_environment
from thesistrace.hosted.release_cli import TemporalMaintenanceControl, enter_maintenance
from thesistrace.hosted.release_gate import ReleaseGateError
from thesistrace.hosted.release_gate import main as release_gate_main
from thesistrace.hosted.release_operations import (
    ReleaseBundle,
    ReleaseOperationError,
    activate_candidate_release,
    activate_previous_release,
    lock_release_images,
    open_recovery_bundle,
    seal_recovery_bundle,
    stage_release_bundle,
    verify_release_image_lock,
)

ROOT = Path(__file__).resolve().parents[2]
def release_test_images(bundle_id: str) -> dict[str, str]:
    return {
        f"thesistrace/app:{bundle_id}": f"sha256:{'a' * 64}",
        f"thesistrace/edge:{bundle_id}": f"sha256:{'b' * 64}",
        f"thesistrace/insforge:{bundle_id}": f"sha256:{'c' * 64}",
        f"thesistrace/insforge-deno:{bundle_id}": f"sha256:{'d' * 64}",
    }


def activate_bundle(state_root: Path, bundle: ReleaseBundle) -> str:
    staged_id = stage_release_bundle(state_root, bundle)
    locked = lock_release_images(
        state_root,
        staged_id,
        release_test_images(staged_id),
    )
    bundle_id = str(locked["bundle_id"])
    activate_candidate_release(state_root)
    return bundle_id


class FakeGate:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.events: list[str] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.events.append(f"gate:{enabled}")


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
    assert set(bundle.custom_images) == set(release_test_images(bundle.bundle_id))


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


def test_release_bundle_activation_is_immutable_and_retains_one_previous(
    tmp_path: Path,
) -> None:
    source = ROOT / "deploy" / "hosted" / "release.json"
    first = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.0")
    second = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.1")

    first_id = activate_bundle(tmp_path, first)
    assert activate_bundle(tmp_path, first) == first_id
    second_id = activate_bundle(tmp_path, second)

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
    first_id = activate_bundle(tmp_path, first)

    second_id = stage_release_bundle(tmp_path, second)

    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == first_id
    assert json.loads((tmp_path / "candidate.json").read_text())["bundle_id"] == second_id
    assert not (tmp_path / "previous.json").exists()

    locked = lock_release_images(
        tmp_path,
        second_id,
        release_test_images(second_id),
    )
    finalized_second_id = str(locked["bundle_id"])
    assert activate_candidate_release(tmp_path) == {
        "status": "activated",
        "bundle_id": finalized_second_id,
    }
    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == (
        finalized_second_id
    )
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
    bundle_id = activate_bundle(tmp_path, bundle)
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
    current_id = activate_bundle(tmp_path, current)
    candidate_id = stage_release_bundle(tmp_path, candidate)
    locked = lock_release_images(
        tmp_path,
        candidate_id,
        release_test_images(candidate_id),
    )
    candidate_id = str(locked["bundle_id"])
    monkeypatch.setenv("THESISTRACE_RELEASE_VERSION", candidate.version)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ID", candidate_id)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ROOT", str(tmp_path))

    release_gate_main()

    assert json.loads((tmp_path / "current.json").read_text())["bundle_id"] == current_id


def test_release_gate_rejects_modified_configuration_or_image_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = ReleaseBundle.from_manifest(
        ROOT / "deploy" / "hosted" / "release.json",
        ROOT,
    )
    bundle_id = activate_bundle(tmp_path, bundle)
    monkeypatch.setenv("THESISTRACE_RELEASE_VERSION", bundle.version)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ID", bundle_id)
    monkeypatch.setenv("THESISTRACE_RELEASE_BUNDLE_ROOT", str(tmp_path))

    configuration = (
        tmp_path
        / "bundles"
        / bundle_id
        / "configuration"
        / "deploy"
        / "hosted"
        / "compose.yaml"
    )
    original_configuration = configuration.read_bytes()
    configuration.chmod(0o600)
    configuration.write_bytes(original_configuration + b"\n# modified\n")
    with pytest.raises(ReleaseGateError, match="configuration snapshot"):
        release_gate_main()

    configuration.write_bytes(original_configuration)
    configuration.chmod(0o444)
    image_lock = tmp_path / "bundles" / bundle_id / "image-lock.json"
    image_lock.chmod(0o600)
    changed = json.loads(image_lock.read_text())
    first_image = next(iter(changed["images"]))
    changed["images"][first_image] = f"sha256:{'f' * 64}"
    image_lock.write_text(json.dumps(changed))
    with pytest.raises(ReleaseGateError, match="image lock"):
        release_gate_main()


def test_rollback_activates_only_the_immediately_previous_compatible_bundle(
    tmp_path: Path,
) -> None:
    source = ROOT / "deploy" / "hosted" / "release.json"
    first = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.0")
    second = ReleaseBundle.from_manifest(source, ROOT, version_override="2.0.1")
    first_id = activate_bundle(tmp_path, first)
    activate_bundle(tmp_path, second)

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
    activate_bundle(tmp_path, incompatible)
    assert activate_previous_release(tmp_path) == {
        "status": "restore_required",
        "reason": "persisted-data compatibility epoch changed",
    }


def test_real_maintenance_cli_drains_then_reports_nonterminal_timeout(monkeypatch) -> None:
    gate = FakeGate()
    now = [0.0]

    class Temporal:
        async def pause_schedules(self) -> int:
            return 2

        async def running_activity_count(self) -> int:
            return 1

    async def connect(*_args, **_kwargs):
        return object()

    async def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(release_cli, "database_url_from_environment", lambda: "postgres://db")
    monkeypatch.setattr(release_cli, "PostgresMaintenanceGate", lambda _url: gate)
    monkeypatch.setattr(release_cli, "Client", SimpleNamespace(connect=connect))
    monkeypatch.setattr(release_cli, "TemporalMaintenanceControl", lambda _client: Temporal())
    monkeypatch.setattr(release_cli.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(release_cli.asyncio, "sleep", sleep)

    result = asyncio.run(enter_maintenance(5))

    assert result == {
        "maintenance": "entered",
        "paused_schedules": 2,
        "drained": False,
        "remaining_activities": 1,
        "interrupted_activity_state": "nonterminal_redelivery",
    }
    assert gate.events == ["gate:True"]
    assert now[0] == 5


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
        equivalence = client.post(
            "/api/v1/daily-tracks/missing/equivalence-requests",
            headers={"Idempotency-Key": "maintenance-equivalence-test"},
        )
        assert equivalence.status_code == 503
        assert equivalence.json()["detail"]["reason_code"] == "MAINTENANCE_MODE"
        assert client.get("/api/v1/live").status_code == 200


def test_recovery_bundle_is_mode_600_and_encrypted(
    tmp_path: Path,
) -> None:
    values = {
        "api_database_url": "postgresql://api:api-secret@postgres/db",
        "compute_database_url": "postgresql://compute:compute-secret@postgres/db",
        "tushare_token": "tushare-secret",
    }
    sealed = seal_recovery_bundle(
        tmp_path / "current.recovery",
        values,
        passphrase="recovery-passphrase",
    )
    payload = sealed.read_bytes()
    assert stat.S_IMODE(sealed.stat().st_mode) == 0o600
    assert b"api-secret" not in payload
    assert b"tushare-secret" not in payload
    assert open_recovery_bundle(sealed, passphrase="recovery-passphrase") == values


def test_release_bundle_snapshots_configuration_and_locks_image_digests(
    tmp_path: Path,
) -> None:
    bundle = ReleaseBundle.from_manifest(
        ROOT / "deploy" / "hosted" / "release.json",
        ROOT,
    )
    bundle_id = stage_release_bundle(tmp_path, bundle)
    snapshot = (
        tmp_path
        / "bundles"
        / bundle_id
        / "configuration"
        / "deploy"
        / "hosted"
        / "compose.yaml"
    )
    assert snapshot.read_bytes() == (ROOT / "deploy" / "hosted" / "compose.yaml").read_bytes()
    entrypoint = snapshot.parent / "secret-entrypoint.sh"
    assert stat.S_IMODE(entrypoint.stat().st_mode) == 0o555

    with pytest.raises(ReleaseOperationError, match="image lock"):
        activate_candidate_release(tmp_path)
    images = release_test_images(bundle_id)
    locked = lock_release_images(tmp_path, bundle_id, images)
    bundle_id = str(locked["bundle_id"])
    finalized_images = dict(locked["images"])
    assert verify_release_image_lock(
        tmp_path,
        bundle_id,
        finalized_images,
    )["images"] == finalized_images
    changed_images = dict(finalized_images)
    app_image = next(
        image for image in changed_images if image.startswith("thesistrace/app:")
    )
    changed_images[app_image] = f"sha256:{'e' * 64}"
    with pytest.raises(ReleaseOperationError, match="immutable image lock"):
        lock_release_images(
            tmp_path,
            bundle_id,
            changed_images,
        )


def test_release_bundle_identity_binds_exact_custom_image_ids(
    tmp_path: Path,
) -> None:
    bundle = ReleaseBundle.from_manifest(
        ROOT / "deploy" / "hosted" / "release.json",
        ROOT,
    )
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_staged_id = stage_release_bundle(first_root, bundle)
    second_staged_id = stage_release_bundle(second_root, bundle)
    assert first_staged_id == second_staged_id

    first = lock_release_images(
        first_root,
        first_staged_id,
        release_test_images(first_staged_id),
    )
    second_images = release_test_images(second_staged_id)
    second_images[f"thesistrace/app:{second_staged_id}"] = (
        f"sha256:{'e' * 64}"
    )
    second = lock_release_images(
        second_root,
        second_staged_id,
        second_images,
    )

    assert first["bundle_id"] != second["bundle_id"]
    finalized = json.loads(
        (
            first_root
            / "bundles"
            / str(first["bundle_id"])
            / "bundle.json"
        ).read_text()
    )
    assert finalized["image_ids"] == first["images"]
    assert finalized["image_tag"] == first["bundle_id"]
    assert set(finalized["image_ids"]) == set(
        release_test_images(str(first["bundle_id"]))
    )


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
    assert "release_cli stage-bundle" in launcher

    migration = (ROOT / "deploy" / "hosted" / "migrations" / "0021_platform_maintenance.sql")
    sql = migration.read_text()
    assert "platform_maintenance" in sql
    assert "maintenance_enabled" in sql
    relay = (ROOT / "src" / "thesistrace" / "hosted" / "execution_outbox.py").read_text()
    assert "maintenance_enabled" in relay
    assert "return []" in relay

    all_admission = (
        ROOT
        / "deploy"
        / "hosted"
        / "migrations"
        / "0022_block_all_publication_admission_in_maintenance.sql"
    ).read_text()
    assert "reject_dataset_publication_during_maintenance" in all_admission
    assert "NEW.trigger_kind" not in all_admission


def test_custom_images_and_launcher_use_the_immutable_release_bundle_id() -> None:
    compose = (ROOT / "deploy" / "hosted" / "compose.yaml").read_text()
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
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
            env={**os.environ, "THESISTRACE_RELEASE_BUNDLE_ID": "bundle-test"},
        ).stdout
    )

    custom_image_lines = [
        line.strip()
        for line in compose.splitlines()
        if line.strip().startswith("image: thesistrace/")
    ]
    assert custom_image_lines
    assert all(
        "${THESISTRACE_RELEASE_IMAGE_TAG:-dev}" in line
        for line in custom_image_lines
    )
    assert model["services"]["release-gate"]["environment"][
        "THESISTRACE_RELEASE_BUNDLE_ID"
    ] == "bundle-test"
    assert "THESISTRACE_RELEASE_BUNDLE_ID" in launcher
    assert "THESISTRACE_RELEASE_IMAGE_TAG" in launcher
    assert "lock-images" in launcher
    assert "verify-images" in launcher
    assert "THESISTRACE_RELEASE_CONFIG_ROOT" in launcher
    assert 'configuration/deploy/hosted"' in launcher
    assert 'compose_file="$release_config_root/compose.yaml"' in launcher
    rollback_block = launcher.split("    rollback)", 1)[1].split("        ;;", 1)[0]
    assert "select_current_release" in rollback_block


def test_read_only_operations_do_not_install_a_new_release_bundle() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    prepare_block = launcher.split("prepare() {", 1)[1].split("\n}", 1)[0]
    smoke_block = launcher.split("    smoke)", 1)[1].split("        ;;", 1)[0]

    assert "release_cli stage-bundle" not in prepare_block
    assert "select_current_release" in smoke_block
    assert "stage_release" not in smoke_block


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
    start_block = launcher.split("start_workers() {", 1)[1].split("\n}", 1)[0]
    exit_block = launcher.split("exit_maintenance() {", 1)[1].split("\n}", 1)[0]

    assert "start_workers" in exit_block
    assert "compose up --detach --no-deps" in start_block
    assert "compose start" not in start_block


def test_compatible_rollback_does_not_rerun_migration_jobs() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    rollback_block = launcher.split("    rollback)", 1)[1].split("        ;;", 1)[0]

    assert "recreate_steady_services" in rollback_block
    assert rollback_block.index("check-previous") < rollback_block.index(
        "select_release previous"
    )
    assert rollback_block.index("release_images verify-images") < rollback_block.index(
        "activate-previous"
    )
    for migration_service in (
        "insforge-migrations",
        "temporal-schema",
        "thesistrace-migrations",
        "release-gate",
    ):
        assert migration_service not in rollback_block


def test_release_recreates_every_configuration_consumer() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    recreate = launcher.split("recreate_steady_services() {", 1)[1].split(
        "\n}", 1
    )[0]
    for service in (
        "postgres",
        "temporal-postgres",
        "temporal",
        "postgrest",
        "deno",
        "insforge",
        "object-store",
        "tushare-egress",
        "otel-collector",
        "prometheus",
        "grafana",
        "api",
        "health-service",
        "edge",
        "execution-relay",
        "data-worker",
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
    ):
        assert service in recreate
    assert "--force-recreate --no-build --no-deps" in recreate


def test_forward_deploy_drains_old_bundle_before_installing_new_bundle() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    deploy_block = launcher.split("    deploy)", 1)[1].split("        ;;", 1)[0]

    assert deploy_block.index("enter_maintenance") < deploy_block.index("stage_release")
    assert "build_candidate_images" in deploy_block
    migration_phase, steady_phase = deploy_block.split("recreate_steady_services", 1)
    assert "release-gate" in migration_phase
    assert "api edge" not in migration_phase
    assert steady_phase
    assert deploy_block.index("activate_candidate") > deploy_block.index(
        "build_candidate_images"
    )
    assert deploy_block.rindex("exit_maintenance") > deploy_block.index(
        "activate_candidate"
    )
