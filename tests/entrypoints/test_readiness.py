from __future__ import annotations

import sys
from pathlib import Path
from subprocess import TimeoutExpired
from time import monotonic
from types import SimpleNamespace

from fastapi.testclient import TestClient

from thesistrace.entrypoints import readiness as readiness_module
from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.readiness import CoreReadiness


def test_readiness_has_one_end_to_end_deadline_for_blocked_probes(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "blocked_readiness_probe.py"
    probe.write_text(
        """
import sys
from threading import Event

if sys.argv[1] == "dataset_store":
    Event().wait()
raise SystemExit(0)
""".lstrip(),
        encoding="utf-8",
    )
    events: list[object] = []
    readiness = CoreReadiness(
        database_url="private-dsn",
        s3_endpoint_url="private-endpoint",
        s3_access_key_id="private-access-key",
        s3_secret_access_key="private-secret-key",
        s3_bucket="private-bucket",
        s3_region="us-east-1",
        data_mount=tmp_path / "private-mounted-root",
        deadline_seconds=0.25,
        probe_command=(sys.executable, str(probe)),
    )
    app = create_app(event_sink=events.append)
    app.state.core_runtime = SimpleNamespace(readiness=readiness)

    client = TestClient(app, raise_server_exceptions=True)
    try:
        started = monotonic()
        response = client.get("/health/ready")
        elapsed = monotonic() - started

        assert elapsed < 1
        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable",
            "dependencies": {
                "postgresql": {"status": "ready", "code": "POSTGRESQL_READY"},
                "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
                "dataset_store": {
                    "status": "unavailable",
                    "code": "DATASET_STORE_UNAVAILABLE",
                },
            },
        }
        assert "private" not in response.text
        assert client.get("/health/live").json() == {"status": "ok"}
        assert events == []
    finally:
        client.close()


def test_readiness_does_not_wait_for_a_probe_that_cannot_be_reaped(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    class UnreapableProbe:
        returncode = None

        def wait(self, timeout: float | None = None) -> int:
            raise TimeoutExpired("unreapable-readiness-probe", timeout)

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        readiness_module.subprocess,
        "Popen",
        lambda *args, **kwargs: UnreapableProbe(),
    )
    readiness = CoreReadiness(
        database_url="private-dsn",
        s3_endpoint_url="private-endpoint",
        s3_access_key_id="private-access-key",
        s3_secret_access_key="private-secret-key",
        s3_bucket="private-bucket",
        s3_region="us-east-1",
        data_mount=tmp_path / "private-mounted-root",
        deadline_seconds=0.05,
    )
    app = create_app()
    app.state.core_runtime = SimpleNamespace(readiness=readiness)
    client = TestClient(app)

    try:
        started = monotonic()
        response = client.get("/health/ready")

        assert monotonic() - started < 0.5
        assert response.status_code == 503
        assert response.json() == {
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
            },
        }
    finally:
        client.close()
