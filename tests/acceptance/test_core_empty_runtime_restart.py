from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from core_runtime import drop_product_schemas

from thesistrace._postgres import PostgresDatabase
from thesistrace.data import DatasetLifecycle, MountedGenerationStore
from thesistrace.entrypoints.runtime import CoreSettings, core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.fixture import build_minimal_canonical_fixture

ROOT = Path(__file__).resolve().parents[2]


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


def _request_status(url: str) -> int:
    try:
        with urlopen(url, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            return response.status
    except HTTPError as error:
        return error.code


@pytest.mark.skipif(
    not core_environment_is_configured(),
    reason="the isolated Core PostgreSQL/RustFS runtime is not configured",
)
def test_http_and_worker_process_restarts_reopen_one_prepared_head(tmp_path: Path) -> None:
    settings = replace(CoreSettings.from_environment(), data_mount=tmp_path)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    database = PostgresDatabase(settings.database_url)
    database.open()
    try:
        generation = MountedGenerationStore(tmp_path).materialize(
            build_minimal_canonical_fixture(),
            prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
            source_name="prepared-process-restart-test",
            source_lineage={"fixture": "minimal"},
        )
        lifecycle = DatasetLifecycle(database, tmp_path)
        lifecycle.protect_candidate(
            operation_id="prepared-process-restart",
            generation_manifest_sha256=generation.manifest_sha256,
            lease_seconds=60,
        )
        lifecycle.compare_and_swap_head(
            expected_generation_manifest_sha256=None,
            candidate_generation_manifest_sha256=generation.manifest_sha256,
            operation_id="prepared-process-restart",
        )
    finally:
        database.close()

    environment = {
        **os.environ,
        "THESISTRACE_DATA_MOUNT": str(tmp_path),
        "THESISTRACE_BENCHMARK_MOUNT": str(settings.benchmark_mount),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            settings.batch_attempt_control_directory
        ),
        "THESISTRACE_LOG_LEVEL": "warning",
    }
    environment.pop("THESISTRACE_TUSHARE_TOKEN", None)
    api_command = shutil.which("thesistrace-core-api")
    worker_command = shutil.which("thesistrace-core-worker")
    assert api_command is not None
    assert worker_command is not None
    expected_overview = {
        "market_coverage": {"start": "2026-08-07", "end": "2026-08-07"},
        "financial_coverage": None,
        "industry_coverage": {
            "start": "2026-08-07",
            "observation_through_session": "2026-08-07",
            "classification_version": "SW2021",
        },
        "data_through_session": "2026-08-07",
        "last_market_refresh_at": None,
        "last_financial_refresh_at": None,
        "last_industry_refresh_at": None,
        "industry_refresh_status": None,
        "industry_refresh_failure_code": None,
        "market_research_readiness": True,
        "financial_research_readiness": "not_ready",
        "industry_research_readiness": True,
    }

    for role in ("research", "tracking"):
        worker = subprocess.run(
            [worker_command, "--role", role, "--once"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert worker.returncode == 0, worker.stderr

        port = _free_port()
        http = subprocess.Popen(
            [api_command, "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert _request_json(f"http://127.0.0.1:{port}/api/data") == expected_overview
            assert _request_status(f"http://127.0.0.1:{port}/api/data/releases") == 404
            assert _request_status(f"http://127.0.0.1:{port}/api/data/update") == 404
        finally:
            http.terminate()
            _, stderr = http.communicate(timeout=10)
            assert http.returncode in (0, -15), stderr
