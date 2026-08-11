from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from thesistrace.entrypoints.runtime import CORE_ENVIRONMENT_NAMES

ROOT = Path(__file__).resolve().parents[2]


def test_worker_healthcheck_does_not_require_core_dependencies() -> None:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in CORE_ENVIRONMENT_NAMES
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "thesistrace.entrypoints.worker",
            "--healthcheck",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stderr
