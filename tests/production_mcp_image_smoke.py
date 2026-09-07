from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Never
from uuid import UUID

import anyio
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, ListToolsResult
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from production_mcp_image_api import (
    ISSUER_URL,
    RESOURCE_URL,
    TRUSTED_ORIGIN,
    application,
)
from production_mcp_image_canaries import (
    ACTION_TOKEN,
    FORMULA,
    HYPOTHESIS,
    READ_TOKEN,
    SUBJECT,
)
from sanitize_production_mcp_evidence import (
    EvidenceSanitizationError,
    verify_evidence,
)

import thesistrace
from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.http import create_app
from thesistrace.researcher import ResearcherIdentity, ResearcherService

SAFE_STDIO_TOOL_ORDER = (
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
    "refresh_daily_track",
    "retry_daily_track",
    "list_research_batches",
    "get_research_batch",
    "submit_research_batch",
    "submit_research_run",
)
SAFE_STDIO_TOOLS = set(SAFE_STDIO_TOOL_ORDER)
READ_TOOLS = {
    "diagnose_alpha_formula",
    "get_alpha_catalog",
    "get_research_batch",
    "get_research_context",
    "get_research_run",
    "get_research_run_result",
    "list_research_batches",
    "list_research_runs",
}
ACTION_TOOLS = READ_TOOLS | {"submit_research_batch", "submit_research_run"}
DANGEROUS_TOOLS = {
    "cancel_research_batch",
    "cancel_research_run",
    "stop_daily_track",
}
RESEARCH_CONTEXT_KEYS = {"authoring_constraints", "data_overview", "folders"}
FORBIDDEN_TOOL_FRAGMENTS = {
    "data_operator",
    "delete",
    "execute",
    "http",
    "object",
    "python",
    "shell",
    "sql",
}
CORE_ENVIRONMENT_NAMES = (
    "THESISTRACE_DATABASE_URL",
    "THESISTRACE_S3_ENDPOINT_URL",
    "THESISTRACE_S3_ACCESS_KEY_ID",
    "THESISTRACE_S3_SECRET_ACCESS_KEY",
    "THESISTRACE_S3_BUCKET",
    "THESISTRACE_S3_REGION",
    "THESISTRACE_DATA_MOUNT",
    "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
)
TRACE_PATTERN = re.compile(r"trace_[0-9a-f]{32}")
MAX_STDIO_RESPONSE_BYTES = 1024 * 1024
PRIVATE_EVIDENCE_KEYS = {
    "checkpoint",
    "cursor",
    "formula",
    "hypothesis",
    "instrument_id",
    "manifest",
    "object_key",
    "positions",
    "sql",
    "token",
}
FAILURE_CODES = {
    "api_lifecycle_contract",
    "default_fail_closed_contract",
    "http_auth_contract",
    "http_discovery_contract",
    "http_result_contract",
    "http_submission_contract",
    "image_package_contract",
    "mcp_persistence_contract",
    "protocol_evidence_contract",
    "stdio_contract",
    "timeout",
    "unexpected",
}


class _SmokeFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in FAILURE_CODES:
            raise ValueError("image smoke failure code is not allowlisted")
        super().__init__(code)
        self.code = code


def main() -> None:
    phases = {"preflight", "http-before", "http-after", "stdio", "evidence"}
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        raise SystemExit(
            "usage: production_mcp_image_smoke.py "
            f"{{{'|'.join(sorted(phases))}}}"
        )
    phase = sys.argv[1]
    try:
        if phase == "preflight":
            result = _preflight()
        elif phase == "http-before":
            result = anyio.run(_http_before)
            _write_private_state(_state_path(), {"run_id": result["run_id"]})
        elif phase == "http-after":
            result = anyio.run(_http_after, _read_run_id())
        elif phase == "stdio":
            result = anyio.run(_stdio)
        else:
            result = _evidence()
        serialized = json.dumps(result, ensure_ascii=True, sort_keys=True)
        _assert_public_evidence(json.loads(serialized))
        print(serialized)
    except _SmokeFailure as error:
        _exit_closed(error.code)
    except BaseException as error:
        _exit_closed(
            _nested_smoke_failure_code(error) or "unexpected",
            error_types=_error_types(error),
        )


