from __future__ import annotations

import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread


class _ReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health/ready":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *args: object) -> None:
        del args


def test_auth_probe_does_not_require_unrelated_storage_drivers(tmp_path: Path) -> None:
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        """
import builtins

original_import = builtins.__import__

def import_without_storage_driver(name, *args, **kwargs):
    if name == "boto3" or name.startswith("boto3."):
        raise ImportError("unrelated storage driver is unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = import_without_storage_driver
""".lstrip()
    )
    server = HTTPServer(("127.0.0.1", 0), _ReadyHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source_root = Path(__file__).parents[2] / "src"
    python_path = os.pathsep.join(
        filter(
            None,
            (os.fspath(tmp_path), os.fspath(source_root), os.environ.get("PYTHONPATH")),
        )
    )
    environment = {
        **os.environ,
        "PYTHONPATH": python_path,
        "THESISTRACE_AUTH_INTERNAL_ORIGIN": (
            f"http://127.0.0.1:{server.server_address[1]}"
        ),
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "thesistrace.entrypoints.readiness_child", "auth"],
            check=False,
            env=environment,
            capture_output=True,
            timeout=5,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
