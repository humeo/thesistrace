import importlib.util
import json
import os
import stat
import subprocess
import urllib.error
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from thesistrace.launch import (
    LaunchQualificationError,
    LaunchQualificationService,
    launch_attestation,
    launch_failures,
)

ROOT = Path(__file__).resolve().parents[2]


def local_acceptance_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "local_acceptance.py"
    spec = importlib.util.spec_from_file_location("hosted_local_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_smoke_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted-release-smoke.py"
    spec = importlib.util.spec_from_file_location("hosted_release_smoke_local", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_public_smoke_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted-local-smoke.py"
    spec = importlib.util.spec_from_file_location("hosted_local_public_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_postgres_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "local_postgres_acceptance.py"
    spec = importlib.util.spec_from_file_location("hosted_local_postgres", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_boundary_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "local_boundary_acceptance.py"
    spec = importlib.util.spec_from_file_location("hosted_local_boundary", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_recovery_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "local_recovery_acceptance.py"
    spec = importlib.util.spec_from_file_location("hosted_local_recovery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_ops_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "local_ops_probe.py"
    spec = importlib.util.spec_from_file_location("hosted_local_ops", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_acceptance_module() -> ModuleType:
    path = ROOT / "scripts" / "hosted" / "release_acceptance.py"
    spec = importlib.util.spec_from_file_location("hosted_release_acceptance_local", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(module: ModuleType, tmp_path: Path):
    return module.parser().parse_args(
        [
            "--output",
            str(tmp_path / "local-evidence.json"),
            "--state-dir",
            str(tmp_path / "state"),
            "--project",
            "thesistrace-hosted-local-test",
        ]
    )


def parse_arguments(module: ModuleType, tmp_path: Path, *extra: str):
    return module.parser().parse_args(
        [
            "--output",
            str(tmp_path / "local-evidence.json"),
            "--state-dir",
            str(tmp_path / "state"),
            "--project",
            "thesistrace-hosted-local-test",
            *extra,
        ]
    )


def runtime_capacity() -> dict[str, object]:
    return {
        "source": "docker-info",
        "logical_cpu": 2,
        "memory_bytes": 4_109_938_688,
    }


def stable_runtime_state(_environment) -> dict[str, object]:
    return {"runtime": "stable"}


def test_local_gate_selection_supports_one_gate_or_one_contiguous_range(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    exact = module.select_phases(
        parse_arguments(module, tmp_path, "--phase", "identity_product")
    )
    ranged = module.select_phases(
        parse_arguments(
            module,
            tmp_path,
            "--from",
            "api_relay_recovery",
            "--until",
            "publication_recovery",
        )
    )

    assert [phase.name for phase in exact] == ["identity_product"]
    assert [phase.name for phase in ranged] == [
        "api_relay_recovery",
        "compute_recovery",
        "publication_recovery",
    ]


def test_local_gate_selection_rejects_mixed_or_reversed_selectors(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    with pytest.raises(SystemExit):
        parse_arguments(
            module,
            tmp_path,
            "--phase",
            "identity_product",
            "--from",
            "identity_product",
        )
    with pytest.raises(module.LocalAcceptanceError, match="canonical order"):
        module.select_phases(
            parse_arguments(
                module,
                tmp_path,
                "--from",
                "publication_recovery",
                "--until",
                "api_relay_recovery",
            )
        )


def test_local_gate_requires_prerequisites_from_the_same_session(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    calls: list[str] = []

    def executor(phase, environment):
        calls.append(phase.name)
        return {"status": "passed"}, {"status": "passed"}

    module.run_acceptance(
        parse_arguments(
            module,
            tmp_path,
            "--phase",
            "reset",
            "--cleanup-policy",
            "never",
        ),
        executor=executor,
        runtime_reader=runtime_capacity,
        fingerprint_reader=lambda: {"source_sha256": "a" * 64},
        state_reader=lambda _environment: {"runtime": "reset"},
    )

    with pytest.raises(module.LocalAcceptanceError, match="core_session"):
        module.run_acceptance(
            parse_arguments(
                module,
                tmp_path,
                "--phase",
                "identity_product",
                "--cleanup-policy",
                "never",
            ),
            executor=executor,
            runtime_reader=runtime_capacity,
            fingerprint_reader=lambda: {"source_sha256": "a" * 64},
            state_reader=lambda _environment: {"runtime": "reset"},
        )

    assert calls == ["reset"]


def test_local_gate_failure_preserves_state_unless_cleanup_is_explicit(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    calls: list[str] = []

    def executor(phase, environment):
        calls.append(phase.name)
        if phase.name == "core_session":
            raise module.LocalAcceptanceError("core failed")
        return {"status": "passed"}, {"status": "passed"}

    common = {
        "executor": executor,
        "runtime_reader": runtime_capacity,
        "fingerprint_reader": lambda: {"source_sha256": "a" * 64},
        "state_reader": lambda _environment: {"runtime": "stable"},
    }
    module.run_acceptance(
        parse_arguments(
            module,
            tmp_path,
            "--phase",
            "reset",
            "--cleanup-policy",
            "never",
        ),
        **common,
    )

    with pytest.raises(module.LocalAcceptanceError, match="core failed"):
        module.run_acceptance(
            parse_arguments(
                module,
                tmp_path,
                "--phase",
                "core_session",
                "--cleanup-policy",
                "never",
            ),
            **common,
        )
    preserved = json.loads((tmp_path / "local-evidence.json").read_text())
    assert calls == ["reset", "core_session"]
    assert preserved["diagnostics"]["preserved"] is True
    assert "--phase core_session" in preserved["diagnostics"]["retry_command"]
    assert "--cleanup" in preserved["diagnostics"]["cleanup_command"]
    manifest = json.loads(
        module.session_manifest_path(arguments(module, tmp_path)).read_text()
    )
    assert manifest["gates"]["core_session"]["status"] == "failed"
    assert manifest["current_state_digest"] == manifest["gates"]["core_session"][
        "output_state_digest"
    ]

    calls.clear()
    with pytest.raises(module.LocalAcceptanceError, match="core failed"):
        module.run_acceptance(
            parse_arguments(
                module,
                tmp_path,
                "--phase",
                "core_session",
                "--cleanup-policy",
                "always",
            ),
            **common,
        )
    assert calls == ["core_session", "cleanup"]


def test_explicit_cleanup_does_not_reclassify_old_runtime_health(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    common = {
        "runtime_reader": runtime_capacity,
        "fingerprint_reader": lambda: {"source_sha256": "a" * 64},
        "state_reader": stable_runtime_state,
    }
    module.run_acceptance(
        parse_arguments(module, tmp_path, "--phase", "reset"),
        executor=lambda _phase, _environment: (
            {"status": "passed"},
            {"status": "passed"},
        ),
        **common,
    )

    evidence = module.run_acceptance(
        parse_arguments(module, tmp_path, "--cleanup"),
        executor=lambda _phase, _environment: (
            {"status": "passed"},
            {
                "status": "passed",
                "resources": {
                    "sample_count": 1,
                    "unhealthy_containers": ["old-api"],
                },
            },
        ),
        **common,
    )

    assert evidence["status"] == "passed"
    assert evidence["runtime_observations"]["unhealthy_container"] is True


def test_local_gate_command_failure_writes_a_private_diagnostic_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = local_acceptance_module()

    class Sampler:
        def __init__(self, project):
            assert project == "thesistrace-hosted-local-test"

        def start(self):
            return None

        def stop(self):
            return {"sample_count": 1, "sampling_errors": []}

    class Completed:
        returncode = 7
        stdout = b"diagnostic stdout\n"
        stderr = b"diagnostic stderr\n"

    monkeypatch.setattr(module, "DockerPhaseSampler", Sampler)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Completed())
    environment = module.local_environment(
        parse_arguments(
            module,
            tmp_path,
            "--phase",
            "core_session",
            "--cleanup-policy",
            "never",
        )
    )

    with pytest.raises(module.PhaseExecutionError) as failed:
        module.execute_phase(module.Phase("core_session", ("false",), 10), environment)

    log_path = Path(failed.value.record["log_path"])
    assert log_path.read_bytes() == Completed.stdout + Completed.stderr
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    assert failed.value.record["status"] == "failed"
    assert failed.value.record["returncode"] == 7
    assert failed.value.record["resources"]["sample_count"] == 1
    assert failed.value.record["started_at"].endswith("+00:00")
    assert failed.value.record["completed_at"].endswith("+00:00")


def test_local_resume_runs_only_the_next_canonical_compatible_gate(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    calls: list[str] = []

    def executor(phase, environment):
        calls.append(phase.name)
        payload = {"status": "passed"}
        if phase.name == "core_session":
            payload["release_bundle_id"] = "release-local"
        return payload, {"status": "passed"}

    common = {
        "executor": executor,
        "runtime_reader": runtime_capacity,
        "fingerprint_reader": lambda: {"source_sha256": "a" * 64},
        "state_reader": lambda _environment: {"runtime": "stable"},
    }
    first = module.run_acceptance(
        parse_arguments(
            module,
            tmp_path,
            "--from",
            "reset",
            "--until",
            "core_session",
            "--cleanup-policy",
            "never",
        ),
        **common,
    )
    calls.clear()
    resumed = module.run_acceptance(
        parse_arguments(
            module,
            tmp_path,
            "--resume",
            "--cleanup-policy",
            "never",
        ),
        **common,
    )

    assert calls == ["identity_product"]
    assert resumed["selected_gates"] == ["identity_product"]
    assert resumed["run_id"] == first["run_id"]
    assert resumed["state_epoch"] == first["state_epoch"]
    manifest_path = module.session_manifest_path(arguments(module, tmp_path))
    manifest = json.loads(manifest_path.read_text())
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert manifest["release_bundle_id"] == "release-local"
    assert len(manifest["gates"]["core_session"]["input_state_digest"]) == 64
    assert len(manifest["gates"]["core_session"]["output_state_digest"]) == 64
    assert [record["gate"] for record in manifest["gate_history"]] == [
        "reset",
        "core_session",
        "identity_product",
    ]


def test_local_session_rejects_changed_inputs_or_runtime_state(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    def executor(phase, environment):
        return {"status": "passed"}, {"status": "passed"}

    module.run_acceptance(
        parse_arguments(module, tmp_path, "--phase", "reset"),
        executor=executor,
        runtime_reader=runtime_capacity,
        fingerprint_reader=lambda: {"source_sha256": "a" * 64},
        state_reader=lambda _environment: {"state": "before"},
    )

    with pytest.raises(module.LocalAcceptanceError, match="inputs changed"):
        module.run_acceptance(
            parse_arguments(module, tmp_path, "--phase", "core_session"),
            executor=executor,
            runtime_reader=runtime_capacity,
            fingerprint_reader=lambda: {"source_sha256": "b" * 64},
            state_reader=lambda _environment: {"state": "before"},
        )
    with pytest.raises(module.LocalAcceptanceError, match="input state differs"):
        module.run_acceptance(
            parse_arguments(module, tmp_path, "--phase", "core_session"),
            executor=executor,
            runtime_reader=runtime_capacity,
            fingerprint_reader=lambda: {"source_sha256": "a" * 64},
            state_reader=lambda _environment: {"state": "mutated"},
        )


def test_local_session_refuses_to_persist_authentication_material(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    with pytest.raises(module.LocalAcceptanceError, match="authentication material"):
        module.run_acceptance(
            parse_arguments(module, tmp_path, "--phase", "reset"),
            executor=lambda phase, environment: (
                {"status": "passed", "access_token": "must-not-persist"},
                {"status": "passed"},
            ),
            runtime_reader=runtime_capacity,
            fingerprint_reader=lambda: {"source_sha256": "a" * 64},
            state_reader=lambda _environment: {"state": "reset"},
        )

    manifest = module.session_manifest_path(arguments(module, tmp_path)).read_text()
    evidence = (tmp_path / "local-evidence.json").read_text()
    assert "must-not-persist" not in manifest
    assert "must-not-persist" not in evidence


def test_source_fingerprint_covers_untracked_inputs_but_excludes_runtime_outputs(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.py").write_text("value = 1\n")
    (tmp_path / "untracked.py").write_text("value = 2\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "tracked.py"],
        check=True,
    )

    before = module.source_fingerprint(tmp_path)
    (tmp_path / "untracked.py").write_text("value = 3\n")
    changed = module.source_fingerprint(tmp_path)
    runtime = tmp_path / ".hosted" / "evidence"
    runtime.mkdir(parents=True)
    (runtime / "result.json").write_text('{"status":"passed"}')
    excluded = module.source_fingerprint(tmp_path)

    assert before["files_sha256"] != changed["files_sha256"]
    assert changed == excluded
    assert ".hosted" in changed["excluded_roots"]


def test_release_core_and_harness_fingerprints_are_independent(tmp_path: Path) -> None:
    module = local_acceptance_module()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("release = 1\n")
    (tmp_path / "tests" / "test_runner.py").write_text("assert True\n")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "src/app.py", "tests/test_runner.py"],
        check=True,
    )

    core_before = module.source_fingerprint(tmp_path, include_roots=("src",))
    harness_before = module.source_fingerprint(tmp_path, include_roots=("tests",))
    (tmp_path / "tests" / "test_runner.py").write_text("assert 1 == 1\n")

    assert module.source_fingerprint(tmp_path, include_roots=("src",)) == core_before
    assert (
        module.source_fingerprint(tmp_path, include_roots=("tests",))
        != harness_before
    )


def test_harness_change_invalidates_evidence_without_destroying_core_state() -> None:
    module = local_acceptance_module()
    manifest = {
        "fingerprint": {
            "release_core": {"source": "release-a"},
            "harness": {"source": "harness-a"},
        },
        "current_state_digest": "runtime-after-failed-gate",
        "gates": {
            "reset": {"status": "passed", "output_state_digest": "reset"},
            "core_session": {"status": "passed", "output_state_digest": "core"},
            "identity_product": {
                "status": "failed",
                "output_state_digest": "runtime-after-failed-gate",
            },
        },
    }
    changed = {
        "release_core": {"source": "release-a"},
        "harness": {"source": "harness-b"},
    }

    assert module.reconcile_fingerprint(manifest, changed) == "harness"
    assert manifest["gates"]["core_session"]["status"] == "passed"
    assert manifest["gates"]["identity_product"]["status"] == "invalidated"
    assert manifest["current_state_digest"] == "runtime-after-failed-gate"
    assert manifest["fingerprint"] == changed


def test_release_core_change_requires_a_new_state_epoch() -> None:
    module = local_acceptance_module()
    manifest = {
        "fingerprint": {
            "release_core": {"source": "release-a"},
            "harness": {"source": "harness-a"},
        },
        "gates": {"core_session": {"status": "passed"}},
    }

    assert (
        module.reconcile_fingerprint(
            manifest,
            {
                "release_core": {"source": "release-b"},
                "harness": {"source": "harness-a"},
            },
        )
        == "release_core"
    )
    assert manifest["gates"]["core_session"]["status"] == "passed"


def test_state_mismatch_invalidates_the_gate_and_every_later_checkpoint(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    def stable(_environment):
        return {"state": "stable"}

    common = {
        "executor": lambda phase, environment: (
            {
                "status": "passed",
                **(
                    {"release_bundle_id": "release-local"}
                    if phase.name == "core_session"
                    else {}
                ),
            },
            {"status": "passed"},
        ),
        "runtime_reader": runtime_capacity,
        "fingerprint_reader": lambda: {"source_sha256": "a" * 64},
    }
    module.run_acceptance(
        parse_arguments(
            module,
            tmp_path,
            "--from",
            "reset",
            "--until",
            "identity_product",
        ),
        state_reader=stable,
        **common,
    )

    with pytest.raises(module.LocalAcceptanceError, match="input state differs"):
        module.run_acceptance(
            parse_arguments(module, tmp_path, "--phase", "core_session"),
            state_reader=lambda _environment: {"state": "externally-mutated"},
            **common,
        )

    manifest = json.loads(
        module.session_manifest_path(arguments(module, tmp_path)).read_text()
    )
    assert manifest["gates"]["reset"]["status"] == "passed"
    assert manifest["gates"]["core_session"]["status"] == "invalidated"
    assert manifest["gates"]["identity_product"]["status"] == "invalidated"


def test_reset_derives_a_unique_guarded_compose_project_when_unspecified(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    arguments_without_project = module.parser().parse_args(
        [
            "--output",
            str(tmp_path / "local-evidence.json"),
            "--state-dir",
            str(tmp_path / "state"),
            "--phase",
            "reset",
        ]
    )
    projects: list[str] = []

    module.run_acceptance(
        arguments_without_project,
        executor=lambda phase, environment: (
            projects.append(environment["THESISTRACE_COMPOSE_PROJECT_NAME"])
            or {"status": "passed"},
            {"status": "passed"},
        ),
        runtime_reader=runtime_capacity,
        fingerprint_reader=lambda: {"source_sha256": "a" * 64},
        state_reader=lambda environment: {
            "project": environment["THESISTRACE_COMPOSE_PROJECT_NAME"]
        },
    )

    assert len(projects) == 1
    assert projects[0].startswith("thesistrace-hosted-local-")
    assert projects[0] != "thesistrace-hosted-local"
    manifest = json.loads(module.session_manifest_path(arguments_without_project).read_text())
    assert manifest["project"] == projects[0]


def test_local_project_guard_rejects_a_non_acceptance_compose_project(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    with pytest.raises(module.LocalAcceptanceError, match="project name"):
        module.run_acceptance(
            parse_arguments(module, tmp_path, "--phase", "reset").__class__(
                **{
                    **vars(parse_arguments(module, tmp_path, "--phase", "reset")),
                    "project": "thesistrace-production",
                }
            ),
            executor=lambda phase, environment: (
                {"status": "passed"},
                {"status": "passed"},
            ),
            runtime_reader=runtime_capacity,
            fingerprint_reader=lambda: {"source_sha256": "a" * 64},
            state_reader=lambda _environment: {},
        )


def test_core_session_state_rejects_extra_compute_or_observability_services() -> None:
    module = local_acceptance_module()
    valid = {
        "release": {
            "bundle_id": "release-local",
            "web_asset_manifest": {"/": "a" * 64},
        },
        "authoritative_state": {"latest_dataset_release_id": None, "objects": []},
        "topology": [
            {"service": "api"},
            {"service": "execution-relay"},
            {"service": "compute-worker-1"},
            {"service": "data-worker"},
            {"service": "postgres"},
            {"service": "temporal"},
        ],
    }

    assert module.validate_core_runtime_state(valid, "release-local") == {
        "bundle_id": "release-local"
    }
    with pytest.raises(module.LocalAcceptanceError, match="Web asset"):
        module.validate_core_runtime_state(
            {**valid, "release": {"bundle_id": "release-local"}},
            "release-local",
        )
    for forbidden in ("compute-worker-2", "otel-collector", "prometheus", "grafana"):
        with pytest.raises(module.LocalAcceptanceError, match=forbidden):
            module.validate_core_runtime_state(
                {**valid, "topology": [*valid["topology"], {"service": forbidden}]},
                "release-local",
            )


def test_reusable_core_keeps_release_and_source_authorization_state() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    local_up = launcher.split("    local-up)", 1)[1].split("        ;;", 1)[0]
    local_reset = launcher.split("    local-reset)", 1)[1].split("        ;;", 1)[0]
    seed = launcher.split("seed_local_source_authorization()", 1)[1].split("}\n", 1)[0]

    assert 'if [ -f "$release_state/current.json" ]' in local_up
    assert "release_images verify-images" in local_up
    assert local_up.count("stage_release") == 1
    assert local_up.count("build_candidate_images") == 1
    assert "local core convergence failed once" in local_up
    assert "local-source-authorization" in seed
    assert 'sed -n \'1p\' "$marker"' in seed
    assert 'mv "$marker.tmp" "$marker"' in seed
    assert 'rm -f -- "$state_dir/local-source-authorization"' in local_reset


def test_local_acceptance_writes_distinct_non_launch_evidence(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def executor(phase, environment):
        calls.append((phase.name, phase.command))
        payload: dict[str, object] = {"status": "passed"}
        if phase.name == "core_session":
            payload["release_bundle_id"] = "release-local"
        return payload, {
            "status": "passed",
            "elapsed_seconds": 0.01,
            "output_sha256": "0" * 64,
        }

    evidence = module.run_acceptance(
        arguments(module, tmp_path),
        executor=executor,
        runtime_reader=runtime_capacity,
        state_reader=stable_runtime_state,
    )

    assert [name for name, _command in calls] == [
        "reset",
        "core_session",
        "identity_product",
        "postgres_edge_storage",
        "api_relay_recovery",
        "compute_recovery",
        "publication_recovery",
        "controlled_workflows",
        "operational_health",
        "local_recovery",
        "browser_ready",
        "frontend_browser",
    ]
    assert evidence["schema_version"] == "hosted-v2-local-v1"
    assert evidence["status"] == "passed"
    assert evidence["launch_qualified"] is False
    assert evidence["release_bundle_id"] == "release-local"
    assert evidence["runtime_capacity"] == runtime_capacity()
    assert evidence["production_only_not_claimed"] == [
        "capacity_qualification",
        "cloudflare",
        "co_resident_maximum_load",
        "external_dns_tls",
        "off_node_recovery",
        "production_invitation_admission",
        "production_rto_rpo",
        "real_smtp_delivery",
        "whole_node_resilience",
    ]
    assert launch_failures(evidence)
    serialized_commands = " ".join(" ".join(command) for _name, command in calls)
    assert "acceptance-record-launch" not in serialized_commands
    assert "capacity-qualification" not in serialized_commands
    assert "hosted-release-acceptance" not in serialized_commands
    assert json.loads(arguments(module, tmp_path).output.read_text()) == evidence


def test_clean_final_run_executes_every_gate_once_without_checkpoint_reuse(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    calls: list[str] = []

    def executor(phase, environment):
        calls.append(phase.name)
        payload = {"status": "passed"}
        if phase.name == "core_session":
            payload["release_bundle_id"] = "release-local"
        return payload, {"status": "passed"}

    evidence = module.run_acceptance(
        parse_arguments(
            module,
            tmp_path,
            "--fresh",
            "--cleanup-policy",
            "on-success",
        ),
        executor=executor,
        runtime_reader=runtime_capacity,
        fingerprint_reader=lambda: {"source_sha256": "a" * 64},
        state_reader=stable_runtime_state,
    )

    assert calls == [*module.CANONICAL_GATE_NAMES, "cleanup"]
    assert evidence["clean_run"] is True
    assert evidence["checkpoint_reused"] is False
    assert evidence["selected_gates"] == list(module.CANONICAL_GATE_NAMES)
    assert evidence["records"]["cleanup"]["status"] == "passed"


def test_local_recovery_gates_each_cover_a_real_heartbeat_window() -> None:
    module = local_acceptance_module()
    phases = {phase.name: phase for phase in module.local_phases()}

    assert phases["compute_recovery"].timeout_seconds == 900
    assert phases["publication_recovery"].timeout_seconds == 900


def test_local_acceptance_records_the_first_failure_and_preserves_by_default(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()
    calls: list[str] = []

    def executor(phase, environment):
        calls.append(phase.name)
        if phase.name == "identity_product":
            raise module.LocalAcceptanceError("public boundary failed")
        payload = {"status": "passed"}
        if phase.name == "core_session":
            payload["release_bundle_id"] = "release-local"
        return payload, {"status": "passed"}

    with pytest.raises(module.LocalAcceptanceError, match="public boundary failed"):
        module.run_acceptance(
            arguments(module, tmp_path),
            executor=executor,
            runtime_reader=runtime_capacity,
            state_reader=stable_runtime_state,
        )

    assert calls == ["reset", "core_session", "identity_product"]
    evidence = json.loads(arguments(module, tmp_path).output.read_text())
    assert evidence["status"] == "failed"
    assert evidence["launch_qualified"] is False
    assert evidence["failure"] == {
        "phase": "identity_product",
        "message": "public boundary failed",
    }
    assert evidence["diagnostics"]["preserved"] is True


def test_local_acceptance_records_an_operator_interrupt_before_exit(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    def executor(phase, environment):
        if phase.name == "identity_product":
            raise KeyboardInterrupt
        payload = {"status": "passed"}
        if phase.name == "core_session":
            payload["release_bundle_id"] = "release-local"
        return payload, {"status": "passed"}

    with pytest.raises(module.LocalAcceptanceError, match="operator signal"):
        module.run_acceptance(
            arguments(module, tmp_path),
            executor=executor,
            runtime_reader=runtime_capacity,
            state_reader=stable_runtime_state,
        )

    evidence = json.loads(arguments(module, tmp_path).output.read_text())
    assert evidence["failure"]["phase"] == "identity_product"
    assert evidence["diagnostics"]["preserved"] is True


def test_local_acceptance_rejects_a_runtime_smaller_than_2c4g(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    with pytest.raises(module.LocalAcceptanceError, match="at least 2 logical CPU"):
        module.run_acceptance(
            arguments(module, tmp_path),
            executor=lambda *_arguments: ({"status": "passed"}, {}),
            runtime_reader=lambda: {
                "source": "docker-info",
                "logical_cpu": 1,
                "memory_bytes": 2 * 1024**3,
            },
        )

    evidence = json.loads(arguments(module, tmp_path).output.read_text())
    assert evidence["status"] == "failed"
    assert evidence["failure"]["phase"] == "preflight"


def test_public_origin_profiles_keep_launch_only_recovery_out_of_local_mode() -> None:
    module = public_smoke_module()

    launch = module.acceptance_profile("launch")
    local = module.acceptance_profile("local")

    assert launch.compute_services == (
        "compute-worker-1",
        "compute-worker-2",
        "compute-worker-3",
        "compute-worker-4",
    )
    assert launch.whole_node_recovery is True
    assert launch.backup_and_three_health_planes is True
    assert launch.invitation_gate_reason == "LAUNCH_QUALIFICATION_REQUIRED"
    assert local.compute_services == ("compute-worker-1",)
    assert local.whole_node_recovery is False
    assert local.backup_and_three_health_planes is False
    assert local.invitation_gate_reason == "CAPACITY_QUALIFICATION_REQUIRED"


def test_public_origin_poll_fails_fast_on_a_terminal_failed_state() -> None:
    module = public_smoke_module()

    with pytest.raises(module.AcceptanceFailure, match="failed before convergence"):
        module.poll(
            lambda: (200, {"advances": [{"id": "advance-1", "status": "failed"}]}),
            lambda value: any(
                item.get("status") == "succeeded"
                for item in value.get("advances", [])
            ),
            "DailyTrack Advance",
            terminal_failure=lambda value: any(
                item.get("status") == "failed"
                for item in value.get("advances", [])
            ),
        )


def test_local_ops_accepts_only_the_explicit_launch_only_system_gaps() -> None:
    module = local_ops_module()
    views = {
        "system": {
            "status": "degraded",
            "checks": {
                "api": True,
                "backup": False,
                "workflow_capacity": False,
            },
        },
        "data": {"status": "available", "checks": {"schema": True}},
        "quantitative": {
            "status": "available",
            "checks": {"deterministic_regression": True},
        },
    }

    assert module.validate_local_health_views(views) == {
        "backup",
        "workflow_capacity",
    }
    views["system"]["checks"]["api"] = False
    with pytest.raises(module.LocalOperationalHealthError, match="unexpected"):
        module.validate_local_health_views(views)


def test_local_ops_reports_the_failing_endpoint_name_and_url(monkeypatch) -> None:
    module = local_ops_module()
    url = "http://otel-collector:8888/metrics"

    def refuse(_url: str, *, timeout: int):
        assert timeout == 10
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", refuse)

    with pytest.raises(
        module.LocalOperationalHealthError,
        match=r"collector .*otel-collector:8888/metrics.*connection refused",
    ):
        module.read_url("collector", url)


def test_local_public_smoke_is_distinct_and_reuses_the_real_product_flow() -> None:
    script = (ROOT / "scripts" / "hosted-local-smoke.py").read_text()

    for gate in (
        "identity-product",
        "api-relay-recovery",
        "compute-recovery",
        "publication-recovery",
    ):
        assert gate in script
    assert "hosted-local-public-origin-gate-v1" in script
    assert "acceptance-record-launch" not in script
    assert "capacity-qualification" not in script


def test_local_public_smoke_dispatches_exactly_one_named_gate(monkeypatch) -> None:
    module = local_public_smoke_module()
    calls: list[str] = []

    class ReleaseSmoke:
        def run_local_identity_product(self):
            calls.append("identity-product")
            return {"status": "passed", "gate": "identity-product"}

        def run_local_api_relay_recovery(self):
            calls.append("api-relay-recovery")
            return {"status": "passed", "gate": "api-relay-recovery"}

        def run_local_compute_recovery(self):
            calls.append("compute-recovery")
            return {"status": "passed", "gate": "compute-recovery"}

        def run_local_publication_recovery(self):
            calls.append("publication-recovery")
            return {"status": "passed", "gate": "publication-recovery"}

    monkeypatch.setattr(module, "release_smoke_module", lambda: ReleaseSmoke())

    evidence = module.run_gate("compute-recovery")

    assert calls == ["compute-recovery"]
    assert evidence == {"status": "passed", "gate": "compute-recovery"}


def test_local_api_relay_gate_never_stops_a_compute_or_data_worker() -> None:
    script = (ROOT / "scripts" / "hosted-release-smoke.py").read_text()
    gate = script.split("def run_local_api_relay_recovery()", 1)[1].split(
        "def run_local_compute_recovery()", 1
    )[0]

    assert 'acceptance-stop-service", "execution-relay"' in gate
    assert 'acceptance-stop-service", "compute-worker' not in gate
    assert 'acceptance-stop-service", "data-worker' not in gate


def test_local_product_context_keeps_credentials_private_and_rejects_tokens(
    tmp_path: Path,
) -> None:
    module = public_smoke_module()
    credentials = {
        "email_a": "user-a@example.invalid",
        "password_a": "acceptance-only-a",
        "email_b": "user-b@example.invalid",
        "password_b": "acceptance-only-b",
    }
    product = {"workspace_a": "workspace-a", "run_id": "run-a"}

    module.write_local_acceptance_context(tmp_path, credentials, product)
    loaded_credentials, loaded_product = module.read_local_acceptance_context(tmp_path)

    assert loaded_credentials == credentials
    assert loaded_product == product
    for name in ("public-origin-credentials.json", "public-origin-context.json"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    with pytest.raises(module.AcceptanceFailure, match="token"):
        module.write_local_acceptance_context(
            tmp_path,
            credentials,
            {**product, "access_token": "forbidden"},
        )


def test_local_postgres_acceptance_uses_an_isolated_real_database(
    tmp_path: Path,
) -> None:
    module = local_postgres_module()
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "postgres_password").write_text("local-db-secret")
    lifecycle: list[tuple[str, str]] = []
    test_environments: list[dict[str, str]] = []

    def database_lifecycle(operation: str, admin_info: str, database_name: str):
        lifecycle.append((operation, database_name))
        assert "host=127.0.0.1" in admin_info
        assert "port=25432" in admin_info
        assert "password=local-db-secret" in admin_info

    def test_runner(command: tuple[str, ...], environment: dict[str, str]):
        test_environments.append(environment)
        assert command[:4] == ("uv", "run", "pytest", "-q")
        assert set(command[4:]) == set(module.postgres_test_targets())
        return b"3 passed in 1.00s"

    evidence = module.run_postgres_acceptance(
        state_dir=tmp_path,
        port=25432,
        database_lifecycle=database_lifecycle,
        test_runner=test_runner,
    )

    assert lifecycle == [
        ("recreate", "thesistrace_local_acceptance_test"),
        ("drop", "thesistrace_local_acceptance_test"),
    ]
    assert "dbname=thesistrace_local_acceptance_test" in (
        test_environments[0]["THESISTRACE_TEST_DATABASE_URL"]
    )
    assert evidence["status"] == "passed"
    assert evidence["database"] == "isolated-runtime-postgresql"
    assert evidence["tests"] == list(module.postgres_test_targets())
    assert "local-db-secret" not in json.dumps(evidence)


def test_local_boundary_gate_combines_isolated_postgres_and_controlled_security() -> None:
    module = local_boundary_module()
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]):
        calls.append(command)
        if command[1].endswith("local_postgres_acceptance.py"):
            return b'{"status":"passed","database":"isolated-runtime-postgresql"}\n'
        return b"12 passed in 1.00s\n"

    evidence = module.run_boundary_acceptance(runner=runner)

    assert len(calls) == 1 + len(module.CONTROLLED_TARGETS)
    assert calls[0][0].endswith("python")
    for target in (
        "tests/hosted/test_edge_policy.py",
        "tests/hosted/test_edge_rate_limits.py",
        "tests/hosted/test_container_boundaries.py",
        "tests/hosted/test_storage_admission.py",
        "tests/hosted/test_object_store_boundary.py",
        "tests/hosted/test_health_views.py",
    ):
        assert any(target in " ".join(call) for call in calls[1:])
    assert evidence["status"] == "passed"
    assert evidence["schema_version"] == "hosted-local-boundary-v1"
    assert evidence["postgresql"]["database"] == "isolated-runtime-postgresql"
    assert set(evidence["controlled_tests"]) == set(module.CONTROLLED_TARGETS)


def test_local_resource_sampler_records_per_phase_peaks_and_failures() -> None:
    module = local_acceptance_module()
    sampler = module.DockerPhaseSampler("thesistrace-hosted-local-test")

    sampler.observe_snapshot(
        {
            "api": {
                "memory_bytes": 100,
                "cpu_percent": 10.0,
                "swap_peak_bytes": 0,
                "restart_count": 0,
                "oom_killed": False,
                "health": "healthy",
            },
            "compute-worker-1": {
                "memory_bytes": 300,
                "cpu_percent": 80.0,
                "swap_peak_bytes": 0,
                "restart_count": 0,
                "oom_killed": False,
                "health": "healthy",
            },
        }
    )
    sampler.observe_snapshot(
        {
            "api": {
                "memory_bytes": 200,
                "cpu_percent": 20.0,
                "swap_peak_bytes": 4096,
                "restart_count": 1,
                "oom_killed": True,
                "health": "unhealthy",
            }
        }
    )

    summary = sampler.summary()
    assert summary["sample_count"] == 2
    assert summary["peak_memory_bytes"] == 400
    assert summary["peak_cpu_percent"] == 90.0
    assert summary["peak_swap_bytes"] == 4096
    assert summary["unexpected_restart_containers"] == ["api"]
    assert summary["oom_killed_containers"] == ["api"]
    assert summary["unhealthy_containers"] == ["api"]
    assert summary["container_peaks"]["compute-worker-1"]["memory_bytes"] == 300


def test_local_resource_sampler_does_not_exec_when_swap_is_disabled_by_docker() -> None:
    module = local_acceptance_module()

    class Client:
        def project_containers(self, project):
            assert project == "thesistrace-hosted-local-test"
            return [{"Id": "container-1", "Names": ["/api"]}]

        def container_json(self, container_id, endpoint):
            assert container_id == "container-1"
            if endpoint == "json":
                return {
                    "State": {
                        "Running": True,
                        "OOMKilled": False,
                        "Health": {"Status": "healthy"},
                    },
                    "HostConfig": {"Memory": 512, "MemorySwap": 512},
                    "RestartCount": 0,
                }
            assert endpoint == "stats?stream=false&one-shot=true"
            return {
                "memory_stats": {"usage": 100, "stats": {"inactive_file": 20}},
                "cpu_stats": {},
                "precpu_stats": {},
            }

        def container_swap_peak(self, container_id):
            raise AssertionError("swap-disabled containers must not create Docker execs")

    snapshot = module.docker_project_snapshot(
        "thesistrace-hosted-local-test",
        client=Client(),
    )

    assert snapshot["api"]["memory_bytes"] == 80
    assert snapshot["api"]["swap_peak_bytes"] == 0


def test_local_acceptance_fails_closed_on_unsafe_runtime_observations(
    tmp_path: Path,
) -> None:
    module = local_acceptance_module()

    def executor(phase, environment):
        resources = {
            "sample_count": 1,
            "peak_memory_bytes": 100,
            "peak_cpu_percent": 1.0,
            "peak_swap_bytes": 0,
            "unexpected_restart_containers": [],
            "oom_killed_containers": ["compute-worker-1"]
            if phase.name == "compute_recovery"
            else [],
            "unhealthy_containers": [],
            "sampling_errors": [],
        }
        payload = {"status": "passed"}
        if phase.name == "core_session":
            payload["release_bundle_id"] = "release-local"
        return payload, {"status": "passed", "resources": resources}

    with pytest.raises(module.LocalAcceptanceError, match="OOM kill"):
        module.run_acceptance(
            arguments(module, tmp_path),
            executor=executor,
            runtime_reader=runtime_capacity,
            state_reader=stable_runtime_state,
        )

    evidence = json.loads(arguments(module, tmp_path).output.read_text())
    assert evidence["status"] == "failed"
    assert evidence["failure"]["phase"] == "runtime_observations"
    assert evidence["runtime_observations"]["oom_kill"] is True
    assert evidence["launch_qualified"] is False


def test_local_recovery_proves_cold_restart_and_disposable_restore() -> None:
    module = local_recovery_module()
    calls: list[str] = []
    context = {
        "state_epoch": "epoch-local",
        "release_bundle_id": "bundle-local",
        "release_pointer_sha256": "1" * 64,
        "release_bundle_sha256": "2" * 64,
        "migration_source_sha256": "3" * 64,
        "session_manifest_sha256": "4" * 64,
        "product_context_sha256": "5" * 64,
        "snapshot_sha256": "6" * 64,
    }
    snapshot = {
        "latest_dataset_release_id": "release-local",
        "objects": [{"object_key": "content:abc", "sha256": "a" * 64}],
    }

    class Operations:
        def capture_backup(self):
            calls.append("capture_backup")
            return snapshot, {
                "database_dump_sha256": "b" * 64,
                "backup_bytes": 1234,
                **context,
            }

        def cold_restart_and_smoke(self):
            calls.append("cold_restart_and_smoke")

        def live_snapshot(self):
            calls.append("live_snapshot")
            return snapshot

        def restore_and_verify(self, expected_snapshot):
            calls.append("restore_and_verify")
            assert expected_snapshot == snapshot
            return {"latest_dataset_release_id": "release-local", "verified_objects": 1}

        def cleanup(self):
            calls.append("cleanup")

    evidence = module.run_local_recovery(Operations())

    assert calls == [
        "capture_backup",
        "cold_restart_and_smoke",
        "live_snapshot",
        "restore_and_verify",
        "cleanup",
    ]
    assert evidence["status"] == "passed"
    assert evidence["schema_version"] == "hosted-local-recovery-v1"
    assert evidence["cold_restart"] is True
    assert evidence["database_restore"] == "disposable-runtime-postgresql"
    assert evidence["authoritative_state_survived"] is True
    assert evidence["object_index_and_payload_verified"] is True
    assert evidence["latest_dataset_release_id"] == "release-local"
    assert evidence["verified_objects"] == 1
    assert evidence["database_dump_sha256"] == "b" * 64
    assert evidence["backup_bytes"] == 1234
    assert evidence["recovery_context"] == context
    assert set(evidence["durations_seconds"]) == {
        "backup",
        "cold_restart_and_product_smoke",
        "disposable_restore_and_verification",
    }
    assert evidence["off_node"] is False
    assert evidence["production_rpo_rto_claimed"] is False
    assert evidence["whole_node_resilience_claimed"] is False


def test_local_recovery_fails_when_authoritative_state_changes_and_cleans_up() -> None:
    module = local_recovery_module()
    cleaned: list[bool] = []

    class Operations:
        def capture_backup(self):
            return (
                {"latest_dataset_release_id": "before", "objects": []},
                {
                    "database_dump_sha256": "b" * 64,
                    "backup_bytes": 1,
                    "state_epoch": "epoch",
                    "release_bundle_id": "bundle",
                    "release_pointer_sha256": "1" * 64,
                    "release_bundle_sha256": "2" * 64,
                    "migration_source_sha256": "3" * 64,
                    "session_manifest_sha256": "4" * 64,
                    "product_context_sha256": "5" * 64,
                    "snapshot_sha256": "6" * 64,
                },
            )

        def cold_restart_and_smoke(self):
            return None

        def live_snapshot(self):
            return {"latest_dataset_release_id": "after", "objects": []}

        def restore_and_verify(self, expected_snapshot):
            raise AssertionError("restore must not run after state drift")

        def cleanup(self):
            cleaned.append(True)

    with pytest.raises(module.LocalRecoveryAcceptanceError, match="cold restart"):
        module.run_local_recovery(Operations())

    assert cleaned == [True]


def test_every_production_evidence_consumer_rejects_local_evidence(
    tmp_path: Path,
) -> None:
    evidence = {
        "schema_version": "hosted-v2-local-v1",
        "status": "passed",
        "launch_qualified": False,
        "release_bundle_id": "release-local",
        "records": {},
    }
    recorded: list[object] = []

    class Store:
        def record_launch_qualification(self, qualification, audit_event):
            recorded.append((qualification, audit_event))

        def latest_launch_qualification(self):
            return None

    key = b"local-evidence-rejection-key-32b"
    with pytest.raises(LaunchQualificationError) as rejected:
        LaunchQualificationService(Store()).record(
            actor="release-acceptance",
            release_bundle_id="release-local",
            evidence=evidence,
            attestation=launch_attestation(evidence, key),
            attestation_key=key,
        )

    assert rejected.value.reason_code == "LAUNCH_QUALIFICATION_LOCAL_EVIDENCE_FORBIDDEN"
    assert recorded == []
    path = tmp_path / "local-evidence.json"
    path.write_text(json.dumps(evidence))
    release = release_acceptance_module()
    with pytest.raises(release.ReleaseAcceptanceError, match="capacity evidence failed"):
        release.validate_capacity(path, "release-local")
    with pytest.raises(release.ReleaseAcceptanceError, match="recovery evidence"):
        release.validate_recovery(path, "release-local")


def test_local_compose_profile_keeps_heavy_and_operational_phases_separate() -> None:
    environment = {
        **os.environ,
        "THESISTRACE_LOCAL_POSTGRES_PORT": "25432",
    }
    composed = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--project-directory",
                str(ROOT),
                "--file",
                str(ROOT / "deploy" / "hosted" / "compose.yaml"),
                "--file",
                str(ROOT / "deploy" / "hosted" / "compose.local.yaml"),
                "--profile",
                "*",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
        )
    )
    services = composed["services"]

    assert services["compute-worker-1"].get("profiles") is None
    assert services["data-worker"].get("profiles") is None
    for name in ("compute-worker-2", "compute-worker-3", "compute-worker-4"):
        assert services[name]["profiles"] == ["launch-capacity"]
    for name in ("otel-collector", "prometheus", "grafana"):
        assert services[name]["profiles"] == ["local-ops"]
    assert services["postgres"]["ports"] == [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "target": 5432,
            "published": "25432",
            "protocol": "tcp",
        }
    ]
    assert set(services["postgres"]["networks"]) == {"control", "local-admin"}
    assert composed["networks"]["local-admin"].get("internal", False) is False


def test_hosted_stack_exposes_local_actions_behind_an_explicit_gate() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()

    assert 'THESISTRACE_LOCAL_ACCEPTANCE:-0}' in launcher
    assert "local_compose()" in launcher
    assert "seed_local_source_authorization()" in launcher
    assert "local-source-authorization" in launcher
    local_up = launcher.split("    local-up)", 1)[1].split("        ;;", 1)[0]
    assert local_up.count("stage_release") == 1
    assert 'if [ -f "$release_state/current.json" ]' in local_up
    assert "release_images verify-images" in local_up
    assert "local core convergence failed once" in local_up
    assert local_up.count("local_compose up --detach --wait --no-build") == 2
    local_reset = launcher.split("    local-reset)", 1)[1].split("        ;;", 1)[0]
    assert "reset_local_release_state" in local_reset
    for action in (
        "local-reset)",
        "local-up)",
        "local-ops-check)",
        "local-recovery-smoke)",
        "local-browser-ready)",
        "local-down)",
    ):
        assert action in launcher


def test_local_frontend_checks_run_after_the_browser_preflight() -> None:
    module = local_acceptance_module()
    phases = module.local_phases()
    names = [phase.name for phase in phases]
    makefile = (ROOT / "Makefile").read_text()

    assert names.index("browser_ready") < names.index("frontend_browser")
    assert "hosted-local-frontend:" in makefile
    assert "hosted-local-acceptance:" in makefile
    acceptance_target = makefile.split("hosted-local-acceptance:", 1)[1]
    assert "scripts/hosted/local_acceptance.py" in acceptance_target
    assert "HOSTED_LOCAL_EVIDENCE" in acceptance_target
    target = makefile.split("hosted-local-frontend:", 1)[1]
    assert "scripts/hosted/local_frontend_acceptance.py" in target


def test_browser_preflight_keeps_the_product_core_online() -> None:
    launcher = (ROOT / "scripts" / "hosted-stack").read_text()
    action = launcher.split("    local-browser-ready)", 1)[1].split(
        "        ;;", 1
    )[0]

    assert "assert-idle" in action
    assert "grafana prometheus otel-collector" in action
    for service in ("api", "caddy", "compute-worker-1", "data-worker"):
        assert f"stop --timeout 30 {service}" not in action


def test_resource_sampler_requires_swap_only_for_running_containers() -> None:
    module = local_acceptance_module()
    sampler = module.DockerPhaseSampler("acceptance")

    sampler.observe_snapshot(
        {
            "stopped-job": {
                "running": False,
                "swap_peak_bytes": None,
            },
            "running-api": {
                "running": True,
                "swap_peak_bytes": None,
            },
        }
    )

    assert sampler.swap_unavailable_containers == {"running-api"}
    assert module.RESOURCE_SAMPLE_INTERVAL_SECONDS == 30.0


def test_local_controlled_suites_cover_heartbeat_health_and_telemetry_redaction() -> None:
    module = local_acceptance_module()
    commands = {
        phase.name: " ".join(phase.command)
        for phase in module.local_phases()
    }

    assert "local_workflow_acceptance.py" in commands["controlled_workflows"]
    controlled = (
        ROOT / "scripts" / "hosted" / "local_workflow_acceptance.py"
    ).read_text()
    assert "tests/hosted/test_temporal_worker_heartbeat.py" in controlled
    assert "physical_capacity_claimed" in controlled
    probe = (ROOT / "scripts" / "hosted" / "local_ops_probe.py").read_text()
    for endpoint in (
        "http://otel-collector:8888/metrics",
        "http://prometheus:9090/-/ready",
        "http://grafana:3000/api/health",
    ):
        assert endpoint in probe
    assert "telemetry_redaction" in probe


def test_local_ops_overlay_gives_cold_start_services_a_bounded_bootstrap_budget() -> None:
    overlay = yaml.safe_load(
        (ROOT / "deploy" / "hosted" / "compose.local.yaml").read_text()
    )
    services = overlay["services"]

    assert services["otel-collector"]["mem_limit"] == "256m"
    assert services["grafana"]["mem_limit"] == "384m"
    assert services["grafana"]["cpus"] == 0.25