def _preflight() -> dict[str, object]:
    image_root = Path("/app").resolve()
    module_path = Path(thesistrace.__file__).resolve()
    _require(module_path.is_relative_to(image_root), "image_package_contract")
    _require(not module_path.is_relative_to(Path("/smoke")), "image_package_contract")

    installed_mcp = version("mcp")
    with Path("/app/uv.lock").open("rb") as lock_file:
        locked = tomllib.load(lock_file)
    locked_versions = {
        str(package["version"])
        for package in locked.get("package", [])
        if package.get("name") == "mcp"
    }
    _require(locked_versions == {installed_mcp}, "image_package_contract")
    stdio_entrypoint = shutil.which("thesistrace-research-agent-mcp")
    api_entrypoint = shutil.which("thesistrace-core-api")
    _require(stdio_entrypoint is not None, "image_package_contract")
    _require(api_entrypoint is not None, "image_package_contract")
    _require(Path(stdio_entrypoint).is_relative_to(image_root), "image_package_contract")
    _require(Path(api_entrypoint).is_relative_to(image_root), "image_package_contract")

    default_routes = {route.path for route in create_app().routes}
    _require("/mcp" not in default_routes, "default_fail_closed_contract")
    try:
        create_app(enable_research_agent_http=True)
    except ValueError:
        pass
    else:
        raise _SmokeFailure("default_fail_closed_contract")
    configured_routes = {route.path for route in application().routes}
    _require("/mcp" in configured_routes, "image_package_contract")
    _require(
        "/.well-known/oauth-protected-resource/mcp" in configured_routes,
        "image_package_contract",
    )
    return {
        "status": "passed",
        "installed_mcp_sdk_version": installed_mcp,
        "locked_mcp_sdk_version": installed_mcp,
        "packaged_api_entrypoint": True,
        "packaged_stdio_entrypoint": True,
        "product_loaded_from_final_image": True,
        "default_http_mcp_enabled": False,
        "configured_http_mcp_mounted": True,
        "random_seed": _random_seed(),
        "image_digest": _image_digest(),
    }


async def _http_before() -> dict[str, object]:
    _bootstrap_mcp_researcher()
    api_origin = _api_origin()
    timeout = httpx2.Timeout(10)
    async with httpx2.AsyncClient(base_url=api_origin, timeout=timeout) as raw:
        metadata = await raw.get("/.well-known/oauth-protected-resource/mcp")
        _require(metadata.status_code == 200, "http_auth_contract")
        metadata_body = metadata.json()
        _require(metadata_body.get("resource") == RESOURCE_URL, "http_auth_contract")
        _require(
            metadata_body.get("authorization_servers") == [ISSUER_URL],
            "http_auth_contract",
        )
        unauthorized = await raw.post("/mcp", json={})
        _require(unauthorized.status_code == 401, "http_auth_contract")
        for path in ("/sse", "/mcp/sse", "/mcp/v1"):
            response = await raw.get(path)
            _require(response.status_code == 404, "http_auth_contract")

    async with _http_mcp_client(READ_TOKEN) as client:
        read_names = {
            tool.name for tool in (await _list_tools(client, transport="streamable_http")).tools
        }
        _require(read_names == READ_TOOLS, "http_discovery_contract")
        context = await _call_tool(
            client,
            "get_research_context",
            {},
            transport="streamable_http",
        )
        context_payload = _successful_content(context, "http_result_contract")
        _require(
            set(context_payload) == RESEARCH_CONTEXT_KEYS,
            "http_result_contract",
        )

    async with _http_mcp_client(ACTION_TOKEN) as client:
        action_names = {
            tool.name for tool in (await _list_tools(client, transport="streamable_http")).tools
        }
        _require(action_names == ACTION_TOOLS, "http_discovery_contract")
        _assert_no_generic_tools(action_names)
        submission = await _call_tool(
            client,
            "submit_research_run",
            {
                "request_id": "image-smoke-mcp-strategy",
                "folder_id": "folder_default",
                "name": "Production Image MCP Strategy",
                "hypothesis": HYPOTHESIS,
                "start_date": "2026-08-03",
                "end_date": "2026-08-05",
                "formula": FORMULA,
                "universe": "top300",
                "neutralization": "none",
                "research_kind": "strategy_backtest",
                "holdings_count": 1,
                "rebalance_every_sessions": 1,
            },
            transport="streamable_http",
        )
        submitted = _successful_content(submission, "http_submission_contract")
        _require(submitted.get("outcome") == "accepted", "http_submission_contract")
        _require(submitted.get("status") == "queued", "http_submission_contract")
        run_id = submitted.get("run_id")
        _require(isinstance(run_id, str) and run_id.startswith("run_"), "http_submission_contract")

    return {
        "status": "passed",
        "protected_resource_metadata": True,
        "unauthenticated_request_rejected": True,
        "legacy_routes_absent": True,
        "read_tool_count": len(READ_TOOLS),
        "action_tool_count": len(ACTION_TOOLS),
        "dangerous_tools_absent": sorted(DANGEROUS_TOOLS),
        "context_read": True,
        "submission_status": "queued",
        "run_id": run_id,
        "transport_disconnected": True,
        "random_seed": _random_seed(),
        "image_digest": _image_digest(),
    }


