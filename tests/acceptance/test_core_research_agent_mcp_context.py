from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path

import anyio
from core_runtime import (
    drop_product_schemas,
    isolated_core_settings,
)
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.entrypoints.schema import initialize_core
from thesistrace.research_agent.mcp_server import RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES


def test_packaged_stdio_reads_real_core_context_and_exits_cleanly(
    tmp_path: Path,
) -> None:
    settings = isolated_core_settings(tmp_path / "data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    stderr_path = tmp_path / "mcp-stderr.log"
    try:
        anyio.run(_exercise_stdio, settings, stderr_path)
        events = [json.loads(line) for line in stderr_path.read_text().splitlines()]
        assert len(events) == 6
        assert all(event["component"] == "research_agent_mcp" for event in events)
        assert all(event["transport"] == "stdio" for event in events)
        assert all(event["subject"] == "local_operator" for event in events)
        assert [event["outcome"] for event in events] == [
            "succeeded",
            "succeeded",
            "succeeded",
            "succeeded",
            "succeeded",
            "failed",
        ]
        assert events[-1]["failure_code"] == "INVALID_INPUT"
        assert "private-formula-canary" not in stderr_path.read_text()
        _assert_raw_stdio_process_exits_cleanly(settings)
        anyio.run(
            _exercise_official_client_oversize_disconnect_and_reconnect,
            settings,
            tmp_path,
        )
    finally:
        drop_product_schemas(settings)


async def _exercise_stdio(settings: CoreSettings, stderr_path: Path) -> None:
    executable = Path(sys.executable).with_name("thesistrace-research-agent-mcp")
    parameters = StdioServerParameters(
        command=str(executable),
        cwd=Path.cwd(),
        env=_core_environment(settings),
    )
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stderr_path.open("w+") as errlog:
        async with Client(stdio_client(parameters, errlog=errlog)) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == [
                "get_research_context",
                "get_alpha_catalog",
                "diagnose_alpha_formula",
                "list_research_runs",
                "get_research_run",
                "get_research_run_result",
                "list_daily_tracks",
                "get_daily_track",
                "get_daily_track_result",
                "start_daily_track",
                "retry_daily_track",
                "list_research_batches",
                "get_research_batch",
                "submit_research_batch",
                "submit_research_run",
            ]

            context = await client.call_tool("get_research_context", {})
            assert context.is_error is False
            assert context.structured_content["data_overview"]["market_research_readiness"] is False
            assert [folder["id"] for folder in context.structured_content["folders"]["items"]] == [
                "folder_default",
                "folder_batch_research",
            ]
            assert "generation" not in str(context.structured_content).lower()

            catalog = await client.call_tool(
                "get_alpha_catalog",
                {"identifiers": ["ts_mean", "unknown_identifier", "close"]},
            )
            assert catalog.is_error is False
            assert [field["identifier"] for field in catalog.structured_content["fields"]] == [
                "close"
            ]
            assert [
                builtin["identifier"] for builtin in catalog.structured_content["builtins"]
            ] == ["ts_mean"]
            assert catalog.structured_content["unknown_identifiers"] == ["unknown_identifier"]

            diagnostic = await client.call_tool(
                "diagnose_alpha_formula",
                {"source": "unknown_alpha + close"},
            )
            assert diagnostic.is_error is False
            assert diagnostic.structured_content["valid"] is False
            assert diagnostic.structured_content["diagnostics"][0]["code"] == ("UNKNOWN_IDENTIFIER")
            assert diagnostic.structured_content["diagnostics"][0]["range"]["start"]["offset"] == 0

            first_full_catalog = await client.call_tool("get_alpha_catalog", {})
            second_full_catalog = await client.call_tool("get_alpha_catalog", {})
            assert first_full_catalog.structured_content == (second_full_catalog.structured_content)
            assert [
                field["identifier"] for field in first_full_catalog.structured_content["fields"]
            ] == sorted(
                field["identifier"] for field in first_full_catalog.structured_content["fields"]
            )
            assert [
                builtin["identifier"]
                for builtin in first_full_catalog.structured_content["builtins"]
            ] == sorted(
                builtin["identifier"]
                for builtin in first_full_catalog.structured_content["builtins"]
            )

            malformed = await client.call_tool(
                "diagnose_alpha_formula",
                {
                    "source": "private-formula-canary",
                    "generation_id": "must-not-be-accepted",
                },
            )
            assert malformed.is_error is True
            assert malformed.structured_content["code"] == "INVALID_INPUT"
            assert malformed.structured_content["retryable"] is False
            assert malformed.structured_content["trace_id"].startswith("trace_")

    assert executable.is_file()
    assert os.access(executable, os.X_OK)


def _assert_raw_stdio_process_exits_cleanly(settings: CoreSettings) -> None:
    executable = Path(sys.executable).with_name("thesistrace-research-agent-mcp")
    process = subprocess.Popen(
        [str(executable)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **_core_environment(settings)},
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    transcript: list[dict[str, object]] = []
    stdout_tail = ""
    stderr = ""
    try:
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_HANDSHAKE_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "acceptance", "version": "1"},
            },
        }
        initialize = _raw_stdio_exchange(
            process,
            initialize_request,
        )
        transcript.append({"request": initialize_request, "response": initialize})
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        _raw_stdio_send(
            process,
            initialized_notification,
        )
        transcript.append({"notification": initialized_notification})
        list_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        tools = _raw_stdio_exchange(
            process,
            list_request,
        )
        transcript.append({"request": list_request, "response": tools})
        process.stdin.close()
        returncode = process.wait(timeout=30)
        stdout_tail = process.stdout.read()
        stderr = process.stderr.read()
        assert returncode == 0
        assert initialize["id"] == 1
        assert initialize["result"]["protocolVersion"] == LATEST_HANDSHAKE_VERSION
        assert tools["id"] == 2
        assert [tool["name"] for tool in tools["result"]["tools"]] == [
            "get_research_context",
            "get_alpha_catalog",
            "diagnose_alpha_formula",
            "list_research_runs",
            "get_research_run",
            "get_research_run_result",
            "list_daily_tracks",
            "get_daily_track",
            "get_daily_track_result",
            "start_daily_track",
            "retry_daily_track",
            "list_research_batches",
            "get_research_batch",
            "submit_research_batch",
            "submit_research_run",
        ]
        assert stdout_tail == ""
        assert stderr == ""
    except Exception as error:
        returncode, remaining_stdout, remaining_stderr = _finish_raw_stdio_process(process)
        stdout_tail += remaining_stdout
        stderr += remaining_stderr
        diagnostic = {
            "returncode": returncode,
            "transcript": transcript,
            "stdout": _sanitize_raw_stdio_diagnostic(stdout_tail, settings),
            "stderr": _sanitize_raw_stdio_diagnostic(stderr, settings),
        }
        raise AssertionError(
            f"raw stdio MCP acceptance failed: {json.dumps(diagnostic, sort_keys=True)[:8192]}"
        ) from error


