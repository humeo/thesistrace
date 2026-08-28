from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOCATOR = ROOT / "scripts" / "locked-loopback-port"


def test_allocator_holds_unique_ports_until_the_exact_owner_releases_them(
    tmp_path: Path,
) -> None:
    lock_root = tmp_path / "port-locks"
    first_owner = "thesistrace-test-first"
    second_owner = "thesistrace-test-second"

    first = _acquire(lock_root, first_owner)
    second = _acquire(lock_root, second_owner)
    assert first != second
    assert (lock_root / str(first) / "owner").read_text() == f"{first_owner}\n"
    assert (lock_root / str(second) / "owner").read_text() == f"{second_owner}\n"

    refused = subprocess.run(
        [
            sys.executable,
            ALLOCATOR,
            "release",
            "--lock-root",
            lock_root,
            "--owner",
            second_owner,
            "--port",
            str(first),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert refused.returncode != 0
    assert (lock_root / str(first)).is_dir()

    _release(lock_root, first_owner, first)
    _release(lock_root, second_owner, second)
    assert list(lock_root.iterdir()) == []


def _acquire(lock_root: Path, owner: str) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            ALLOCATOR,
            "acquire",
            "--lock-root",
            lock_root,
            "--owner",
            owner,
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    return int(completed.stdout)


def _release(lock_root: Path, owner: str, port: int) -> None:
    subprocess.run(
        [
            sys.executable,
            ALLOCATOR,
            "release",
            "--lock-root",
            lock_root,
            "--owner",
            owner,
            "--port",
            str(port),
        ],
        check=True,
    )