async def _http_after(run_id: str) -> dict[str, object]:
    async with _http_mcp_client(ACTION_TOKEN) as client:
        statuses, available_sections = await _poll_run_until_succeeded(client, run_id)
        summary_result = await _call_tool(
            client,
            "get_research_run_result",
            {"run_id": run_id, "section": "strategy_summary"},
            transport="streamable_http",
        )
        summary = _successful_content(summary_result, "http_result_contract")
        first_result = await _call_tool(
            client,
            "get_research_run_result",
            {
                "run_id": run_id,
                "section": "strategy_observations",
                "limit": 1,
            },
            transport="streamable_http",
        )
        first = _successful_content(first_result, "http_result_contract")
        first_items = first.get("items")
        next_page = first.get("next_cursor")
        _require(isinstance(first_items, list) and len(first_items) == 1, "http_result_contract")
        _require(isinstance(next_page, str) and next_page, "http_result_contract")
        second_result = await _call_tool(
            client,
            "get_research_run_result",
            {
                "run_id": run_id,
                "section": "strategy_observations",
                "limit": 1,
                "cursor": next_page,
            },
            transport="streamable_http",
        )
        second = _successful_content(second_result, "http_result_contract")
        second_items = second.get("items")
        _require(
            isinstance(second_items, list) and len(second_items) == 1,
            "http_result_contract",
        )
        _require(first_items[0] != second_items[0], "http_result_contract")
        _require(
            len(json.dumps(summary, separators=(",", ":")).encode()) < 256 * 1024,
            "http_result_contract",
        )

    return {
        "status": "passed",
        "run_id": run_id,
        "reconnected_transport": True,
        "terminal_status": "succeeded",
        "status_trace": statuses,
        "available_result_sections": available_sections,
        "strategy_summary_read": True,
        "observation_page_count": 2,
        "pagination_followed": True,
        "random_seed": _random_seed(),
        "image_digest": _image_digest(),
    }