async def _exercise_official_client_oversize_disconnect_and_reconnect(
    settings: CoreSettings,
    tmp_path: Path,
) -> None:
    executable = Path(sys.executable).with_name("thesistrace-research-agent-mcp")
    parameters = StdioServerParameters(
        command=str(executable),
        cwd=Path.cwd(),
        env=_core_environment(settings),
    )
    canary = "official-client-oversize-canary"
    failure: BaseException | None = None
    failed_stderr = tmp_path / "mcp-oversize-stderr.log"
    with failed_stderr.open("w+") as errlog:
        try:
            with anyio.fail_after(10):
                async with Client(stdio_client(parameters, errlog=errlog)) as client:
                    await client.call_tool(
                        "diagnose_alpha_formula",
                        {
                            "source": canary
                            * (RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES // len(canary))
                        },
                    )
        except BaseException as error:
            failure = error

    assert failure is not None
    assert not isinstance(failure, TimeoutError)
    assert canary not in str(failure)
    failure_events = [json.loads(line) for line in failed_stderr.read_text().splitlines()]
    assert len(failure_events) == 1
    assert failure_events[0]["component"] == "research_agent_mcp"
    assert failure_events[0]["event"] == "mcp_process_failed"
    assert failure_events[0]["failure_code"] == "MCP_PROCESS_FAILED"
    assert canary not in failed_stderr.read_text()

    reconnected_stderr = tmp_path / "mcp-reconnected-stderr.log"
    with reconnected_stderr.open("w+") as errlog:
        async with Client(stdio_client(parameters, errlog=errlog)) as client:
            tools = await client.list_tools()
    assert len(tools.tools) == 15
    assert reconnected_stderr.read_text() == ""


def _raw_stdio_exchange(
    process: subprocess.Popen[str],
    message: dict[str, object],
) -> dict[str, object]:
    _raw_stdio_send(process, message)
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 10)
    assert ready, "timed out waiting for raw stdio MCP response"
    line = process.stdout.readline()
    assert line, "raw stdio MCP process exited before responding"
    return json.loads(line)


def _raw_stdio_send(
    process: subprocess.Popen[str],
    message: dict[str, object],
) -> None:
    assert process.stdin is not None
    process.stdin.write(f"{json.dumps(message)}\n")
    process.stdin.flush()


def _finish_raw_stdio_process(
    process: subprocess.Popen[str],
) -> tuple[int | None, str, str]:
    if process.stdin is not None and not process.stdin.closed:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    stdout = "" if process.stdout is None else process.stdout.read()
    stderr = "" if process.stderr is None else process.stderr.read()
    return process.returncode, stdout, stderr


def _sanitize_raw_stdio_diagnostic(value: str, settings: CoreSettings) -> str:
    sanitized = value
    for private_value in (
        settings.database_url,
        settings.s3_endpoint_url,
        settings.s3_access_key_id,
        settings.s3_secret_access_key,
        str(settings.data_mount),
        str(settings.batch_attempt_control_directory),
    ):
        if private_value:
            sanitized = sanitized.replace(private_value, "<redacted>")
    return sanitized[:4096]


def _core_environment(settings: CoreSettings) -> dict[str, str]:
    return {
        "THESISTRACE_DATABASE_URL": settings.database_url,
        "THESISTRACE_S3_ENDPOINT_URL": settings.s3_endpoint_url,
        "THESISTRACE_S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "THESISTRACE_S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        "THESISTRACE_S3_BUCKET": settings.s3_bucket,
        "THESISTRACE_S3_REGION": settings.s3_region,
        "THESISTRACE_DATA_MOUNT": str(settings.data_mount),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(
            settings.batch_attempt_control_directory
        ),
    }
