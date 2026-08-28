from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Thread
from types import ModuleType

import pytest


def test_outage_polling_ignores_transient_fail_closed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_smoke_module()
    transient = (
        503,
        {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "unavailable", "code": "RUSTFS_UNAVAILABLE"},
                "dataset_store": {
                    "status": "unavailable",
                    "code": "DATASET_STORE_UNAVAILABLE",
                },
                "auth": {"status": "unavailable", "code": "AUTH_UNAVAILABLE"},
            },
        },
        0.01,
    )
    expected = (
        503,
        {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {
                    "status": "unavailable",
                    "code": "POSTGRESQL_UNAVAILABLE",
                },
                "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
                "dataset_store": {"status": "ready", "code": "DATASET_STORE_READY"},
                "auth": {"status": "unavailable", "code": "AUTH_UNAVAILABLE"},
            },
        },
        0.01,
    )
    responses = iter((transient, expected))
    monkeypatch.setattr(smoke, "_request_health", lambda *_args: next(responses))

    assert smoke._wait_for_readiness("http://api:8100", unavailable="postgresql") == expected


def test_mounted_data_hash_detects_batch_attempt_control_pollution(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    dataset_file = tmp_path / "generations" / "generation-id" / "manifest.json"
    dataset_file.parent.mkdir(parents=True)
    dataset_file.write_text("immutable dataset", encoding="utf-8")
    expected = smoke._directory_sha256(tmp_path)

    control_file = tmp_path / ".batch-attempts" / "batch_attempt_id.lock"
    control_file.parent.mkdir()
    control_file.write_text("runtime state", encoding="utf-8")

    assert smoke._directory_sha256(tmp_path) != expected


def test_web_image_probe_uses_the_public_origin_host_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_host = "thesistrace.test:8443"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Host") != expected_host:
                self.send_response(421)
                self.end_headers()
                return
            body = b'<!doctype html><div id="root"></div>'
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "THESISTRACE_PUBLIC_ORIGIN",
        f"https://{expected_host}",
    )
    try:
        smoke = _load_smoke_module()
        smoke._assert_web_image(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _load_smoke_module() -> ModuleType:
    path = Path(__file__).parents[1] / "production_image_smoke.py"
    spec = spec_from_file_location("thesistrace_production_image_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