async def _poll_run_until_succeeded(
    client: Client,
    run_id: str,
    *,
    timeout_seconds: float = 120,
) -> tuple[list[str], list[str]]:
    statuses: list[str] = []
    available_sections: list[str] | None = None
    deadline = anyio.current_time() + timeout_seconds
    try:
        with anyio.fail_after(timeout_seconds):
            while True:
                polled = await _call_tool(
                    client,
                    "get_research_run",
                    {"run_id": run_id},
                    transport="streamable_http",
                )
                detail = _successful_content(polled, "http_result_contract")
                status = detail.get("status")
                _require(isinstance(status, str), "http_result_contract")
                if not statuses or statuses[-1] != status:
                    statuses.append(status)
                if status == "succeeded":
                    raw_sections = detail.get("available_result_sections")
                    _require(isinstance(raw_sections, list), "http_result_contract")
                    available_sections = [str(section) for section in raw_sections]
                    break
                _require(status in {"queued", "running"}, "http_result_contract")
                retry_after = detail.get("retry_after_seconds")
                _require(
                    isinstance(retry_after, int | float) and retry_after >= 0,
                    "http_result_contract",
                )
                remaining = max(0.0, deadline - anyio.current_time())
                await anyio.sleep(min(float(retry_after), remaining))
    except TimeoutError:
        raise _SmokeFailure("timeout") from None
    _require(available_sections is not None, "http_result_contract")
    return statuses, available_sections


async def _stdio() -> dict[str, object]:
    result = await anyio.to_thread.run_sync(_raw_stdio_probe)
    return result


def _bootstrap_mcp_researcher() -> None:
    database = PostgresDatabase(_required_environment("THESISTRACE_DATABASE_URL"))
    database.open()
    try:
        ResearcherService(database).bootstrap(
            ResearcherIdentity(
                researcher_id=UUID(SUBJECT),
                email="mcp-image-smoke@example.test",
                display_label="mcp-image-smoke",
            )
        )
    finally:
        database.close()


def _raw_stdio_probe() -> dict[str, object]:
    executable = shutil.which("thesistrace-research-agent-mcp")
    _require(executable is not None, "stdio_contract")
    stderr_path = _evidence_dir() / "mcp-stdio-events.jsonl"
    stderr_stream = stderr_path.open("wb")
    process = subprocess.Popen(
        [executable],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_stream,
        env={
            **os.environ,
            **{name: _required_environment(name) for name in CORE_ENVIRONMENT_NAMES},
            "THESISTRACE_RESEARCH_AGENT_RESEARCHER_ID": SUBJECT,
        },
    )
    try:
        _record_protocol_envelope(
            transport="stdio",
            direction="request",
            method="initialize",
        )
        initialize = _raw_stdio_exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_HANDSHAKE_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "production-image-smoke", "version": "1"},
                },
            },
        )
        _record_protocol_envelope(
            transport="stdio",
            direction="response",
            method="initialize",
            outcome="succeeded",
        )
        initialize_result = initialize.get("result")
        _require(isinstance(initialize_result, dict), "stdio_contract")
        _require(
            initialize_result.get("protocolVersion") == LATEST_HANDSHAKE_VERSION,
            "stdio_contract",
        )
        _raw_stdio_send(
            process,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        _record_protocol_envelope(
            transport="stdio",
            direction="notification",
            method="notifications/initialized",
        )
        _record_protocol_envelope(
            transport="stdio",
            direction="request",
            method="tools/list",
        )
        tools = _raw_stdio_exchange(
            process,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_result = tools.get("result")
        _require(isinstance(tools_result, dict), "stdio_contract")
        raw_tools = tools_result.get("tools")
        _require(isinstance(raw_tools, list), "stdio_contract")
        names = [tool.get("name") for tool in raw_tools if isinstance(tool, dict)]
        _require(tuple(names) == SAFE_STDIO_TOOL_ORDER, "stdio_contract")
        _require(len(names) == 16 and len(set(names)) == 16, "stdio_contract")
        _assert_no_generic_tools(set(names))
        _record_protocol_envelope(
            transport="stdio",
            direction="response",
            method="tools/list",
            outcome="succeeded",
        )
        _record_protocol_envelope(
            transport="stdio",
            direction="request",
            method="tools/call",
            tool_name="get_research_context",
        )
        context = _raw_stdio_exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_research_context", "arguments": {}},
            },
        )
        result = context.get("result")
        _require(
            isinstance(result, dict) and result.get("isError") is False,
            "stdio_contract",
        )
        payload = result.get("structuredContent")
        _require(
            isinstance(payload, dict) and set(payload) == RESEARCH_CONTEXT_KEYS,
            "stdio_contract",
        )
        raw_trace_id = result.get("structuredContent", {}).get("trace_id")
        trace_id = raw_trace_id if isinstance(raw_trace_id, str) else None
        _record_protocol_envelope(
            transport="stdio",
            direction="response",
            method="tools/call",
            tool_name="get_research_context",
            outcome="succeeded",
            trace_id=trace_id,
        )
        _require(process.stdin is not None, "stdio_contract")
        process.stdin.close()
        try:
            returncode = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            raise _SmokeFailure("timeout") from None
        _require(process.stdout is not None, "stdio_contract")
        stdout_tail = process.stdout.read()
        _require(returncode == 0 and stdout_tail == b"", "stdio_contract")
    except BaseException:
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
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        stderr_stream.close()

    stderr_path.chmod(0o600)
    events = _plain_json_events(stderr_path)
    traces = _mcp_trace_ids(events, transport="stdio")
    _require(len(traces) == 1, "stdio_contract")
    return {
        "status": "passed",
        "tool_count": len(SAFE_STDIO_TOOL_ORDER),
        "dangerous_tools_absent": sorted(DANGEROUS_TOOLS),
        "context_read": True,
        "protocol_exit_clean": True,
        "stdout_protocol_clean": True,
        "trace_ids": traces,
        "random_seed": _random_seed(),
        "image_digest": _image_digest(),
    }


