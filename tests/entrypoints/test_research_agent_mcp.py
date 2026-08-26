from __future__ import annotations

import json
import logging
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from thesistrace.entrypoints import research_agent_mcp
from thesistrace.entrypoints.runtime import CORE_ENVIRONMENT_NAMES


def test_packaged_stdio_entrypoint_fails_cleanly_without_core_context() -> None:
    executable = Path(os.sys.executable).with_name("thesistrace-research-agent-mcp")
    environment = {
        name: value for name, value in os.environ.items() if name not in CORE_ENVIRONMENT_NAMES
    }

    completed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    event = json.loads(completed.stderr)
    assert event["component"] == "research_agent_mcp"
    assert event["event"] == "mcp_startup_failed"
    assert event["failure_code"] == "CORE_CONFIGURATION_MISSING"
    assert event["outcome"] == "failed"
    assert event["subject"] == "local_operator"
    assert event["trace_id"].startswith("trace_")
    assert event["transport"] == "stdio"
    assert "Traceback" not in completed.stderr


def test_packaged_stdio_entrypoint_sanitizes_unavailable_core_context(
    tmp_path: Path,
) -> None:
    executable = Path(os.sys.executable).with_name("thesistrace-research-agent-mcp")
    data_mount = tmp_path / "data"
    batch_attempt_control_directory = tmp_path / "batch-attempts"
    data_mount.mkdir()
    batch_attempt_control_directory.mkdir()
    database_canary = "private-database-canary"
    secret_canary = "private-s3-secret-canary"
    environment = {
        **os.environ,
        "THESISTRACE_DATABASE_URL": (f"postgresql://{database_canary}:unused@127.0.0.1:1/unused"),
        "THESISTRACE_S3_ENDPOINT_URL": "http://127.0.0.1:1",
        "THESISTRACE_S3_ACCESS_KEY_ID": "unused",
        "THESISTRACE_S3_SECRET_ACCESS_KEY": secret_canary,
        "THESISTRACE_S3_BUCKET": "unused",
        "THESISTRACE_DATA_MOUNT": str(data_mount),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(batch_attempt_control_directory),
    }

    completed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert len(completed.stderr.splitlines()) == 1
    event = json.loads(completed.stderr)
    assert event["component"] == "research_agent_mcp"
    assert event["event"] == "mcp_startup_failed"
    assert event["failure_code"] == "CORE_STARTUP_FAILED"
    assert event["outcome"] == "failed"
    assert event["subject"] == "local_operator"
    assert event["trace_id"].startswith("trace_")
    assert event["transport"] == "stdio"
    assert "Traceback" not in completed.stderr
    assert database_canary not in completed.stderr
    assert secret_canary not in completed.stderr


def test_stdio_entrypoint_reports_process_failure_by_its_lifecycle_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []
    runtime = _runtime_stub()
    _prepare_main_test(monkeypatch, events)
    monkeypatch.setattr(
        research_agent_mcp,
        "open_core_runtime",
        lambda _settings: _runtime_context(runtime),
    )
    monkeypatch.setattr(
        research_agent_mcp.anyio,
        "run",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("private-process-canary")),
    )

    with pytest.raises(SystemExit) as raised:
        research_agent_mcp.main()

    assert raised.value.code == 2
    assert len(events) == 1
    assert events[0].event == "mcp_process_failed"
    assert events[0].context["failure_code"] == "MCP_PROCESS_FAILED"
    assert "private-process-canary" not in str(events[0].context)


def test_stdio_entrypoint_reports_shutdown_failure_by_its_lifecycle_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []
    runtime = _runtime_stub()
    _prepare_main_test(monkeypatch, events)
    monkeypatch.setattr(
        research_agent_mcp,
        "open_core_runtime",
        lambda _settings: _runtime_context(
            runtime,
            shutdown_error=RuntimeError("private-shutdown-canary"),
        ),
    )
    monkeypatch.setattr(research_agent_mcp.anyio, "run", lambda *_args: None)

    with pytest.raises(SystemExit) as raised:
        research_agent_mcp.main()

    assert raised.value.code == 2
    assert len(events) == 1
    assert events[0].event == "mcp_shutdown_failed"
    assert events[0].context["failure_code"] == "CORE_SHUTDOWN_FAILED"
    assert "private-shutdown-canary" not in str(events[0].context)


def _prepare_main_test(
    monkeypatch: pytest.MonkeyPatch,
    events: list,
) -> None:
    pool_logger = logging.getLogger("psycopg.pool")
    monkeypatch.setattr(pool_logger, "disabled", pool_logger.disabled)
    monkeypatch.setattr(
        research_agent_mcp.CoreSettings,
        "from_environment",
        lambda: object(),
    )
    monkeypatch.setattr(research_agent_mcp, "emit_operational_event", events.append)


def _runtime_stub() -> SimpleNamespace:
    return SimpleNamespace(
        data_overview=object(),
        research_folders=object(),
        research_authoring=object(),
        research_runs=object(),
    )


@contextmanager
def _runtime_context(runtime: object, *, shutdown_error: Exception | None = None):
    yield runtime
    if shutdown_error is not None:
        raise shutdown_error
