import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from thesistrace.capacity import qualification_failures
from thesistrace.launch import REQUIRED_LAUNCH_CHECKS, launch_attestation
from thesistrace.objects import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "scripts" / "hosted-stack"


class ReleaseAcceptanceError(RuntimeError):
    pass


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run and record the complete Hosted V2 release boundary",
    )
    result.add_argument("--release-bundle-id", required=True)
    result.add_argument("--capacity-evidence", type=Path, required=True)
    result.add_argument("--recovery-evidence", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--actor", default="release-acceptance")
    return result


def execute_command(
    name: str,
    command: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
) -> tuple[str, dict[str, object]]:
    print(f"[{name}] {' '.join(command)}", flush=True)
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        tail = output[-8000:].decode("utf-8", errors="replace")
        raise ReleaseAcceptanceError(
            f"{name} failed with exit {completed.returncode}:\n{tail}"
        )
    print(f"[{name}] passed in {elapsed}s", flush=True)
    combined = output.decode("utf-8", errors="replace")
    return combined, {
        "status": "passed",
        "elapsed_seconds": elapsed,
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }


def run_command(
    name: str,
    command: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, object]:
    _output, record = execute_command(name, command, environment=environment)
    return record


def run_json_command(
    name: str,
    command: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    combined, record = execute_command(name, command, environment=environment)
    payload: dict[str, object] | None = None
    for line in reversed(combined.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if payload is None:
        raise ReleaseAcceptanceError(f"{name} returned no JSON evidence")
    return payload, record


def load_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseAcceptanceError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ReleaseAcceptanceError(f"{label} must be a JSON object")
    return value


def validate_capacity(
    path: Path,
    release_bundle_id: str,
) -> dict[str, object]:
    evidence = load_json(path, "capacity evidence")
    if evidence.get("release_bundle_id") != release_bundle_id:
        raise ReleaseAcceptanceError("capacity evidence belongs to another Release Bundle")
    failures = qualification_failures(evidence)
    if failures:
        raise ReleaseAcceptanceError(f"capacity evidence failed: {failures}")
    return {
        "status": "passed",
        "evidence_sha256": hashlib.sha256(canonical_json_bytes(evidence)).hexdigest(),
    }


def validate_recovery(
    path: Path,
    release_bundle_id: str,
) -> dict[str, object]:
    evidence = load_json(path, "recovery evidence")
    objectives = evidence.get("objectives")
    required = {
        "committed_state_loss_within_6h",
        "detection_within_24h",
        "public_origin_smoke",
        "recovery_execution_within_8h",
        "workflow_recovery",
    }
    if (
        evidence.get("format") != "thesistrace-recovery-exercise-v1"
        or evidence.get("status") != "passed"
        or evidence.get("release_bundle_id") != release_bundle_id
        or not isinstance(objectives, dict)
        or any(objectives.get(name) is not True for name in required)
        or not evidence.get("workflow_probe_id")
    ):
        raise ReleaseAcceptanceError(
            "recovery evidence is incomplete or belongs to another Release"
        )
    return {
        "status": "passed",
        "evidence_sha256": hashlib.sha256(canonical_json_bytes(evidence)).hexdigest(),
    }


def assert_clean_checkout() -> dict[str, object]:
    completed = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    if completed.stdout.strip():
        raise ReleaseAcceptanceError("release acceptance requires a clean checkout")
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {"status": "passed", "revision": revision}


def require_postgres_test_environment() -> dict[str, str]:
    database_url = os.environ.get("THESISTRACE_TEST_DATABASE_URL")
    if not database_url:
        raise ReleaseAcceptanceError(
            "THESISTRACE_TEST_DATABASE_URL must target an isolated PostgreSQL test database"
        )
    return dict(os.environ)


def attest_launch_evidence(evidence: dict[str, object]) -> str:
    state_dir = Path(
        os.environ.get("THESISTRACE_HOST_STATE_DIR", ROOT / ".hosted")
    )
    try:
        key = (state_dir / "secrets" / "launch_qualification_key").read_bytes()
    except OSError as error:
        raise ReleaseAcceptanceError(
            "launch attestation key is unavailable"
        ) from error
    return launch_attestation(evidence, key)


def resource_exhaustion_commands() -> tuple[str, ...]:
    return (
        "tests/hosted/test_research_workflow.py::"
        "test_resource_exhaustion_is_attempted_at_most_twice",
        "tests/hosted/test_dataset_publication_workflow.py::"
        "test_failure_and_repeated_resource_exhaustion_preserve_previous_truth",
        "tests/hosted/test_tracking_workflow.py::"
        "test_release_fanout_is_idempotent_and_advance_is_fenced_and_bounded",
        "tests/hosted/test_tracking_operations_workflow.py::"
        "test_equivalence_resource_exhaustion_publishes_no_result",
        "tests/hosted/test_tracking_operations_workflow.py::"
        "test_generation_rebuild_propagates_nested_resource_exhaustion",
        "tests/hosted/test_tracking_operations_workflow.py::"
        "test_tracking_operations_stop_after_two_resource_exhaustions",
    )


def recovery_matrix_commands() -> tuple[str, ...]:
    return (
        "tests/hosted/test_research_workflow.py::"
        "tests/hosted/test_research_workflow.py::"
        "test_relay_acknowledges_an_already_started_workflow",
        "tests/hosted/test_research_workflow.py::"
        "test_activity_redelivery_fences_the_abandoned_attempt",
        "tests/hosted/test_dataset_publication_workflow.py::"
        "test_cancellation_at_commit_fence_publishes_no_release_or_candidate",
        "tests/hosted/test_release_operations.py::"
        "test_real_maintenance_cli_drains_then_reports_nonterminal_timeout",
        "tests/hosted/test_release_operations.py::"
        "test_interrupted_deploy_recovery_waits_only_for_steady_dependencies",
    )


def main() -> None:
    arguments = parser().parse_args()
    release_bundle_id = arguments.release_bundle_id.strip()
    if not release_bundle_id:
        raise SystemExit("Release Bundle ID is required")
    postgres_environment = require_postgres_test_environment()
    records: dict[str, Any] = {}
    records["clean_checkout"] = assert_clean_checkout()
    records["capacity"] = validate_capacity(
        arguments.capacity_evidence,
        release_bundle_id,
    )
    recovery = validate_recovery(arguments.recovery_evidence, release_bundle_id)
    records["coordinated_backup"] = recovery
    records["full_restore"] = recovery

    source, records["source_authorization"] = run_json_command(
        "source_authorization",
        (str(STACK), "operator", "source-authorization", "inspect"),
    )
    if source.get("scope") != "hosted-shared-dataset-releases":
        raise ReleaseAcceptanceError("hosted source authorization is not recorded")
    capacity, _capacity_record = run_json_command(
        "capacity_qualification",
        (str(STACK), "operator", "capacity-qualification", "inspect"),
    )
    if (
        capacity.get("status") != "passed"
        or capacity.get("release_bundle_id") != release_bundle_id
    ):
        raise ReleaseAcceptanceError("latest capacity qualification does not match the Release")

    public, records["public_origin"] = run_json_command(
        "public_origin",
        (sys.executable, str(ROOT / "scripts" / "hosted-release-smoke.py")),
        environment={**os.environ, "THESISTRACE_ACCEPTANCE_MODE": "1"},
    )
    if (
        public.get("status") != "passed"
        or public.get("public_origin_ready") is not True
    ):
        raise ReleaseAcceptanceError("Public-Origin acceptance evidence is incomplete")
    records["system_health"] = records["public_origin"]
    records["data_health"] = records["public_origin"]
    records["quantitative_health"] = records["public_origin"]

    records["direct_origin_security"] = run_command(
        "direct_origin_security",
        (
            str(ROOT / ".venv" / "bin" / "pytest"),
            "-q",
            "tests/hosted/test_edge_policy.py",
            "tests/hosted/test_edge_rate_limits.py",
            "tests/hosted/test_container_boundaries.py",
            "tests/hosted/test_compose_stack.py",
        ),
    )
    records["storage"] = run_command(
        "storage",
        (
            str(ROOT / ".venv" / "bin" / "pytest"),
            "-q",
            "tests/hosted/test_storage_admission.py",
            "tests/hosted/test_object_store_boundary.py",
        ),
        environment=postgres_environment,
    )
    records["resource_exhaustion_matrix"] = run_command(
        "resource_exhaustion_matrix",
        (
            str(ROOT / ".venv" / "bin" / "pytest"),
            "-q",
            *resource_exhaustion_commands(),
        ),
    )
    records["recovery_matrix_unit"] = run_command(
        "recovery_matrix_unit",
        (
            str(ROOT / ".venv" / "bin" / "pytest"),
            "-q",
            *recovery_matrix_commands(),
        ),
    )
    records["postgresql_rls"] = run_command(
        "postgresql_rls",
        (
            str(ROOT / ".venv" / "bin" / "pytest"),
            "-q",
            "tests/hosted/test_workspace_isolation.py::"
            "test_two_users_have_private_research_and_the_same_bounded_dataset_view",
            "tests/hosted/test_workspace_isolation.py::"
            "test_production_roles_and_rls_cover_every_private_table",
            "tests/hosted/test_registration_provisioning.py::"
            "test_postgres_invitation_issue_is_fenced_by_latest_launch_measurement",
        ),
        environment=postgres_environment,
    )
    records["migrations"] = records["postgresql_rls"]
    records["backend"] = run_command(
        "backend",
        (str(ROOT / ".venv" / "bin" / "pytest"), "-q"),
        environment=postgres_environment,
    )
    records["frontend"] = run_command(
        "frontend_typecheck",
        ("bun", "run", "--cwd", "web", "typecheck"),
    )
    frontend_build = run_command(
        "frontend_build",
        ("bun", "run", "--cwd", "web", "build"),
    )
    records["frontend"]["build"] = frontend_build
    records["browser"] = run_command(
        "browser",
        ("bun", "run", "--cwd", "web", "test:e2e"),
    )

    checks = {name: True for name in sorted(REQUIRED_LAUNCH_CHECKS)}
    evidence = {
        "schema_version": "hosted-v2-launch-v1",
        "clean_stack": True,
        "release_bundle_id": release_bundle_id,
        "checks": checks,
        "records": records,
    }
    output_path = arguments.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_json_bytes(evidence))
    attestation = attest_launch_evidence(evidence)
    run_json_command(
        "record_launch_qualification",
        (
            str(STACK),
            "acceptance-record-launch",
            "--actor",
            arguments.actor,
            "--release-bundle-id",
            release_bundle_id,
            "--evidence",
            str(output_path),
            "--attestation",
            attestation,
        ),
        environment={**os.environ, "THESISTRACE_ACCEPTANCE_MODE": "1"},
    )
    suffix = hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()[:12]
    invitation, _record = run_json_command(
        "post_launch_invitation",
        (
            str(STACK),
            "operator",
            "invitation",
            "issue",
            "--actor",
            arguments.actor,
            "--email",
            f"post-launch-{suffix}@example.invalid",
            "--expires-at",
            "2099-01-01T00:00:00Z",
        ),
    )
    if invitation.get("state") != "issued":
        raise ReleaseAcceptanceError("invitation gate did not open after qualification")
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ReleaseAcceptanceError as error:
        raise SystemExit(str(error)) from error