def _raw_stdio_send(
    process: subprocess.Popen[bytes],
    message: dict[str, object],
) -> None:
    _require(process.stdin is not None, "stdio_contract")
    serialized = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
    process.stdin.write(f"{serialized}\n".encode())
    process.stdin.flush()


def _raw_stdio_exchange(
    process: subprocess.Popen[bytes],
    message: dict[str, object],
) -> dict[str, object]:
    _raw_stdio_send(process, message)
    line = _read_bounded_process_line(process, timeout_seconds=20)
    value = json.loads(line)
    _require(isinstance(value, dict), "stdio_contract")
    return value


def _read_bounded_process_line(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    max_bytes: int = MAX_STDIO_RESPONSE_BYTES,
) -> bytes:
    _require(process.stdout is not None, "stdio_contract")
    deadline = time.monotonic() + timeout_seconds
    buffer = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _SmokeFailure("timeout")
        ready, _, _ = select.select([process.stdout], [], [], remaining)
        if not ready:
            raise _SmokeFailure("timeout")
        chunk = os.read(process.stdout.fileno(), min(65_536, max_bytes + 1 - len(buffer)))
        _require(bool(chunk), "stdio_contract")
        buffer.extend(chunk)
        newline = buffer.find(b"\n")
        if newline >= 0:
            _require(newline <= max_bytes, "stdio_contract")
            _require(not buffer[newline + 1 :], "stdio_contract")
            return bytes(buffer[:newline])
        _require(len(buffer) <= max_bytes, "stdio_contract")


