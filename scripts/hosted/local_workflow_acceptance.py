#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_TARGETS = (
    "tests/hosted/test_compute_dispatch.py",
    "tests/hosted/test_temporal_worker_heartbeat.py",
    "tests/hosted/test_research_workflow.py",
    "tests/hosted/test_dataset_publication_workflow.py",
    "tests/hosted/test_tracking_workflow.py",
    "tests/hosted/test_tracking_operations_workflow.py",
)
Runner = Callable[[tuple[str, ...]], bytes]


class LocalWorkflowAcceptanceError(RuntimeError):
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
        raise LocalWorkflowAcceptanceError(
            f"controlled workflow contract failed ({completed.returncode}):\n"
            + output[-8000:].decode("utf-8", errors="replace")
        )
    return output


def run_controlled_workflows(*, runner: Runner = execute) -> dict[str, object]:
    contracts: dict[str, object] = {}
    for target in CONTRACT_TARGETS:
        output = runner((sys.executable, "-m", "pytest", "-q", target))
        contracts[target] = {
            "status": "passed",
            "output_sha256": hashlib.sha256(output).hexdigest(),
        }
    return {
        "status": "passed",
        "schema_version": "hosted-local-controlled-workflows-v1",
        "contracts": contracts,
        "physical_capacity_claimed": False,
        "co_resident_health_claimed": False,
        "production_qualification_claimed": False,
    }


def main() -> None:
    print(json.dumps(run_controlled_workflows(), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except LocalWorkflowAcceptanceError as error:
        raise SystemExit(str(error)) from error
