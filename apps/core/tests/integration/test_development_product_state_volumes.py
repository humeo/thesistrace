from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

POSTGRES_IMAGE = "postgres:16.10-alpine"
ROOT = Path(__file__).resolve().parents[4]
TEST_PROJECT_PATTERN = re.compile(
    r"^thesistrace-test-[0-9]{8}t[0-9]{6}z-[0-9]+-[0-9a-f]{8}$"
)


def test_product_state_reset_and_erase_use_real_isolated_named_volumes() -> None:
    test_project_name = os.environ["THESISTRACE_TEST_PROJECT_NAME"]
    assert TEST_PROJECT_PATTERN.fullmatch(test_project_name)
    project_name = f"{test_project_name}-lifecycle"
    volumes = {
        "canonical": f"{project_name}_canonical-data",
        "postgres": f"{project_name}_postgres-data",
        "rustfs": f"{project_name}_rustfs-data",
    }
    try:
        for volume_name in volumes.values():
            _docker("volume", "create", volume_name)
        _write_marker(
            volumes["canonical"],
            "mkdir -p /state/objects/sha256/aa && "
            "printf exact-head > /state/HEAD.json && "
            "printf immutable-object > /state/objects/sha256/aa/object",
        )
        _write_marker(volumes["postgres"], "printf old-product > /state/product")
        _write_marker(volumes["rustfs"], "printf old-product > /state/product")

        _product_state_volumes("reset", project_name)
        for product_volume in (volumes["postgres"], volumes["rustfs"]):
            _docker("volume", "create", product_volume)

        assert _read_file(volumes["canonical"], "/state/HEAD.json") == "exact-head"
        assert (
            _read_file(
                volumes["canonical"],
                "/state/objects/sha256/aa/object",
            )
            == "immutable-object"
        )
        for product_volume in (volumes["postgres"], volumes["rustfs"]):
            missing = _read_file(product_volume, "/state/product", check=False)
            assert missing.returncode != 0

        _product_state_volumes("erase", project_name)
        for volume_name in volumes.values():
            assert _docker("volume", "inspect", volume_name, check=False).returncode != 0
    finally:
        _docker("volume", "rm", "--force", *volumes.values(), check=False)


def _write_marker(volume_name: str, script: str) -> None:
    _docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--volume",
        f"{volume_name}:/state",
        POSTGRES_IMAGE,
        "sh",
        "-eu",
        "-c",
        script,
    )


def _read_file(
    volume_name: str,
    path: str,
    *,
    check: bool = True,
) -> str | subprocess.CompletedProcess[str]:
    completed = _docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--volume",
        f"{volume_name}:/state",
        POSTGRES_IMAGE,
        "cat",
        path,
        check=check,
    )
    return completed.stdout if check else completed


def _docker(
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("docker", *arguments),
        capture_output=True,
        check=check,
        text=True,
    )


def _product_state_volumes(command: str, project_name: str) -> None:
    subprocess.run(
        (ROOT / "tooling" / "dev" / "product-state-volumes", command, project_name),
        capture_output=True,
        check=True,
        text=True,
    )