def _evidence() -> dict[str, object]:
    evidence_dir = _evidence_dir()
    preflight = _read_json(evidence_dir / "mcp-preflight.json")
    before = _read_json(evidence_dir / "mcp-http-before.json")
    after = _read_json(evidence_dir / "mcp-http-after.json")
    stdio = _read_json(evidence_dir / "mcp-stdio.json")
    stopped = _read_object(evidence_dir / "mcp-api-stopped.json")
    _require(stopped.get("status") == "exited", "api_lifecycle_contract")
    _require(stopped.get("exit_code") == 143, "api_lifecycle_contract")
    _require(stopped.get("oom_killed") is False, "api_lifecycle_contract")
    _require(before.get("run_id") == after.get("run_id"), "http_result_contract")

    api_log_path = evidence_dir / "api-events.jsonl"
    _assert_graceful_mcp_restart(api_log_path)
    api_events = _container_events(api_log_path)
    http_traces = _mcp_trace_ids(api_events, transport="streamable_http")
    http_tools = {
        str(event.get("tool_name"))
        for event in api_events
        if event.get("component") == "research_agent_mcp"
        and event.get("transport") == "streamable_http"
    }
    _require(
        {
            "get_research_context",
            "submit_research_run",
            "get_research_run",
            "get_research_run_result",
        }
        <= http_tools,
        "protocol_evidence_contract",
    )
    _require(len(http_traces) == len(set(http_traces)), "protocol_evidence_contract")
    _require(
        all(
            event.get("subject", "").startswith("oauth_")
            for event in api_events
            if event.get("component") == "research_agent_mcp"
            and event.get("transport") == "streamable_http"
        ),
        "protocol_evidence_contract",
    )
    _assert_no_mcp_persistence()
    for value in (preflight, before, after, stdio):
        _assert_public_evidence(value)
        _require(value.get("random_seed") == _random_seed(), "protocol_evidence_contract")
        _require(value.get("image_digest") == _image_digest(), "protocol_evidence_contract")
    _assert_canaries_absent(evidence_dir)
    return {
        "status": "passed",
        "image_digest": _image_digest(),
        "random_seed": _random_seed(),
        "installed_mcp_sdk_version": preflight["installed_mcp_sdk_version"],
        "locked_mcp_sdk_version": preflight["locked_mcp_sdk_version"],
        "default_http_fail_closed": True,
        "oauth_streamable_http": True,
        "scope_filtered_discovery": True,
        "stdio_packaged_entrypoint": True,
        "api_lifespan_graceful_stop": True,
        "durable_run_id": before["run_id"],
        "durable_status_trace": [before["submission_status"], *after["status_trace"]],
        "transport_reconnected": True,
        "semantic_result_read": True,
        "pagination_followed": True,
        "http_trace_ids": http_traces,
        "stdio_trace_ids": stdio["trace_ids"],
        "legacy_and_generic_surfaces_absent": True,
        "mcp_specific_persistence_absent": True,
        "phase_exit_codes": {
            "preflight": 0,
            "http_before": 0,
            "api_stop": 0,
            "api_reopen": 0,
            "http_after": 0,
            "stdio": 0,
            "evidence": 0,
        },
        "public_deployment_performed": False,
        "production_oauth_verified": False,
    }


def _assert_graceful_mcp_restart(path: Path) -> None:
    lines = path.read_text(errors="replace").splitlines()

    def find_after(start: int, *fragments: str) -> int:
        for index in range(start + 1, len(lines)):
            if all(fragment in lines[index] for fragment in fragments):
                return index
        raise _SmokeFailure("api_lifecycle_contract")

    submitted = find_after(
        -1,
        '"component":"research_agent_mcp"',
        '"tool_name":"submit_research_run"',
    )
    shutting_down = find_after(submitted, "INFO:     Shutting down")
    shutdown_complete = find_after(
        shutting_down,
        "INFO:     Application shutdown complete.",
    )
    finished = find_after(shutdown_complete, "INFO:     Finished server process")
    restarted = find_after(finished, "INFO:     Started server process")
    find_after(
        restarted,
        '"component":"research_agent_mcp"',
        '"tool_name":"get_research_run"',
    )


