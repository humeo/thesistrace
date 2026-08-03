from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ENV = (
    "THESISTRACE_DATABASE_URL",
    "THESISTRACE_S3_ENDPOINT_URL",
    "THESISTRACE_S3_ACCESS_KEY_ID",
    "THESISTRACE_S3_SECRET_ACCESS_KEY",
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request_json(url: str) -> object:
    deadline = time.monotonic() + 15
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 - fixed loopback URL
                return json.load(response)
        except Exception as error:  # noqa: BLE001 - polling a child process boundary
            last_error = error
            time.sleep(0.1)
    raise AssertionError(f"HTTP process did not become ready: {last_error}")


@pytest.mark.skipif(
    any(not os.environ.get(name) for name in REQUIRED_ENV),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_http_and_worker_process_restarts_preserve_empty_data() -> None:
    environment = {**os.environ, "THESISTRACE_LOG_LEVEL": "warning"}
    expected_overview = {
        "status": "idle",
        "latest_release": None,
        "latest_update_outcome": None,
    }
    expected_history = {"items": [], "next_cursor": None}

    for _ in range(2):
        worker = subprocess.run(
            [sys.executable, "-m", "thesistrace.entrypoints.worker", "--once"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert worker.returncode == 0, worker.stderr

        port = _free_port()
        http = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "thesistrace.entrypoints.http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert _request_json(f"http://127.0.0.1:{port}/api/data") == expected_overview
            assert _request_json(f"http://127.0.0.1:{port}/api/data/releases") == expected_history
        finally:
            http.terminate()
            _, stderr = http.communicate(timeout=10)
            assert http.returncode in (0, -15), stderr
