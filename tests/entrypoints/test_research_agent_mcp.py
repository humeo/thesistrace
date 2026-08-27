from __future__ import annotations

import json
import logging
import os
import subprocess
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from thesistrace.entrypoints import research_agent_mcp
from thesistrace.entrypoints.runtime import CORE_ENVIRONMENT_NAMES
from thesistrace.research_agent.mcp_server import RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES


def test_stdio_raw_frame_reader_is_bounded_before_json_parsing() -> None:
    anyio.run(_exercise_bounded_stdio_reader)


async def _exercise_bounded_stdio_reader() -> None:
    exact = b"x" * (RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES - 1) + b"\n"
    reader = research_agent_mcp._BoundedStdin(
        BytesIO(exact + b"private-raw-frame-canary" * 10000)
    )

    assert await anext(reader) == exact.decode()
    with pytest.raises(research_agent_mcp.ResearchAgentStdioRequestTooLarge):
        await anext(reader)


def test_stdio_claim_diverts_handler_and_child_stdin_then_restores_wire() -> None:
    script = """
import json
import os
import subprocess
import sys
from thesistrace.entrypoints.research_agent_mcp import _claimed_bounded_stdin

with _claimed_bounded_stdin() as reader:
    child = subprocess.run(
        [sys.executable, "-c", "import os,sys; sys.stdout.buffer.write(os.read(0, 1))"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    try:
        reader._readline()
    except Exception as error:
        rejected = type(error).__name__
print(json.dumps({
    "child_stdin": child.stdout.decode(),
    "rejected": rejected,
}))
"""
    process = subprocess.Popen(
        [os.sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        process.stdin.write(b"x" * (RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES + 1))
        process.stdin.flush()
        returncode = process.wait(timeout=10)
    except Exception as error:
        returncode, completed_stdout, completed_stderr = _finish_stdio_claim_probe(
            process
        )
        raise AssertionError(
            "bounded stdio claim probe failed: "
            f"returncode={returncode}, "
            f"stdout={completed_stdout!r}, stderr={completed_stderr!r}"
        ) from error
    else:
        completed_stdout = process.stdout.read(4096)
        completed_stderr = process.stderr.read(4096)
    finally:
        if not process.stdin.closed:
            process.stdin.close()

    assert returncode == 0
    assert json.loads(completed_stdout) == {
        "child_stdin": "",
        "rejected": "ResearchAgentStdioRequestTooLarge",
    }
    assert completed_stderr == b""


def _finish_stdio_claim_probe(
    process: subprocess.Popen[bytes],
) -> tuple[int | None, bytes, bytes]:
    if process.stdin is not None and not process.stdin.closed:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stdout = b"" if process.stdout is None else process.stdout.read(4096)
    stderr = b"" if process.stderr is None else process.stderr.read(4096)
    return process.returncode, stdout, stderr


def test_stdio_dangerous_scope_requires_exact_explicit_process_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = research_agent_mcp.RESEARCH_CANCEL_ENABLE_ENVIRONMENT
    monkeypatch.delenv(name, raising=False)
    assert research_agent_mcp._research_cancel_is_enabled() is False
    monkeypatch.setenv(name, "true")
    assert research_agent_mcp._research_cancel_is_enabled() is True
    for value in ("1", "TRUE", "false", " true ", "research:cancel"):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError, match="must be exactly true"):
            research_agent_mcp._research_cancel_is_enabled()

    tracking_name = research_agent_mcp.TRACKING_STOP_ENABLE_ENVIRONMENT
    monkeypatch.delenv(tracking_name, raising=False)
    assert research_agent_mcp._tracking_stop_is_enabled() is False
    monkeypatch.setenv(tracking_name, "true")
    assert research_agent_mcp._tracking_stop_is_enabled() is True
    for value in ("1", "TRUE", "false", " true ", "tracking:stop"):
        monkeypatch.setenv(tracking_name, value)
        with pytest.raises(ValueError, match="must be exactly true"):
            research_agent_mcp._tracking_stop_is_enabled()


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
    benchmark_mount = tmp_path / "benchmark-data"
    batch_attempt_control_directory = tmp_path / "batch-attempts"
    data_mount.mkdir()
    benchmark_mount.mkdir()
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
        "THESISTRACE_BENCHMARK_MOUNT": str(benchmark_mount),
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
        research_batches=object(),
        research_runs=object(),
        daily_tracks=object(),
    )


@contextmanager
def _runtime_context(runtime: object, *, shutdown_error: Exception | None = None):
    yield runtime
    if shutdown_error is not None:
        raise shutdown_error