def _assert_no_mcp_persistence() -> None:
    database = PostgresDatabase(_required_environment("THESISTRACE_DATABASE_URL"))
    database.open()
    try:
        with database.transaction() as transaction:
            rows = transaction.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                """
            ).fetchall()
    finally:
        database.close()
    for row in rows:
        _assert_persistence_table(str(row["table_schema"]), str(row["table_name"]))


def _assert_persistence_table(schema: str, table: str) -> None:
    # The Auth authorization server owns these tables; Core MCP remains stateless.
    auth_oauth_tables = {
        "oauthClient",
        "oauthResource",
        "oauthClientResource",
        "oauthRefreshToken",
        "oauthAccessToken",
        "oauthConsent",
        "oauthClientAssertion",
    }
    if schema == "auth" and table in auth_oauth_tables:
        return
    schema, table = schema.lower(), table.lower()
    forbidden_exact = {"users", "sessions", "audit_logs", "idempotency_keys"}
    _require("mcp" not in schema and "oauth" not in schema, "mcp_persistence_contract")
    _require("mcp" not in table and "oauth" not in table, "mcp_persistence_contract")
    _require(table not in forbidden_exact, "mcp_persistence_contract")


def _assert_no_generic_tools(names: set[str]) -> None:
    _require(names.isdisjoint(DANGEROUS_TOOLS), "http_discovery_contract")
    for name in names:
        _require(
            not any(fragment in name for fragment in FORBIDDEN_TOOL_FRAGMENTS),
            "http_discovery_contract",
        )


def _successful_content(result: object, code: str) -> dict[str, object]:
    _require(getattr(result, "is_error", None) is False, code)
    payload = getattr(result, "structured_content", None)
    _require(isinstance(payload, dict), code)
    return payload


async def _list_tools(client: Client, *, transport: str) -> ListToolsResult:
    _record_protocol_envelope(
        transport=transport,
        direction="request",
        method="tools/list",
    )
    try:
        result = await client.list_tools()
    except BaseException:
        _record_protocol_envelope(
            transport=transport,
            direction="response",
            method="tools/list",
            outcome="failed",
        )
        raise
    _record_protocol_envelope(
        transport=transport,
        direction="response",
        method="tools/list",
        outcome="succeeded",
    )
    return result


async def _call_tool(
    client: Client,
    tool_name: str,
    arguments: dict[str, object],
    *,
    transport: str,
) -> CallToolResult:
    _record_protocol_envelope(
        transport=transport,
        direction="request",
        method="tools/call",
        tool_name=tool_name,
    )
    try:
        result = await client.call_tool(tool_name, arguments)
    except BaseException:
        _record_protocol_envelope(
            transport=transport,
            direction="response",
            method="tools/call",
            tool_name=tool_name,
            outcome="failed",
        )
        raise
    outcome = "failed" if getattr(result, "is_error", True) else "succeeded"
    structured_content = getattr(result, "structured_content", None)
    raw_trace_id = (
        structured_content.get("trace_id")
        if isinstance(structured_content, dict)
        else None
    )
    trace_id = raw_trace_id if isinstance(raw_trace_id, str) else None
    _record_protocol_envelope(
        transport=transport,
        direction="response",
        method="tools/call",
        tool_name=tool_name,
        outcome=outcome,
        trace_id=trace_id,
    )
    return result


def _record_protocol_envelope(
    *,
    transport: str,
    direction: str,
    method: str,
    tool_name: str | None = None,
    outcome: str | None = None,
    trace_id: str | None = None,
) -> None:
    _require(transport in {"stdio", "streamable_http"}, "protocol_evidence_contract")
    _require(direction in {"notification", "request", "response"}, "protocol_evidence_contract")
    _require(
        method in {"initialize", "notifications/initialized", "tools/call", "tools/list"},
        "protocol_evidence_contract",
    )
    envelope = {
        "direction": direction,
        "method": method,
        "transport": transport,
    }
    if tool_name is not None:
        envelope["tool_name"] = tool_name
    if outcome is not None:
        envelope["outcome"] = outcome
    if trace_id is not None:
        _require(TRACE_PATTERN.fullmatch(trace_id) is not None, "protocol_evidence_contract")
        envelope["trace_id"] = trace_id
    path = _evidence_dir() / "mcp-protocol-envelopes.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(envelope, sort_keys=True, separators=(",", ":")))
        stream.write("\n")
    path.chmod(0o600)


@asynccontextmanager
async def _http_mcp_client(token: str) -> AsyncIterator[Client]:
    async with httpx2.AsyncClient(
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": TRUSTED_ORIGIN,
        },
        timeout=httpx2.Timeout(20),
    ) as http_client:
        async with Client(
            streamable_http_client(
                f"{_api_origin()}/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ),
            mode="legacy",
            read_timeout_seconds=20,
        ) as client:
            yield client


def _mcp_trace_ids(
    events: list[dict[str, object]],
    *,
    transport: str,
) -> list[str]:
    traces: list[str] = []
    for event in events:
        if event.get("component") != "research_agent_mcp":
            continue
        if event.get("event") != "mcp_tool_call_completed":
            continue
        if event.get("transport") != transport:
            continue
        trace_id = event.get("trace_id")
        _require(
            isinstance(trace_id, str) and TRACE_PATTERN.fullmatch(trace_id) is not None,
            "protocol_evidence_contract",
        )
        traces.append(trace_id)
    _require(traces, "protocol_evidence_contract")
    return traces


def _container_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text(errors="replace").splitlines():
        payload = line.partition("|")[2].strip()
        if not payload.startswith("{"):
            continue
        value = json.loads(payload)
        if isinstance(value, dict):
            events.append(value)
    return events


def _plain_json_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            raise _SmokeFailure("stdio_contract")
        value = json.loads(line)
        _require(isinstance(value, dict), "stdio_contract")
        events.append(value)
    return events


def _assert_canaries_absent(evidence_dir: Path) -> None:
    try:
        verify_evidence(evidence_dir)
    except EvidenceSanitizationError:
        raise _SmokeFailure("protocol_evidence_contract") from None


def _assert_public_evidence(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _require(key.lower() not in PRIVATE_EVIDENCE_KEYS, "protocol_evidence_contract")
            _assert_public_evidence(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_evidence(child)


def _write_private_state(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True))
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, object]:
    value = _read_object(path)
    _require(
        value.get("status") == "passed",
        "protocol_evidence_contract",
    )
    return value


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text())
    _require(isinstance(value, dict), "protocol_evidence_contract")
    return value


def _read_run_id() -> str:
    value = json.loads(_state_path().read_text())
    run_id = value.get("run_id") if isinstance(value, dict) else None
    _require(isinstance(run_id, str) and run_id.startswith("run_"), "http_result_contract")
    return run_id


def _state_path() -> Path:
    return _evidence_dir() / "mcp-private-state.json"


def _evidence_dir() -> Path:
    return Path(_required_environment("THESISTRACE_TEST_EVIDENCE_DIR"))


def _api_origin() -> str:
    return _required_environment("THESISTRACE_TEST_API_ORIGIN").rstrip("/")


def _image_digest() -> str:
    value = _required_environment("THESISTRACE_TEST_IMAGE_ID")
    _require(value.startswith("sha256:"), "image_package_contract")
    return value


def _random_seed() -> int:
    value = _required_environment("THESISTRACE_TEST_RANDOM_SEED")
    try:
        parsed = int(value)
    except ValueError:
        raise _SmokeFailure("protocol_evidence_contract") from None
    _require(parsed == 1401, "protocol_evidence_contract")
    return parsed


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise _SmokeFailure("image_package_contract")
    return value


def _require(condition: object, code: str) -> None:
    if not condition:
        raise _SmokeFailure(code)


def _error_types(error: BaseException) -> list[str]:
    pending = [error]
    result: list[str] = []
    while pending and len(result) < 16:
        current = pending.pop(0)
        error_type = type(current).__name__
        if error_type not in result:
            result.append(error_type)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions[:16])
    return result


def _nested_smoke_failure_code(error: BaseException) -> str | None:
    pending = [error]
    while pending:
        current = pending.pop(0)
        if isinstance(current, _SmokeFailure):
            return current.code
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions[:16])
    return None


def _exit_closed(code: str, *, error_types: list[str] | None = None) -> Never:
    safe_code = code if code in FAILURE_CODES else "unexpected"
    evidence = {"status": "failed", "failure_code": safe_code}
    if error_types is not None:
        evidence["error_types"] = error_types[:16]
    print(
        json.dumps(evidence, sort_keys=True),
        file=sys.stderr,
    )
    raise SystemExit(2) from None


if __name__ == "__main__":
    main()
