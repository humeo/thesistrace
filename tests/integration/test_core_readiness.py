from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from thesistrace.entrypoints.http import create_app
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core

READY = {
    "status": "ready",
    "dependencies": {
        "postgresql": {"status": "ready", "code": "POSTGRESQL_READY"},
        "rustfs": {"status": "ready", "code": "RUSTFS_READY"},
        "dataset_store": {"status": "ready", "code": "DATASET_STORE_READY"},
    },
}


def test_core_readiness_fails_and_recovers_each_real_dependency_independently(
    core_settings: CoreSettings,
    tmp_path: Path,
) -> None:
    postgres = _controlled_container("postgres")
    rustfs = _controlled_container("rustfs")
    initialize_core(core_settings.database_url)
    settings = replace(core_settings, data_mount=tmp_path)
    events: list[object] = []

    with TestClient(create_app(settings, event_sink=events.append)) as client:
        assert _await_readiness(client, expected=READY).json() == READY
        assert client.get("/health/live").json() == {"status": "ok"}

        _assert_dependency_outage(
            client,
            container=postgres,
            name="postgresql",
            code="POSTGRESQL_UNAVAILABLE",
        )
        _assert_dependency_outage(
            client,
            container=rustfs,
            name="rustfs",
            code="RUSTFS_UNAVAILABLE",
        )

        unavailable_root = tmp_path.with_name(f"{tmp_path.name}-offline")
        tmp_path.rename(unavailable_root)
        try:
            expected = _unavailable(
                "dataset_store",
                "DATASET_STORE_UNAVAILABLE",
            )
            response = _await_readiness(client, expected=expected)
            assert response.json() == expected
            assert client.get("/health/live").status_code == 200
        finally:
            unavailable_root.rename(tmp_path)
        assert _await_readiness(client, expected=READY).json() == READY

        assert events == []
        assert "thesistrace-test" not in json.dumps(READY)


def _controlled_container(service: str) -> str:
    explicit = os.environ.get(f"THESISTRACE_TEST_{service.upper()}_CONTAINER")
    if explicit:
        return explicit
    project = os.environ.get("THESISTRACE_TEST_PROJECT_NAME")
    if not project:
        pytest.skip("isolated Core dependency containers are required")
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    containers = result.stdout.split()
    if len(containers) != 1:
        raise AssertionError(f"expected exactly one controlled {service} container")
    return containers[0]


def _assert_dependency_outage(
    client: TestClient,
    *,
    container: str,
    name: str,
    code: str,
) -> None:
    subprocess.run(["docker", "pause", container], check=True, capture_output=True)
    try:
        expected = _unavailable(name, code)
        response = _await_readiness(client, expected=expected, timeout_seconds=15)
        assert response.json() == expected
        assert client.get("/health/live").status_code == 200
    finally:
        subprocess.run(["docker", "unpause", container], check=True, capture_output=True)
    assert _await_readiness(client, expected=READY, timeout_seconds=15).json() == READY


def _await_readiness(
    client: TestClient,
    *,
    expected: dict[str, object],
    timeout_seconds: float = 5,
):  # type: ignore[no-untyped-def]
    expected_status = 200 if expected["status"] == "ready" else 503
    deadline = monotonic() + timeout_seconds
    while True:
        started = monotonic()
        response = client.get("/health/ready")
        assert monotonic() - started < 3
        if response.status_code == expected_status and response.json() == expected:
            return response
        if monotonic() >= deadline:
            raise AssertionError(
                f"readiness did not reach HTTP {expected_status} with {expected}: "
                f"HTTP {response.status_code} {response.text}"
            )
        Event().wait(0.05)


def _unavailable(name: str, code: str) -> dict[str, object]:
    value = json.loads(json.dumps(READY))
    value["status"] = "unavailable"
    value["dependencies"][name] = {"status": "unavailable", "code": code}
    return value
