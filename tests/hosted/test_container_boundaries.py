import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "hosted" / "compose.yaml"

pytestmark = pytest.mark.skipif(
    os.environ.get("THESISTRACE_CONTAINER_ACCEPTANCE") != "1",
    reason="set THESISTRACE_CONTAINER_ACCEPTANCE=1 for container probes",
)

STORAGE_PROBE = r"""
import os
from pathlib import Path

assert os.getuid() == 10005
assert Path("/var/lib/thesistrace/objects").is_dir()
assert not Path("/var/lib/thesistrace/working-cache").exists()
assert "THESISTRACE_DATABASE_URL" not in os.environ
assert not Path("/var/run/docker.sock").exists()
"""


def compose_command(project: str, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--project-directory",
        str(ROOT),
        "-f",
        str(COMPOSE),
        *arguments,
    ]
