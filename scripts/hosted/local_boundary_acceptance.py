#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_POSTGRES = ROOT / "scripts" / "hosted" / "local_postgres_acceptance.py"
CONTROLLED_TARGETS = (
    "tests/hosted/test_edge_policy.py",
    "tests/hosted/test_edge_rate_limits.py",
    "tests/hosted/test_container_boundaries.py",
    "tests/hosted/test_storage_admission.py",
    "tests/hosted/test_object_store_boundary.py",
    "tests/hosted/test_health_views.py",
    "tests/hosted/test_compose_stack.py::"
    "test_otel_sampling_and_export_failure_are_bounded_and_visible",
)
Runner = Callable[[tuple[str, ...]], bytes]


class LocalBoundaryAcceptanceError(RuntimeError):
    pass


def execute(command: tuple[str, ...]) -> bytes:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ,
        capture_output=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise LocalBoundaryAcceptanceError(
            f"local boundary command failed with exit {completed.returncode}:\n"
            + output[-8000:].decode("utf-8", errors="replace")
        )
    return output


def _last_json(output: bytes) -> dict[str, object]:
    for line in reversed(output.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LocalBoundaryAcceptanceError("local PostgreSQL gate returned no JSON evidence")


def run_boundary_acceptance(*, runner: Runner = execute) -> dict[str, object]:
    postgres_output = runner((sys.executable, str(LOCAL_POSTGRES)))
    postgres = _last_json(postgres_output)
    if postgres.get("status") != "passed":
        raise LocalBoundaryAcceptanceError("local PostgreSQL evidence did not pass")
    controlled_results: dict[str, object] = {}
    for target in CONTROLLED_TARGETS:
        controlled_output = runner((sys.executable, "-m", "pytest", "-q", target))
        controlled_results[target] = {
            "status": "passed",
            "output_sha256": hashlib.sha256(controlled_output).hexdigest(),
        }
    return {
        "status": "passed",
        "schema_version": "hosted-local-boundary-v1",
        "postgresql": postgres,
        "controlled_tests": controlled_results,
        "sub_boundaries": {
            "postgresql_rls": True,
            "edge": True,
            "storage": True,
            "container_and_network": True,
            "telemetry_redaction": True,
        },
    }


def main() -> None:
    if os.environ.get("THESISTRACE_LOCAL_ACCEPTANCE") != "1":
        raise LocalBoundaryAcceptanceError(
            "local boundary acceptance requires THESISTRACE_LOCAL_ACCEPTANCE=1"
        )
    print(json.dumps(run_boundary_acceptance(), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalBoundaryAcceptanceError as error:
        raise SystemExit(str(error)) from error
