from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from typing import Never, TextIO

import pytest
from core_runtime import drop_product_schemas, isolated_core_settings
from jsonschema import validate
from research_agent_mcp_runtime import (
    assert_worker_succeeded,
    core_environment,
    publish_current_data,
    run_research_worker_once,
)

from thesistrace.entrypoints.runtime import core_environment_is_configured
from thesistrace.entrypoints.schema import initialize_core

SAFE_TOOL_NAMES = {
    "diagnose_alpha_formula",
    "get_alpha_catalog",
    "get_daily_track",
    "get_daily_track_result",
    "get_research_batch",
    "get_research_context",
    "get_research_run",
    "get_research_run_result",
    "list_daily_tracks",
    "list_research_batches",
    "list_research_runs",
    "retry_daily_track",
    "start_daily_track",
    "submit_research_batch",
    "submit_research_run",
}
PRIVATE_TERMS = (
    "checkpoint",
    "hypothesis",
    "manifest",
    "object_key",
    "private-formula",
    "sql",
    "token",
)
TRACE_PATTERN = re.compile(r"trace_[0-9a-f]{32}")
INSTRUMENT_PATTERN = re.compile(r"(?:equity:)?[0-9]{6}\.(?:SH|SZ)", re.IGNORECASE)
PHASE_TIMEOUT_SECONDS = 300
MAX_CODEX_EVENT_BYTES = 1_048_576
MAX_CODEX_EVENTS = 4_096
MAX_CODEX_TRANSCRIPT_BYTES = 16_777_216
MAX_CODEX_STDERR_BYTES = 4_194_304
MAX_CODEX_STDERR_TAIL_BYTES = 65_536
MAX_CODEX_RESULT_BYTES = 65_536
MAX_MCP_OPERATIONAL_BYTES = 1_048_576
KNOWN_CODEX_EVENT_TYPES = {
    "error",
    "item.completed",
    "item.started",
    "thread.started",
    "turn.completed",
    "turn.failed",
    "turn.started",
}
KNOWN_CODEX_ITEM_TYPES = {
    "agent_message",
    "mcp_tool_call",
    "reasoning",
    "todo_list",
}
SAFE_LEDGER_FIELDS = {
    "available_result_sections",
    "builtins",
    "comparison",
    "cursor",
    "diagnostics",
    "fields",
    "folders",
    "holdings_count",
    "identifiers",
    "items",
    "limit",
    "metrics",
    "next_cursor",
    "outcome",
    "rebalance_every_sessions",
    "request_id",
    "research_kind",
    "retry_after_seconds",
    "run_id",
    "section",
    "source",
    "status",
    "valid",
}
SAFE_DIAGNOSTIC_CODES = {"UNKNOWN_IDENTIFIER"}
SAFE_PHASE_FAILURES = {
    "host_output_contract",
    "host_runtime_error",
    "invalid_structured_output",
    "nonzero_exit_or_missing_result",
    "oversized_structured_output",
    "operational_trace_contract",
    "timeout",
}
SAFE_OPERATIONAL_TRACE_STATUSES = {"valid", "invalid"}
SAFE_ASSERTION_CODES = {
    "admission_outcome_contract",
    "durable_poll_contract",
    "formula_binding_contract",
    "formula_diagnostic_contract",
    "holdings_count_contract",
    "rationale_presence_contract",
    "rebalance_interval_contract",
    "request_id_contract",
    "research_kind_contract",
    "trajectory_inventory_contract",
    "tool_discovery_contract",
    "unknown",
}
SAFE_STDERR_CATEGORIES = {
    "api_request_error",
    "authentication_error",
    "cli_argument_error",
    "configuration_error",
    "connection_closed",
    "handshake_error",
    "mcp_startup_error",
    "permission_error",
    "process_exit_error",
    "response_schema_error",
    "spawn_not_found",
    "timeout",
    "tool_call_error",
    "tool_contract_error",
}
HOST_ERROR_CATEGORY_MARKERS = {
    "authentication_error": ("authentication", "not logged in"),
    "cli_argument_error": ("unexpected argument", "unknown argument"),
    "configuration_error": (
        "invalid config",
        "unknown feature",
        "unknown field",
        "unsupported",
    ),
    "connection_closed": ("connection closed", "closed before", "eof"),
    "handshake_error": (
        "handshake",
        "handshaking",
        "initialize response",
        "initialization",
    ),
    "permission_error": ("operation not permitted", "permission denied"),
    "process_exit_error": ("exit code", "exited"),
    "spawn_not_found": ("no such file", "not found", "failed to spawn"),
    "timeout": ("timed out", "timeout", "deadline", "elapsed"),
}
SAFE_HOST_ERROR_TERMS = {
    "api",
    "arguments",
    "authentication",
    "bad",
    "call",
    "characters",
    "client",
    "closed",
    "command",
    "config",
    "configuration",
    "connect",
    "connection",
    "deadline",
    "disabled",
    "elapsed",
    "eof",
    "error",
    "executable",
    "failed",
    "handshake",
    "initialize",
    "initialization",
    "invalid",
    "json",
    "length",
    "list",
    "maximum",
    "mcp",
    "missing",
    "model",
    "permission",
    "request",
    "required",
    "response",
    "rpc",
    "schema",
    "server",
    "spawn",
    "start",
    "startup",
    "timed",
    "timeout",
    "tool",
    "tools",
    "transport",
    "unavailable",
}
SAFE_HOST_ERROR_STATUS_CODES = {
    "400",
    "401",
    "403",
    "404",
    "408",
    "422",
    "429",
    "500",
    "502",
    "503",
    "504",
}
CODEX_FEATURES_DISABLED = (
    "apps",
    "browser_use",
    "browser_use_external",
    "code_mode",
    "code_mode_only",
    "computer_use",
    "image_generation",
    "js_repl",
    "multi_agent",
    "shell_tool",
    "unified_exec",
)


@pytest.mark.real_codex
def test_real_codex_completes_reconnected_stdio_research_loop(tmp_path: Path) -> None:
    codex = shutil.which("codex")
    if codex is None:
        pytest.fail("explicit real Codex acceptance requires the Codex CLI")
    evidence_path_value = os.environ.get("THESISTRACE_REAL_CODEX_EVIDENCE_PATH")
    if not evidence_path_value:
        pytest.fail("explicit real Codex acceptance requires an evidence path")
    if not core_environment_is_configured():
        pytest.fail("explicit real Codex acceptance requires the isolated Core runtime")
    evidence_path = Path(evidence_path_value)
    evidence: dict[str, object] = {
        "acceptance": "real_codex_stdio",
        "status": "running",
        "codex_version": _command_version([codex, "--version"]),
        "core_version": version("thesistrace"),
        "mcp_sdk_version": version("mcp"),
        "host_configuration": {
            "ephemeral": True,
            "ignore_user_config": True,
            "mcp_required": True,
            "mcp_server": "thesistrace",
            "sandbox": "read-only",
            "transport": "stdio",
            "entrypoint": "thesistrace-research-agent-mcp",
            "core_environment_visible_to_host": False,
            "disabled_non_mcp_features": list(CODEX_FEATURES_DISABLED),
            "injected_mcp_environment_names": sorted(
                name
                for name in os.environ
                if name.startswith("THESISTRACE_")
                and name != "THESISTRACE_REAL_CODEX_EVIDENCE_PATH"
            ),
        },
        "boundaries": {
            "second_host_verified": False,
            "production_oauth_verified": False,
            "public_" + "cloud" + "flare_deployed": False,
        },
    }
    _write_evidence(evidence_path, evidence)
    settings = isolated_core_settings(tmp_path / "canonical-data")
    settings.data_mount.mkdir(parents=True)
    settings.batch_attempt_control_directory.mkdir(parents=True)
    drop_product_schemas(settings)
    initialize_core(settings.database_url)
    first: _CodexPhase | None = None
    second: _CodexPhase | None = None
    try:
        sessions = publish_current_data(settings)
        mcp_environment = core_environment(settings)
        evidence["host_configuration"] = {
            **_require_mapping(evidence["host_configuration"]),
            "injected_mcp_environment_names": sorted(mcp_environment),
        }
        _write_evidence(evidence_path, evidence)
        first = _run_codex_phase(
            codex=codex,
            mcp_environment=mcp_environment,
            workspace=tmp_path / "codex-submit",
            schema=_submission_schema(),
            prompt=_submission_prompt(end_session=sessions[54]),
        )
        submission = first.final_output
        validate(submission, _submission_schema())
        _assert_tool_discovery(submission.get("visible_tool_names"))
        submission_trace = _assert_submission_trajectory(first.calls)
        _assert_only_mcp_product_access(first.events)

        worker_lock = Lock()
        worker_future = None
        worker_executor = ThreadPoolExecutor(max_workers=1)

        def start_worker_after_first_poll() -> None:
            nonlocal worker_future
            with worker_lock:
                if worker_future is not None:
                    return
                worker_future = worker_executor.submit(run_research_worker_once, settings)

        try:
            second = _run_codex_phase(
                codex=codex,
                mcp_environment=mcp_environment,
                workspace=tmp_path / "codex-reconnect",
                schema=_result_schema(),
                prompt=_result_prompt(run_id=submission_trace["run_id"]),
                on_completed_poll=start_worker_after_first_poll,
            )
            assert worker_future is not None, (
                "Codex never completed its first durable polling call"
            )
            assert_worker_succeeded(worker_future.result(timeout=70))
        finally:
            worker_executor.shutdown(wait=True, cancel_futures=True)
        result = second.final_output
        validate(result, _result_schema())
        result_trace = _assert_result_trajectory(
            second.calls,
            run_id=submission_trace["run_id"],
        )
        assert result["conclusion"] == _semantic_conclusion(
            _require_mapping(result_trace["strategy_summary"])
        )
        _assert_only_mcp_product_access(second.events)

        traces = (*first.operational_traces, *second.operational_traces)
        _assert_operational_traces_match_calls(first.operational_traces, first.calls)
        _assert_operational_traces_match_calls(second.operational_traces, second.calls)
        trace_ids = sorted({trace.trace_id for trace in traces})
        assert len(trace_ids) == len(traces), (
            "each completed MCP call must emit one unique operational trace identifier"
        )
        success_evidence = {
            **evidence,
            "status": "passed",
            "discovered_tool_names": submission["visible_tool_names"],
            "dangerous_tools_absent": [
                "cancel_research_batch",
                "cancel_research_run",
                "stop_daily_track",
            ],
            "authoring": {
                "context_read": submission_trace["context_read"],
                "catalog_read": submission_trace["catalog_read"],
                "invalid_formula_rejected": submission_trace[
                    "invalid_formula_rejected"
                ],
                "corrected_formula_valid": submission_trace["corrected_formula_valid"],
                "admission_attempt_count": submission_trace[
                    "admission_attempt_count"
                ],
                "admission_rejection_recovered": submission_trace[
                    "admission_rejection_recovered"
                ],
            },
            "durable_run": {
                "run_id": submission_trace["run_id"],
                "status_trace": [
                    submission_trace["initial_status"],
                    *result_trace["status_trace"],
                ],
                "reconnected_process": True,
                "retry_after_seconds": submission_trace["retry_after_seconds"],
            },
            "result_read": {
                "available_result_sections": result_trace[
                    "available_result_sections"
                ],
                "observation_page_count": result_trace["observation_page_count"],
                "first_page_had_next_cursor": result_trace[
                    "first_page_had_next_cursor"
                ],
                "observed_session_count": result_trace["observed_session_count"],
                "conclusion": result["conclusion"],
            },
            "trace_ids": trace_ids,
            "codex_event_summary": {
                "first_phase": _event_summary(first.events),
                "reconnected_phase": _event_summary(second.events),
            },
        }
        _write_success_evidence(
            evidence_path,
            success_evidence,
            calls=[*first.calls, *second.calls],
        )
    except BaseException as error:
        try:
            _write_failure_evidence(
                evidence_path,
                safe_base=evidence,
                error=error,
                first=first,
                second=second,
            )
        finally:
            _raise_closed_acceptance_failure()
    finally:
        drop_product_schemas(settings)


@dataclass(frozen=True)
class _ObservedMcpCall:
    tool: str
    arguments: dict[str, object]
    output: dict[str, object]
    completed_at: float


@dataclass(frozen=True)
class _OperationalTrace:
    tool: str
    trace_id: str


@dataclass(frozen=True)
class _CodexPhase:
    events: list[dict[str, object]]
    calls: list[_ObservedMcpCall]
    final_output: dict[str, object]
    stderr: str
    operational_traces: tuple[_OperationalTrace, ...]


class _CodexPhaseFailure(AssertionError):
    def __init__(self, diagnostics: dict[str, object]) -> None:
        super().__init__(json.dumps(diagnostics, sort_keys=True))
        self.diagnostics = diagnostics


class _TrajectoryContractError(AssertionError):
    def __init__(self, code: str) -> None:
        if code not in SAFE_ASSERTION_CODES - {"unknown"}:
            raise ValueError("trajectory assertion code is not allowlisted")
        super().__init__(code)
        self.code = code


class _RealCodexAcceptanceFailure(AssertionError):
    pass


def _raise_closed_acceptance_failure() -> Never:
    raise _RealCodexAcceptanceFailure("real_codex_acceptance_failed") from None


def _require_trajectory(condition: object, code: str) -> None:
    if not condition:
        raise _TrajectoryContractError(code)


def _run_codex_phase(
    *,
    codex: str,
    mcp_environment: Mapping[str, str],
    workspace: Path,
    schema: dict[str, object],
    prompt: str,
    on_completed_poll: Callable[[], None] | None = None,
) -> _CodexPhase:
    workspace.mkdir(parents=True)
    schema_path = workspace / "output-schema.json"
    result_path = workspace / "result.json"
    schema_path.write_text(json.dumps(schema, sort_keys=True))
    executable = Path(sys.executable).with_name("thesistrace-research-agent-mcp")
    if not executable.is_file():
        raise AssertionError(f"packaged MCP entrypoint is unavailable: {executable.name}")
    explicit_mcp_environment = _core_environment_from_mapping(mcp_environment)
    events: list[dict[str, object]] = []
    calls: list[_ObservedMcpCall] = []
    poll_started = False
    stderr_tail = bytearray()
    stderr_total_bytes = 0
    operational_traces: tuple[_OperationalTrace, ...] = ()
    operational_trace_error: AssertionError | OSError | None = None
    with _mcp_launch_configuration(
        workspace=workspace,
        executable=executable,
        environment=explicit_mcp_environment,
    ) as (mcp_command, mcp_arguments, operational_path):
        command = [
            codex,
            "--ask-for-approval",
            "never",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--cd",
            str(workspace),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "-c",
            f"mcp_servers.thesistrace.command={json.dumps(mcp_command)}",
            "-c",
            f"mcp_servers.thesistrace.args={json.dumps(list(mcp_arguments))}",
            "-c",
            f"mcp_servers.thesistrace.cwd={json.dumps(str(Path.cwd()))}",
            "-c",
            "mcp_servers.thesistrace.required=true",
            "-c",
            "mcp_servers.thesistrace.startup_timeout_sec=20",
            "-c",
            "mcp_servers.thesistrace.tool_timeout_sec=90",
            "-c",
            'mcp_servers.thesistrace.default_tools_approval_mode="approve"',
        ]
        for feature in CODEX_FEATURES_DISABLED:
            command.extend(("--disable", feature))
        command.append(prompt)
        sensitive_values = (
            explicit_mcp_environment[name]
            for name in (
                "THESISTRACE_DATABASE_URL",
                "THESISTRACE_S3_ACCESS_KEY_ID",
                "THESISTRACE_S3_SECRET_ACCESS_KEY",
            )
        )
        assert not any(
            secret in argument
            for secret in sensitive_values
            for argument in command
        )
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=_codex_host_environment(codex=codex, mcp_executable=executable),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        def read_events() -> None:
            nonlocal poll_started
            transcript_bytes = 0
            while True:
                raw_line = process.stdout.readline(MAX_CODEX_EVENT_BYTES + 1)
                if not raw_line:
                    return
                if len(raw_line) > MAX_CODEX_EVENT_BYTES:
                    raise AssertionError("Codex JSONL event exceeded the line limit")
                transcript_bytes += len(raw_line)
                if transcript_bytes > MAX_CODEX_TRANSCRIPT_BYTES:
                    raise AssertionError("Codex JSONL transcript exceeded the byte limit")
                if len(events) >= MAX_CODEX_EVENTS:
                    raise AssertionError("Codex JSONL transcript exceeded the event limit")
                try:
                    line = raw_line.decode("utf-8")
                    event = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise AssertionError(
                        "Codex emitted a non-JSON event line with SHA-256 "
                        f"{hashlib.sha256(raw_line).hexdigest()}"
                    ) from error
                if not isinstance(event, dict):
                    raise AssertionError("Codex JSONL event must be an object")
                events.append(event)
                call = _completed_mcp_call(event, completed_at=time.monotonic())
                if call is not None:
                    calls.append(call)
                if (
                    on_completed_poll is not None
                    and not poll_started
                    and call is not None
                    and call.tool == "get_research_run"
                ):
                    poll_started = True
                    on_completed_poll()

        def read_stderr() -> None:
            nonlocal stderr_total_bytes
            while True:
                chunk = process.stderr.read1(8192)
                if not chunk:
                    return
                stderr_total_bytes += len(chunk)
                stderr_tail.extend(chunk)
                del stderr_tail[:-MAX_CODEX_STDERR_TAIL_BYTES]
                if stderr_total_bytes > MAX_CODEX_STDERR_BYTES:
                    raise AssertionError("Codex stderr exceeded the byte limit")

        executor = ThreadPoolExecutor(max_workers=2)
        event_reader = executor.submit(read_events)
        stderr_reader = executor.submit(read_stderr)
        failure: BaseException | None = None
        returncode: int | None = None
        try:
            deadline = time.monotonic() + PHASE_TIMEOUT_SECONDS
            while returncode is None:
                if event_reader.done():
                    event_reader.result()
                if stderr_reader.done():
                    stderr_reader.result()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "real Codex MCP phase exceeded its bounded timeout"
                    )
                try:
                    returncode = process.wait(timeout=min(remaining, 0.25))
                except subprocess.TimeoutExpired:
                    continue
            event_reader.result(timeout=10)
            stderr_reader.result(timeout=10)
        except BaseException as error:
            failure = error
        finally:
            _terminate_process_group(process)
            process.stdout.close()
            process.stderr.close()
            for reader in (event_reader, stderr_reader):
                try:
                    reader.result(timeout=10)
                except BaseException as reader_error:
                    if failure is None:
                        failure = reader_error
            executor.shutdown(wait=True, cancel_futures=True)
        try:
            operational_traces = _read_operational_traces(operational_path)
        except (AssertionError, OSError) as error:
            operational_trace_error = error
    stderr = bytes(stderr_tail).decode("utf-8", errors="replace")
    operational_trace_status = (
        "invalid" if operational_trace_error is not None else "valid"
    )
    if failure is not None:
        raise _CodexPhaseFailure(
            {
                "phase_failure": _phase_failure_name(failure),
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": operational_trace_status,
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        ) from failure
    if returncode != 0 or not result_path.is_file():
        raise _CodexPhaseFailure(
            {
                "phase_failure": "nonzero_exit_or_missing_result",
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": operational_trace_status,
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        )
    if result_path.stat().st_size > MAX_CODEX_RESULT_BYTES:
        raise _CodexPhaseFailure(
            {
                "phase_failure": "oversized_structured_output",
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": operational_trace_status,
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        )
    with result_path.open("rb") as result_file:
        result_bytes = result_file.read(MAX_CODEX_RESULT_BYTES + 1)
    if len(result_bytes) > MAX_CODEX_RESULT_BYTES:
        raise _CodexPhaseFailure(
            {
                "phase_failure": "oversized_structured_output",
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": operational_trace_status,
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        )
    try:
        final_output = json.loads(result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _CodexPhaseFailure(
            {
                "phase_failure": "invalid_structured_output",
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": operational_trace_status,
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        ) from error
    if not isinstance(final_output, dict):
        raise _CodexPhaseFailure(
            {
                "phase_failure": "invalid_structured_output",
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": operational_trace_status,
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        )
    if operational_trace_error is not None:
        raise _CodexPhaseFailure(
            {
                "phase_failure": "operational_trace_contract",
                "returncode": returncode,
                "events": _event_summary(events),
                "mcp_ledger": _safe_mcp_ledger(calls),
                "operational_trace_status": "invalid",
                "stderr": _stderr_diagnostics(stderr, stderr_total_bytes),
            }
        ) from operational_trace_error
    return _CodexPhase(
        events=events,
        calls=calls,
        final_output=final_output,
        stderr=stderr,
        operational_traces=operational_traces,
    )


def _submission_prompt(*, end_session: str) -> str:
    return f"""Use only the ThesisTrace MCP server named `thesistrace`; do not use shell,
files, product HTTP routes, SQL, or internal Python APIs. Complete one research admission:
1. Inspect every Tool visible from the server and report their exact names.
2. Call get_research_context and get_alpha_catalog for close and ts_mean.
3. Diagnose `unknown_alpha + close`; use its structured diagnostics to correct the Formula,
   then diagnose the corrected Formula and require valid=true.
4. Submit one strategy_backtest using the default folder, dates 2026-08-03 through
   {end_session}, top300, neutralization none, holdings_count 51,
   rebalance_every_sessions 1, and a unique request_id beginning codex-real-acceptance-.
5. Call get_research_run exactly once for the returned durable run_id. No Worker is running,
   so require status queued and preserve its retry_after_seconds.
Return only the exact visible Tool names requested by the output Schema. Do not include Formula
or hypothesis text."""


def _result_prompt(*, run_id: str) -> str:
    return f"""Use only the ThesisTrace MCP server named `thesistrace`; do not use shell,
files, product HTTP routes, SQL, or internal Python APIs. This is a fresh Codex process after
the submitting MCP process disconnected. Poll durable ResearchRun `{run_id}` with
get_research_run until it reaches a terminal state, following retry_after_seconds before a
repeat poll. Require succeeded and report every distinct observed status in order. Then read
strategy_summary and exactly two strategy_observations pages with limit=1, following the
opaque next_cursor returned by page one. Classify the strategy's net cumulative return,
annualized excess return, and whether maximum drawdown is non-zero using only the closed
categories in the output Schema. Do not include Formula, hypothesis, cursor value, positions,
instrument identifiers, storage metadata, SQL, paths, or free-form prose."""


def _submission_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "visible_tool_names": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["visible_tool_names"],
    }


def _result_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "conclusion": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "return_direction": {
                        "enum": ["positive", "negative", "flat", "unavailable"]
                    },
                    "benchmark_comparison": {
                        "enum": [
                            "outperformed",
                            "underperformed",
                            "matched",
                            "unavailable",
                        ]
                    },
                    "drawdown": {
                        "enum": ["observed", "none", "unavailable"]
                    },
                },
                "required": [
                    "return_direction",
                    "benchmark_comparison",
                    "drawdown",
                ],
            },
        },
        "required": ["conclusion"],
    }


def _completed_mcp_call(
    event: Mapping[str, object],
    *,
    completed_at: float,
) -> _ObservedMcpCall | None:
    if event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if not isinstance(item, Mapping) or item.get("type") != "mcp_tool_call":
        return None
    assert item.get("server") == "thesistrace"
    tool = item.get("tool")
    assert isinstance(tool, str) and tool in SAFE_TOOL_NAMES
    assert item.get("status") == "completed"
    arguments = item.get("arguments")
    assert isinstance(arguments, dict)
    result = item.get("result")
    assert isinstance(result, Mapping)
    output = result.get("structured_content")
    assert isinstance(output, dict)
    return _ObservedMcpCall(
        tool=tool,
        arguments=arguments,
        output=output,
        completed_at=completed_at,
    )


def _assert_operational_traces_match_calls(
    traces: tuple[_OperationalTrace, ...],
    calls: list[_ObservedMcpCall],
) -> None:
    assert [trace.tool for trace in traces] == [call.tool for call in calls], (
        "MCP operational traces must match the completed Tool call sequence"
    )


def _assert_tool_discovery(value: object) -> list[str]:
    _require_trajectory(
        isinstance(value, list) and all(isinstance(item, str) for item in value),
        "tool_discovery_contract",
    )
    names = _require_string_list(value)
    _require_trajectory(
        set(names) == SAFE_TOOL_NAMES and len(names) == len(SAFE_TOOL_NAMES),
        "tool_discovery_contract",
    )
    return names


def _assert_submission_trajectory(calls: list[_ObservedMcpCall]) -> dict[str, object]:
    _require_trajectory(calls, "trajectory_inventory_contract")
    _require_trajectory(
        {call.tool for call in calls}
        <= {
            "get_research_context",
            "get_alpha_catalog",
            "diagnose_alpha_formula",
            "submit_research_run",
            "get_research_run",
        },
        "trajectory_inventory_contract",
    )
    contexts = [call for call in calls if call.tool == "get_research_context"]
    catalogs = [call for call in calls if call.tool == "get_alpha_catalog"]
    diagnoses = [call for call in calls if call.tool == "diagnose_alpha_formula"]
    submissions = [call for call in calls if call.tool == "submit_research_run"]
    polls = [call for call in calls if call.tool == "get_research_run"]
    _require_trajectory(
        len(contexts) == len(catalogs) == len(polls) == 1,
        "trajectory_inventory_contract",
    )
    _require_trajectory(len(diagnoses) >= 2, "trajectory_inventory_contract")
    _require_trajectory(submissions, "trajectory_inventory_contract")
    context = contexts[0]
    catalog = catalogs[0]
    _require_trajectory(context.arguments == {}, "trajectory_inventory_contract")
    catalog_identifiers = catalog.arguments.get("identifiers")
    _require_trajectory(
        isinstance(catalog_identifiers, list)
        and all(isinstance(item, str) for item in catalog_identifiers),
        "trajectory_inventory_contract",
    )
    _require_trajectory(
        set(_require_string_list(catalog_identifiers)) == {"close", "ts_mean"},
        "trajectory_inventory_contract",
    )
    first_submission_index = min(calls.index(call) for call in submissions)
    _require_trajectory(
        calls.index(context) < first_submission_index,
        "trajectory_inventory_contract",
    )
    _require_trajectory(
        calls.index(catalog) < first_submission_index,
        "trajectory_inventory_contract",
    )
    invalid_candidates = [
        call
        for call in diagnoses
        if call.arguments.get("source") == "unknown_alpha + close"
    ]
    _require_trajectory(
        len(invalid_candidates) == 1,
        "formula_diagnostic_contract",
    )
    invalid = invalid_candidates[0]
    invalid_source = invalid.arguments.get("source")
    _require_trajectory(
        invalid_source == "unknown_alpha + close",
        "formula_diagnostic_contract",
    )
    _require_trajectory(
        invalid.output.get("valid") is False,
        "formula_diagnostic_contract",
    )
    invalid_diagnostics = invalid.output.get("diagnostics")
    _require_trajectory(
        isinstance(invalid_diagnostics, list)
        and all(isinstance(item, Mapping) for item in invalid_diagnostics),
        "formula_diagnostic_contract",
    )
    _require_trajectory(
        any(
            item.get("code") == "UNKNOWN_IDENTIFIER"
            for item in _require_mapping_list(invalid_diagnostics)
        ),
        "formula_diagnostic_contract",
    )
    invalid_index = calls.index(invalid)
    _require_trajectory(
        invalid_index < min(calls.index(call) for call in submissions),
        "formula_diagnostic_contract",
    )
    valid_sources: set[str] = set()
    request_ids: list[str] = []
    for index, call in enumerate(calls):
        if index > invalid_index and call.tool == "diagnose_alpha_formula" and call.output == {
            "valid": True,
            "diagnostics": [],
        }:
            source = call.arguments.get("source")
            _require_trajectory(
                isinstance(source, str) and source != invalid_source,
                "formula_diagnostic_contract",
            )
            valid_sources.add(source)
        if call.tool != "submit_research_run":
            continue
        _require_trajectory(
            call.arguments.get("formula") in valid_sources,
            "formula_binding_contract",
        )
        hypothesis = call.arguments.get("hypothesis")
        _require_trajectory(
            isinstance(hypothesis, str) and hypothesis,
            "rationale_presence_contract",
        )
        _require_trajectory(
            call.arguments.get("research_kind") == "strategy_backtest",
            "research_kind_contract",
        )
        _require_trajectory(
            call.arguments.get("holdings_count") == 51,
            "holdings_count_contract",
        )
        _require_trajectory(
            call.arguments.get("rebalance_every_sessions") == 1,
            "rebalance_interval_contract",
        )
        request_id = call.arguments.get("request_id")
        _require_trajectory(
            isinstance(request_id, str)
            and request_id.startswith("codex-real-acceptance-"),
            "request_id_contract",
        )
        request_ids.append(request_id)
        if call.output.get("outcome") == "rejected":
            issues = call.output.get("issues")
            _require_trajectory(
                isinstance(issues, list)
                and bool(issues)
                and all(isinstance(item, Mapping) for item in issues),
                "admission_outcome_contract",
            )
        else:
            _require_trajectory(
                call.output.get("outcome") == "accepted",
                "admission_outcome_contract",
            )
    _require_trajectory(
        len(request_ids) == len(set(request_ids)),
        "request_id_contract",
    )
    accepted = [call for call in submissions if call.output.get("outcome") == "accepted"]
    _require_trajectory(len(accepted) == 1, "admission_outcome_contract")
    submitted = accepted[0]
    _require_trajectory(submitted == submissions[-1], "admission_outcome_contract")
    _require_trajectory(
        submitted.output.get("outcome") == "accepted",
        "admission_outcome_contract",
    )
    run_id = submitted.output.get("run_id")
    _require_trajectory(
        isinstance(run_id, str) and run_id,
        "admission_outcome_contract",
    )
    _require_trajectory(
        submitted.output.get("status") == "queued",
        "admission_outcome_contract",
    )
    polled = polls[0]
    _require_trajectory(calls[-1] == polled, "durable_poll_contract")
    _require_trajectory(
        calls.index(submitted) < calls.index(polled),
        "durable_poll_contract",
    )
    _require_trajectory(
        polled.arguments == {"run_id": run_id},
        "durable_poll_contract",
    )
    _require_trajectory(
        polled.output.get("status") == "queued",
        "durable_poll_contract",
    )
    _require_trajectory(
        polled.output.get("retry_after_seconds") == 2,
        "durable_poll_contract",
    )
    return {
        "context_read": True,
        "catalog_read": True,
        "invalid_formula_rejected": True,
        "corrected_formula_valid": True,
        "admission_attempt_count": len(submissions),
        "admission_rejection_recovered": any(
            call.output.get("outcome") == "rejected" for call in submissions
        ),
        "run_id": run_id,
        "initial_status": "queued",
        "retry_after_seconds": 2,
    }


def _assert_result_trajectory(
    calls: list[_ObservedMcpCall],
    *,
    run_id: str,
) -> dict[str, object]:
    poll_calls = [call for call in calls if call.tool == "get_research_run"]
    result_calls = [call for call in calls if call.tool == "get_research_run_result"]
    assert calls == [*poll_calls, *result_calls]
    assert len(poll_calls) >= 2
    assert all(call.arguments == {"run_id": run_id} for call in poll_calls)
    statuses = [call.output.get("status") for call in poll_calls]
    assert all(isinstance(status, str) for status in statuses)
    assert statuses[0] in {"queued", "running"}
    assert statuses[-1] == "succeeded"
    for previous, current in zip(poll_calls, poll_calls[1:], strict=False):
        retry_after = previous.output.get("retry_after_seconds")
        if retry_after is None:
            continue
        assert isinstance(retry_after, int | float) and retry_after >= 0
        assert current.completed_at - previous.completed_at >= retry_after - 0.1

    assert len(result_calls) == 3
    summary, first_page, second_page = result_calls
    assert summary.arguments == {"run_id": run_id, "section": "strategy_summary"}
    assert first_page.arguments == {
        "run_id": run_id,
        "section": "strategy_observations",
        "limit": 1,
    }
    first_items = _require_mapping_list(first_page.output.get("items"))
    assert len(first_items) == 1
    cursor = first_page.output.get("next_cursor")
    assert isinstance(cursor, str) and cursor
    assert second_page.arguments == {
        "run_id": run_id,
        "section": "strategy_observations",
        "limit": 1,
        "cursor": cursor,
    }
    second_items = _require_mapping_list(second_page.output.get("items"))
    assert len(second_items) == 1
    assert first_items[0].get("session") != second_items[0].get("session")
    available_sections = poll_calls[-1].output.get("available_result_sections")
    assert available_sections == [
        "factor",
        "strategy_summary",
        "strategy_observations",
        "terminal_strategy_state",
        "terminal_positions",
        "provenance",
    ]
    return {
        "status_trace": _distinct_strings(statuses),
        "available_result_sections": available_sections,
        "observation_page_count": 2,
        "first_page_had_next_cursor": True,
        "observed_session_count": 2,
        "strategy_summary": summary.output,
    }


def _semantic_conclusion(summary: Mapping[str, object]) -> dict[str, str]:
    comparison = _require_mapping(summary.get("comparison"))
    metrics = _require_mapping(summary.get("metrics"))
    maximum_drawdown = _require_mapping(metrics.get("maximum_drawdown"))
    return {
        "return_direction": _sign_category(
            comparison.get("net_cumulative_return"),
            positive="positive",
            negative="negative",
            zero="flat",
        ),
        "benchmark_comparison": _sign_category(
            comparison.get("annualized_excess_return"),
            positive="outperformed",
            negative="underperformed",
            zero="matched",
        ),
        "drawdown": _absolute_category(maximum_drawdown.get("value")),
    }


def _assert_only_mcp_product_access(events: list[dict[str, object]]) -> None:
    item_types = {
        str(item["type"])
        for event in events
        if isinstance((item := event.get("item")), Mapping) and "type" in item
    }
    assert "mcp_tool_call" in item_types
    assert item_types <= {"agent_message", "mcp_tool_call", "reasoning", "todo_list"}


def _event_summary(events: list[dict[str, object]]) -> dict[str, object]:
    item_types: dict[str, int] = {}
    tool_names: list[str] = []
    event_types: dict[str, int] = {}
    host_error_messages: list[str] = []
    for event in events:
        raw_event_type = event.get("type")
        event_type = (
            raw_event_type
            if isinstance(raw_event_type, str)
            and raw_event_type in KNOWN_CODEX_EVENT_TYPES
            else "unknown"
        )
        event_types[event_type] = event_types.get(event_type, 0) + 1
        host_error_message = _host_error_message(event)
        if host_error_message is not None:
            host_error_messages.append(host_error_message)
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        raw_item_type = item.get("type")
        item_type = (
            raw_item_type
            if isinstance(raw_item_type, str)
            and raw_item_type in KNOWN_CODEX_ITEM_TYPES
            else "unknown"
        )
        item_types[item_type] = item_types.get(item_type, 0) + 1
        if (
            event_type == "item.completed"
            and item_type == "mcp_tool_call"
            and isinstance((tool_name := item.get("tool")), str)
            and tool_name in SAFE_TOOL_NAMES
        ):
            tool_names.append(tool_name)
    return {
        "event_types": event_types,
        "item_types": item_types,
        "completed_mcp_tool_names": tool_names,
        "host_errors": _closed_host_error_diagnostics(host_error_messages),
    }


def _core_environment_from_mapping(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        name: environment[name]
        for name in (
            "THESISTRACE_DATABASE_URL",
            "THESISTRACE_S3_ENDPOINT_URL",
            "THESISTRACE_S3_ACCESS_KEY_ID",
            "THESISTRACE_S3_SECRET_ACCESS_KEY",
            "THESISTRACE_S3_BUCKET",
            "THESISTRACE_S3_REGION",
            "THESISTRACE_DATA_MOUNT",
            "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY",
        )
    }


@contextmanager
def _mcp_launch_configuration(
    *,
    workspace: Path,
    executable: Path,
    environment: Mapping[str, str],
) -> Iterator[tuple[str, tuple[str, ...], Path]]:
    launcher_path = workspace / ".thesistrace-mcp-launcher.py"
    environment_path = workspace / ".thesistrace-mcp-environment.json"
    operational_path = workspace / ".thesistrace-mcp-operational.jsonl"
    launcher_source = (
        "import json\n"
        "import os\n"
        "import pathlib\n"
        "import resource\n"
        "import sys\n"
        "environment_path = pathlib.Path(sys.argv[1])\n"
        "environment = json.loads(environment_path.read_text())\n"
        "if not isinstance(environment, dict):\n"
        "    raise SystemExit('invalid MCP environment')\n"
        "if not all(\n"
        "    isinstance(name, str) and name.startswith('THESISTRACE_')\n"
        "    and isinstance(value, str)\n"
        "    for name, value in environment.items()\n"
        "):\n"
        "    raise SystemExit('invalid MCP environment')\n"
        "child_environment = dict(os.environ)\n"
        "child_environment.update(environment)\n"
        f"resource.setrlimit(resource.RLIMIT_FSIZE, ({MAX_MCP_OPERATIONAL_BYTES}, "
        f"{MAX_MCP_OPERATIONAL_BYTES}))\n"
        "operational_fd = os.open(\n"
        "    sys.argv[3], os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW\n"
        ")\n"
        "os.dup2(operational_fd, 2)\n"
        "os.close(operational_fd)\n"
        "os.execve(sys.argv[2], [sys.argv[2]], child_environment)\n"
    )
    try:
        with _open_exclusive_text(
            launcher_path,
            mode=0o700,
        ) as launcher_file:
            launcher_file.write(launcher_source)
        with _open_exclusive_text(
            environment_path,
            mode=0o600,
        ) as environment_file:
            json.dump(dict(environment), environment_file, sort_keys=True)
        operational_descriptor = os.open(
            operational_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(operational_descriptor)
        yield (
            sys.executable,
            (
                str(launcher_path),
                str(environment_path),
                str(executable),
                str(operational_path),
            ),
            operational_path,
        )
    finally:
        operational_path.unlink(missing_ok=True)
        environment_path.unlink(missing_ok=True)
        launcher_path.unlink(missing_ok=True)


def _read_operational_traces(path: Path) -> tuple[_OperationalTrace, ...]:
    if not path.is_file():
        return ()
    if path.stat().st_size > MAX_MCP_OPERATIONAL_BYTES:
        raise AssertionError("MCP operational evidence exceeded the byte limit")
    traces: list[_OperationalTrace] = []
    with path.open("rb") as operational_file:
        for raw_line in operational_file:
            if len(raw_line) > MAX_CODEX_EVENT_BYTES:
                raise AssertionError("MCP operational event exceeded the line limit")
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AssertionError("MCP operational evidence was not JSONL") from error
            if not isinstance(event, Mapping):
                raise AssertionError("MCP operational event must be an object")
            if event.get("component") != "research_agent_mcp":
                continue
            if event.get("event") != "mcp_tool_call_completed":
                continue
            trace_id = event.get("trace_id")
            if not isinstance(trace_id, str) or TRACE_PATTERN.fullmatch(trace_id) is None:
                raise AssertionError("MCP operational trace identifier is invalid")
            tool = event.get("tool_name")
            if not isinstance(tool, str) or tool not in SAFE_TOOL_NAMES:
                raise AssertionError("MCP operational tool name is invalid")
            traces.append(_OperationalTrace(tool=tool, trace_id=trace_id))
    trace_ids = [trace.trace_id for trace in traces]
    assert len(trace_ids) == len(set(trace_ids)), (
        "MCP operational trace identifiers must be unique"
    )
    return tuple(traces)


def _open_exclusive_text(path: Path, *, mode: int) -> TextIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        return os.fdopen(descriptor, "w")
    except BaseException:
        os.close(descriptor)
        raise


def _codex_host_environment(*, codex: str, mcp_executable: Path) -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in (
            "CODEX_HOME",
            "HOME",
            "LANG",
            "LC_ALL",
            "LOGNAME",
            "NO_COLOR",
            "TERM",
            "TMPDIR",
            "USER",
        )
        if name in os.environ
    }
    environment["PATH"] = os.pathsep.join(
        dict.fromkeys(
            (
                str(Path(codex).parent),
                str(mcp_executable.parent),
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            )
        )
    )
    assert not any(name.startswith("THESISTRACE_") for name in environment)
    return environment


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if process.poll() is None:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait(timeout=5)


def _safe_mcp_ledger(calls: list[_ObservedMcpCall]) -> list[dict[str, object]]:
    ledger: list[dict[str, object]] = []
    for call in calls:
        diagnostic_codes = []
        diagnostics = call.output.get("diagnostics")
        if isinstance(diagnostics, list):
            diagnostic_codes = _safe_diagnostic_codes(diagnostics)
        status = call.output.get("status")
        ledger.append(
            {
                "tool": call.tool if call.tool in SAFE_TOOL_NAMES else "unknown",
                "argument_fields": _safe_field_names(call.arguments),
                "result_fields": _safe_field_names(call.output),
                "status": (
                    status
                    if isinstance(status, str)
                    and status
                    in {
                        "queued",
                        "running",
                        "succeeded",
                        "failed",
                        "cancelled",
                    }
                    else None
                ),
                "diagnostic_codes": diagnostic_codes,
            }
        )
    return ledger


def _safe_field_names(value: Mapping[str, object]) -> list[str]:
    known = sorted(
        key
        for key in value
        if isinstance(key, str) and key in SAFE_LEDGER_FIELDS
    )
    if len(known) != len(value):
        known.append("unknown")
    return known


def _safe_diagnostic_codes(diagnostics: list[object]) -> list[str]:
    codes: list[str] = []
    unknown = False
    for item in diagnostics:
        if not isinstance(item, Mapping):
            unknown = True
            continue
        code = item.get("code")
        if isinstance(code, str) and code in SAFE_DIAGNOSTIC_CODES:
            codes.append(code)
        else:
            unknown = True
    if unknown:
        codes.append("unknown")
    return codes


def _phase_failure_name(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, AssertionError):
        return "host_output_contract"
    return "host_runtime_error"


def _stderr_diagnostics(stderr_tail: str, total_bytes: int) -> dict[str, object]:
    return {
        "total_bytes": total_bytes,
        "tail_sha256": hashlib.sha256(stderr_tail.encode()).hexdigest(),
        "categories": _closed_host_error_categories(stderr_tail.splitlines()),
    }


def _host_error_message(event: Mapping[str, object]) -> str | None:
    if event.get("type") == "error" and isinstance(event.get("message"), str):
        return str(event["message"])
    if event.get("type") != "turn.failed":
        return None
    error = event.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("message"), str):
        return str(error["message"])
    return None


def _closed_host_error_diagnostics(messages: list[str]) -> dict[str, object]:
    lowered = "\n".join(messages).lower()
    return {
        "count": len(messages),
        "total_bytes": sum(len(_diagnostic_bytes(message)) for message in messages),
        "message_sha256": sorted(
            hashlib.sha256(_diagnostic_bytes(message)).hexdigest()
            for message in messages
        ),
        "categories": _closed_host_error_categories(messages),
        "safe_terms": sorted(
            term
            for term in SAFE_HOST_ERROR_TERMS
            if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", lowered)
        ),
        "safe_status_codes": sorted(
            {
                code
                for message in messages
                for code in _safe_http_status_codes(message.lower())
            }
        ),
    }


def _diagnostic_bytes(value: str) -> bytes:
    return value.encode("utf-8", errors="surrogatepass")


def _closed_host_error_categories(messages: Iterable[str]) -> list[str]:
    return sorted(
        {
            category
            for message in messages
            for category in _closed_host_error_categories_for_message(
                message.lower()
            )
        }
    )


def _closed_host_error_categories_for_message(lowered: str) -> set[str]:
    categories = {
        category
        for category, markers in HOST_ERROR_CATEGORY_MARKERS.items()
        if any(_contains_error_marker(lowered, marker) for marker in markers)
    }
    has_mcp_subject = any(
        _contains_error_marker(lowered, marker)
        for marker in ("mcp", "mcp client", "mcp server")
    )
    has_startup_semantics = any(
        _contains_error_marker(lowered, marker)
        for marker in (
            "initialize",
            "initialization",
            "spawn",
            "start",
            "startup",
        )
    )
    if has_mcp_subject and has_startup_semantics:
        categories.add("mcp_startup_error")
    if (
        _contains_error_marker(lowered, "request")
        and _contains_error_marker(lowered, "response")
        and _contains_error_marker(lowered, "error")
    ):
        categories.add("api_request_error")
    has_tool_contract_context = any(
        _contains_error_marker(lowered, marker)
        for marker in (
            "tool schema",
            "tools schema",
            "schema for tool",
            "tool definition",
        )
    ) or re.search(r"(?<![a-z0-9_])tools\[[0-9]+\]", lowered) is not None
    if has_tool_contract_context and any(
        _contains_error_marker(lowered, marker)
        for marker in ("invalid", "schema", "maximum", "length", "characters")
    ):
        categories.add("tool_contract_error")
    has_tool_subject = any(
        _contains_error_marker(lowered, marker) for marker in ("tool", "tools")
    )
    if has_tool_subject and _contains_error_marker(lowered, "call") and any(
        _contains_error_marker(lowered, marker)
        for marker in ("error", "failed", "invalid")
    ):
        categories.add("tool_call_error")
    if any(
        _contains_error_marker(lowered, marker)
        for marker in (
            "invalid response schema",
            "schema for response",
            "schema for response_format",
            "schema for response format",
            "invalid output schema",
        )
    ):
        categories.add("response_schema_error")
    return categories


def _safe_http_status_codes(lowered: str) -> set[str]:
    context = (
        r"(?<![a-z0-9_])"
        r"(?:http(?: status)?|status(?: code)?|error response(?: from server)?|response)"
        r"\s*(?::|=|-)?\s*"
    )
    return {
        match.group("code")
        for match in re.finditer(
            context
            + rf"(?P<code>{'|'.join(sorted(SAFE_HOST_ERROR_STATUS_CODES))})"
            + r"(?![0-9])",
            lowered,
        )
    }


def _contains_error_marker(lowered: str, marker: str) -> bool:
    return (
        re.search(
            rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])",
            lowered,
        )
        is not None
    )


def _safe_phase_diagnostics(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    phase_failure = value.get("phase_failure")
    returncode = value.get("returncode")
    operational_trace_status = value.get("operational_trace_status")
    return {
        "phase_failure": (
            phase_failure
            if isinstance(phase_failure, str)
            and phase_failure in SAFE_PHASE_FAILURES
            else "unknown"
        ),
        "returncode": (
            returncode
            if isinstance(returncode, int) and not isinstance(returncode, bool)
            else None
        ),
        "operational_trace_status": (
            operational_trace_status
            if isinstance(operational_trace_status, str)
            and operational_trace_status in SAFE_OPERATIONAL_TRACE_STATUSES
            else "invalid"
        ),
        "events": _safe_event_summary(value.get("events")),
        "mcp_ledger": _safe_serialized_mcp_ledger(value.get("mcp_ledger")),
        "stderr": _safe_stderr_diagnostics(value.get("stderr")),
    }


def _safe_event_summary(value: object) -> dict[str, object]:
    summary = value if isinstance(value, Mapping) else {}
    return {
        "event_types": _safe_count_map(
            summary.get("event_types"),
            allowed={*KNOWN_CODEX_EVENT_TYPES, "unknown"},
        ),
        "item_types": _safe_count_map(
            summary.get("item_types"),
            allowed={*KNOWN_CODEX_ITEM_TYPES, "unknown"},
        ),
        "completed_mcp_tool_names": _safe_closed_string_list(
            summary.get("completed_mcp_tool_names"),
            allowed={*SAFE_TOOL_NAMES, "unknown"},
        ),
        "host_errors": _safe_host_error_diagnostics(summary.get("host_errors")),
    }


def _safe_count_map(value: object, *, allowed: set[str]) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, count in value.items():
        safe_key = key if isinstance(key, str) and key in allowed else "unknown"
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            result[safe_key] = result.get(safe_key, 0) + count
    return result


def _safe_closed_string_list(value: object, *, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, str) and item in allowed else "unknown" for item in value]


def _safe_serialized_mcp_ledger(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for raw_item in value:
        item = raw_item if isinstance(raw_item, Mapping) else {}
        tool = item.get("tool")
        status = item.get("status")
        result.append(
            {
                "tool": (
                    tool
                    if isinstance(tool, str) and tool in SAFE_TOOL_NAMES
                    else "unknown"
                ),
                "argument_fields": _safe_closed_string_list(
                    item.get("argument_fields"),
                    allowed={*SAFE_LEDGER_FIELDS, "unknown"},
                ),
                "result_fields": _safe_closed_string_list(
                    item.get("result_fields"),
                    allowed={*SAFE_LEDGER_FIELDS, "unknown"},
                ),
                "status": (
                    status
                    if isinstance(status, str)
                    and status
                    in {
                        "cancelled",
                        "failed",
                        "queued",
                        "running",
                        "succeeded",
                    }
                    else None
                ),
                "diagnostic_codes": _safe_closed_string_list(
                    item.get("diagnostic_codes"),
                    allowed={*SAFE_DIAGNOSTIC_CODES, "unknown"},
                ),
            }
        )
    return result


def _safe_stderr_diagnostics(value: object) -> dict[str, object]:
    diagnostics = value if isinstance(value, Mapping) else {}
    total_bytes = diagnostics.get("total_bytes")
    tail_sha256 = diagnostics.get("tail_sha256")
    return {
        "total_bytes": (
            total_bytes
            if isinstance(total_bytes, int)
            and not isinstance(total_bytes, bool)
            and total_bytes >= 0
            else None
        ),
        "tail_sha256": (
            tail_sha256
            if isinstance(tail_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", tail_sha256)
            else None
        ),
        "categories": _safe_closed_string_list(
            diagnostics.get("categories"),
            allowed=SAFE_STDERR_CATEGORIES,
        ),
    }


def _safe_host_error_diagnostics(value: object) -> dict[str, object]:
    diagnostics = value if isinstance(value, Mapping) else {}
    count = diagnostics.get("count")
    total_bytes = diagnostics.get("total_bytes")
    hashes = diagnostics.get("message_sha256")
    return {
        "count": (
            count
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0
            else None
        ),
        "total_bytes": (
            total_bytes
            if isinstance(total_bytes, int)
            and not isinstance(total_bytes, bool)
            and total_bytes >= 0
            else None
        ),
        "message_sha256": [
            value
            for value in hashes
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        ]
        if isinstance(hashes, list)
        else [],
        "categories": _safe_closed_string_list(
            diagnostics.get("categories"),
            allowed=SAFE_STDERR_CATEGORIES,
        ),
        "safe_terms": _safe_closed_string_list(
            diagnostics.get("safe_terms"),
            allowed=SAFE_HOST_ERROR_TERMS,
        ),
        "safe_status_codes": _safe_closed_string_list(
            diagnostics.get("safe_status_codes"),
            allowed=SAFE_HOST_ERROR_STATUS_CODES,
        ),
    }


def _require_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    assert all(isinstance(key, str) for key in value)
    return value


def _require_string_list(value: object) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return value


def _require_mapping_list(value: object) -> list[Mapping[str, object]]:
    assert isinstance(value, list)
    assert all(isinstance(item, Mapping) for item in value)
    return value


def _distinct_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        assert isinstance(value, str)
        if not result or result[-1] != value:
            result.append(value)
    return result


def _sign_category(
    value: object,
    *,
    positive: str,
    negative: str,
    zero: str,
) -> str:
    if value is None:
        return "unavailable"
    assert isinstance(value, int | float) and not isinstance(value, bool)
    if value > 0:
        return positive
    if value < 0:
        return negative
    return zero


def _absolute_category(value: object) -> str:
    if value is None:
        return "unavailable"
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return "observed" if value != 0 else "none"


def _assert_sanitized_evidence(
    serialized: str,
    *,
    calls: list[_ObservedMcpCall],
) -> None:
    lowered = serialized.lower()
    assert not any(term in lowered for term in PRIVATE_TERMS)
    assert INSTRUMENT_PATTERN.search(serialized) is None
    for canary in _sensitive_canaries(calls):
        assert canary not in serialized


def _sensitive_canaries(calls: list[_ObservedMcpCall]) -> set[str]:
    canaries: set[str] = set()
    for call in calls:
        if call.tool == "diagnose_alpha_formula":
            source = call.arguments.get("source")
            if isinstance(source, str) and source:
                canaries.add(source)
        _collect_sensitive_values(call.arguments, canaries)
        _collect_sensitive_values(call.output, canaries)
    return canaries


def _collect_sensitive_values(
    value: object,
    canaries: set[str],
    *,
    key: str | None = None,
) -> None:
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _collect_sensitive_values(child, canaries, key=str(child_key))
        return
    if isinstance(value, list):
        for child in value:
            _collect_sensitive_values(child, canaries, key=key)
        return
    if key in {
        "cursor",
        "formula",
        "hypothesis",
        "instrument_id",
        "next_cursor",
        "object_key",
        "ts_code",
    } and isinstance(value, str) and value:
        canaries.add(value)


def _write_success_evidence(
    path: Path,
    evidence: Mapping[str, object],
    *,
    calls: list[_ObservedMcpCall],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True)
    _assert_sanitized_evidence(serialized, calls=calls)
    _write_evidence(path, evidence)


def _write_failure_evidence(
    path: Path,
    *,
    safe_base: Mapping[str, object],
    error: BaseException,
    first: _CodexPhase | None,
    second: _CodexPhase | None,
) -> None:
    failure_evidence = {
        **safe_base,
        "status": "failed",
        "failure": {
            "error_type": type(error).__name__,
            "error_sha256": hashlib.sha256(str(error).encode()).hexdigest(),
            "assertion_code": _safe_assertion_code(error),
            "phase_diagnostics": (
                _safe_phase_diagnostics(error.diagnostics)
                if isinstance(error, _CodexPhaseFailure)
                else None
            ),
            "first_phase": _event_summary(first.events) if first is not None else None,
            "reconnected_phase": (
                _event_summary(second.events) if second is not None else None
            ),
            "discovered_tool_names": _safe_discovered_tool_names(first),
            "mcp_ledger": _safe_mcp_ledger(
                [
                    *(first.calls if first is not None else []),
                    *(second.calls if second is not None else []),
                ]
            ),
        },
    }
    serialized = json.dumps(
        failure_evidence,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )
    _assert_sanitized_evidence(serialized, calls=[])
    _write_evidence(path, failure_evidence)


def _safe_discovered_tool_names(phase: _CodexPhase | None) -> list[str]:
    if phase is None:
        return []
    names = phase.final_output.get("visible_tool_names")
    return _safe_closed_string_list(
        names,
        allowed={*SAFE_TOOL_NAMES, "unknown"},
    )


def _safe_assertion_code(error: BaseException) -> str | None:
    if not isinstance(error, AssertionError):
        return None
    if not isinstance(error, _TrajectoryContractError):
        return "unknown"
    return error.code if error.code in SAFE_ASSERTION_CODES else "unknown"


def _write_evidence(path: Path, evidence: Mapping[str, object]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(f"{serialized}\n")
    temporary_path.chmod(0o600)
    os.replace(temporary_path, path)


def _command_version(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip() or completed.stderr.strip()


def _call(
    tool: str,
    arguments: dict[str, object],
    output: dict[str, object],
    completed_at: float,
) -> _ObservedMcpCall:
    return _ObservedMcpCall(
        tool=tool,
        arguments=arguments,
        output=output,
        completed_at=completed_at,
    )


def _submission_calls_for_failure_test(
    *,
    accepted_request_id: str = "codex-real-acceptance-accepted",
    catalog_identifiers: object = None,
    invalid_source: str = "unknown_alpha + close",
    invalid_diagnostics: object = None,
    rejected_issues: object = None,
    submission_overrides: Mapping[str, object] | None = None,
) -> list[_ObservedMcpCall]:
    diagnostics = (
        [{"code": "UNKNOWN_IDENTIFIER"}]
        if invalid_diagnostics is None
        else invalid_diagnostics
    )
    common = {
        "hypothesis": "fixture-hypothesis-canary",
        "research_kind": "strategy_backtest",
        "holdings_count": 51,
        "rebalance_every_sessions": 1,
    }
    if submission_overrides is not None:
        common.update(submission_overrides)
    calls = [
        _call("get_research_context", {}, {"folders": []}, 1),
        _call(
            "get_alpha_catalog",
            {
                "identifiers": (
                    ["close", "ts_mean"]
                    if catalog_identifiers is None
                    else catalog_identifiers
                )
            },
            {"fields": [], "builtins": []},
            2,
        ),
        _call(
            "diagnose_alpha_formula",
            {"source": invalid_source},
            {"valid": False, "diagnostics": diagnostics},
            3,
        ),
        _call(
            "diagnose_alpha_formula",
            {"source": "close"},
            {"valid": True, "diagnostics": []},
            4,
        ),
    ]
    if rejected_issues is not None:
        calls.append(
            _call(
                "submit_research_run",
                {
                    **common,
                    "formula": "close",
                    "request_id": "codex-real-acceptance-rejected",
                },
                {"outcome": "rejected", "issues": rejected_issues},
                5,
            )
        )
    calls.extend(
        (
            _call(
                "submit_research_run",
                {
                    **common,
                    "formula": "close",
                    "request_id": accepted_request_id,
                },
                {"outcome": "accepted", "run_id": "run_test", "status": "queued"},
                6,
            ),
            _call(
                "get_research_run",
                {"run_id": "run_test"},
                {"status": "queued", "retry_after_seconds": 2},
                7,
            ),
        )
    )
    return calls


def test_codex_event_contract_is_strict_and_preserves_structured_result() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "thesistrace",
            "tool": "get_research_context",
            "status": "completed",
            "arguments": {},
            "result": {"content": [], "structured_content": {"folders": []}},
        },
    }

    call = _completed_mcp_call(event, completed_at=12.5)

    assert call == _ObservedMcpCall(
        tool="get_research_context",
        arguments={},
        output={"folders": []},
        completed_at=12.5,
    )
    aliased = json.loads(json.dumps(event))
    aliased["item"]["tool_name"] = aliased["item"].pop("tool")
    with pytest.raises(AssertionError):
        _completed_mcp_call(aliased, completed_at=12.5)


def test_trajectory_evidence_is_derived_from_tool_arguments_and_results() -> None:
    submitted_arguments = {
        "formula": "ts_mean(close, 5)",
        "hypothesis": "fixture-hypothesis-canary",
        "research_kind": "strategy_backtest",
        "holdings_count": 51,
        "rebalance_every_sessions": 1,
        "request_id": "codex-real-acceptance-test",
    }
    first = [
        _call("get_research_context", {}, {"folders": []}, 1),
        _call(
            "get_alpha_catalog",
            {"identifiers": ["close", "ts_mean"]},
            {"fields": [], "builtins": []},
            2,
        ),
        _call(
            "diagnose_alpha_formula",
            {"source": "unknown_alpha + close"},
            {"valid": False, "diagnostics": [{"code": "UNKNOWN_IDENTIFIER"}]},
            3,
        ),
        _call(
            "diagnose_alpha_formula",
            {"source": "ts_mean(close, 5)"},
            {"valid": True, "diagnostics": []},
            4,
        ),
        _call(
            "submit_research_run",
            submitted_arguments,
            {"outcome": "accepted", "run_id": "run_test", "status": "queued"},
            5,
        ),
        _call(
            "get_research_run",
            {"run_id": "run_test"},
            {"status": "queued", "retry_after_seconds": 2},
            6,
        ),
    ]
    submission = _assert_submission_trajectory(first)
    summary = {
        "comparison": {
            "net_cumulative_return": 0.2,
            "annualized_excess_return": -0.1,
        },
        "metrics": {"maximum_drawdown": {"value": -0.05}},
    }
    second = [
        _call(
            "get_research_run",
            {"run_id": "run_test"},
            {"status": "queued", "retry_after_seconds": 2},
            10,
        ),
        _call(
            "get_research_run",
            {"run_id": "run_test"},
            {
                "status": "succeeded",
                "retry_after_seconds": None,
                "available_result_sections": [
                    "factor",
                    "strategy_summary",
                    "strategy_observations",
                    "terminal_strategy_state",
                    "terminal_positions",
                    "provenance",
                ],
            },
            12,
        ),
        _call(
            "get_research_run_result",
            {"run_id": "run_test", "section": "strategy_summary"},
            summary,
            13,
        ),
        _call(
            "get_research_run_result",
            {
                "run_id": "run_test",
                "section": "strategy_observations",
                "limit": 1,
            },
            {"items": [{"session": "2026-08-03"}], "next_cursor": "cursor-canary"},
            14,
        ),
        _call(
            "get_research_run_result",
            {
                "run_id": "run_test",
                "section": "strategy_observations",
                "limit": 1,
                "cursor": "cursor-canary",
            },
            {"items": [{"session": "2026-08-04"}], "next_cursor": None},
            15,
        ),
    ]

    result = _assert_result_trajectory(second, run_id=str(submission["run_id"]))

    assert result["status_trace"] == ["queued", "succeeded"]
    assert _semantic_conclusion(_require_mapping(result["strategy_summary"])) == {
        "return_direction": "positive",
        "benchmark_comparison": "underperformed",
        "drawdown": "observed",
    }


def test_submission_trajectory_accepts_structured_rejection_recovery() -> None:
    common = {
        "hypothesis": "fixture-hypothesis-canary",
        "research_kind": "strategy_backtest",
        "holdings_count": 51,
        "rebalance_every_sessions": 1,
    }
    calls = [
        _call(
            "diagnose_alpha_formula",
            {"source": "unknown_alpha + close"},
            {"valid": False, "diagnostics": [{"code": "UNKNOWN_IDENTIFIER"}]},
            1,
        ),
        _call(
            "get_alpha_catalog",
            {"identifiers": ["close", "ts_mean"]},
            {"fields": [], "builtins": []},
            2,
        ),
        _call("get_research_context", {}, {"folders": []}, 3),
        _call(
            "diagnose_alpha_formula",
            {"source": "ts_mean(close, 5)"},
            {"valid": True, "diagnostics": []},
            4,
        ),
        _call(
            "submit_research_run",
            {
                **common,
                "formula": "ts_mean(close, 5)",
                "request_id": "codex-real-acceptance-rejected",
            },
            {
                "outcome": "rejected",
                "issues": [{"code": "INSUFFICIENT_CALCULATION_WARMUP"}],
            },
            5,
        ),
        _call(
            "diagnose_alpha_formula",
            {"source": "close"},
            {"valid": True, "diagnostics": []},
            6,
        ),
        _call(
            "submit_research_run",
            {
                **common,
                "formula": "close",
                "request_id": "codex-real-acceptance-accepted",
            },
            {
                "outcome": "accepted",
                "run_id": "run_recovered",
                "status": "queued",
            },
            7,
        ),
        _call(
            "get_research_run",
            {"run_id": "run_recovered"},
            {"status": "queued", "retry_after_seconds": 2},
            8,
        ),
    ]

    trace = _assert_submission_trajectory(calls)

    assert trace["run_id"] == "run_recovered"
    assert trace["admission_attempt_count"] == 2
    assert trace["admission_rejection_recovered"] is True


@pytest.mark.parametrize(
    "leaked",
    (
        "ts_mean(close, 5)",
        "fixture-hypothesis-canary",
        "opaque-cursor-canary",
        "equity:000001.SZ",
    ),
)
def test_evidence_rejects_semantic_canaries(leaked: str) -> None:
    call = _ObservedMcpCall(
        tool="diagnose_alpha_formula",
        arguments={
            "source": "ts_mean(close, 5)",
            "hypothesis": "fixture-hypothesis-canary",
            "cursor": "opaque-cursor-canary",
        },
        output={"instrument_id": "equity:000001.SZ"},
        completed_at=1,
    )

    with pytest.raises(AssertionError):
        _assert_sanitized_evidence(
            json.dumps({"conclusion": leaked}),
            calls=[call],
        )


def test_real_acceptance_failure_hides_dynamic_values_from_pytest_output(
    tmp_path: Path,
) -> None:
    canaries = (
        "dynamic-formula-canary",
        "dynamic-hypothesis-canary",
        "dynamic-cursor-canary",
    )
    regression = tmp_path / "test_closed_failure.py"
    regression.write_text(
        "import os\n"
        "from test_real_codex_research_agent_mcp import "
        "_raise_closed_acceptance_failure\n\n"
        "def test_closed_failure():\n"
        "    try:\n"
        "        raise AssertionError(os.environ['DYNAMIC_PRIVATE_CANARIES'])\n"
        "    except AssertionError:\n"
        "        _raise_closed_acceptance_failure()\n"
    )
    environment = {
        **os.environ,
        "DYNAMIC_PRIVATE_CANARIES": "|".join(canaries),
        "PYTHONPATH": os.pathsep.join(
            filter(
                None,
                (
                    str(Path(__file__).parent),
                    os.environ.get("PYTHONPATH"),
                ),
            )
        ),
    }

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(regression)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "real_codex_acceptance_failed" in output
    assert not any(canary in output for canary in canaries)


def test_trajectory_failure_persists_only_allowlisted_assertion_code(
    tmp_path: Path,
) -> None:
    with pytest.raises(_TrajectoryContractError) as raised:
        _assert_submission_trajectory([])
    evidence_path = tmp_path / "trajectory-failure.json"

    _write_failure_evidence(
        evidence_path,
        safe_base={"acceptance": "real_codex_stdio", "status": "running"},
        error=raised.value,
        first=None,
        second=None,
    )

    persisted = json.loads(evidence_path.read_text())
    assert persisted["failure"]["assertion_code"] == (
        "trajectory_inventory_contract"
    )


def test_tool_discovery_failure_persists_only_closed_names_and_code(
    tmp_path: Path,
) -> None:
    reported_names = ["get_research_context", "private-tool-canary"]
    with pytest.raises(_TrajectoryContractError) as raised:
        _assert_tool_discovery(reported_names)
    phase = _CodexPhase(
        events=[],
        calls=[],
        final_output={"visible_tool_names": reported_names},
        stderr="",
        operational_traces=(),
    )
    evidence_path = tmp_path / "tool-discovery-failure.json"

    _write_failure_evidence(
        evidence_path,
        safe_base={"acceptance": "real_codex_stdio", "status": "running"},
        error=raised.value,
        first=phase,
        second=None,
    )

    persisted = json.loads(evidence_path.read_text())
    assert persisted["failure"]["assertion_code"] == "tool_discovery_contract"
    assert persisted["failure"]["discovered_tool_names"] == [
        "get_research_context",
        "unknown",
    ]
    assert "private-tool-canary" not in evidence_path.read_text()


@pytest.mark.parametrize(
    ("calls", "expected_code"),
    (
        (
            _submission_calls_for_failure_test(catalog_identifiers={}),
            "trajectory_inventory_contract",
        ),
        (
            _submission_calls_for_failure_test(invalid_source="other_invalid + close"),
            "formula_diagnostic_contract",
        ),
        (
            _submission_calls_for_failure_test(invalid_diagnostics={}),
            "formula_diagnostic_contract",
        ),
        (
            _submission_calls_for_failure_test(rejected_issues={}),
            "admission_outcome_contract",
        ),
        (
            _submission_calls_for_failure_test(
                submission_overrides={"hypothesis": ""}
            ),
            "rationale_presence_contract",
        ),
        (
            _submission_calls_for_failure_test(
                submission_overrides={"research_kind": "private-kind-canary"}
            ),
            "research_kind_contract",
        ),
        (
            _submission_calls_for_failure_test(
                submission_overrides={"holdings_count": 52}
            ),
            "holdings_count_contract",
        ),
        (
            _submission_calls_for_failure_test(
                submission_overrides={"rebalance_every_sessions": 2}
            ),
            "rebalance_interval_contract",
        ),
        (
            _submission_calls_for_failure_test(
                accepted_request_id="private-request-canary"
            ),
            "request_id_contract",
        ),
    ),
)
def test_trajectory_structure_failures_persist_closed_assertion_code(
    tmp_path: Path,
    calls: list[_ObservedMcpCall],
    expected_code: str,
) -> None:
    with pytest.raises(_TrajectoryContractError) as raised:
        _assert_submission_trajectory(calls)
    evidence_path = tmp_path / "trajectory-structure-failure.json"

    _write_failure_evidence(
        evidence_path,
        safe_base={"acceptance": "real_codex_stdio", "status": "running"},
        error=raised.value,
        first=None,
        second=None,
    )

    persisted = json.loads(evidence_path.read_text())
    assert persisted["failure"]["assertion_code"] == expected_code
    assert "private-kind-canary" not in evidence_path.read_text()
    assert "private-request-canary" not in evidence_path.read_text()


def test_sanitizer_failure_persists_only_a_fresh_failure_envelope(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    safe_base = {"acceptance": "real_codex_stdio", "status": "running"}
    call = _ObservedMcpCall(
        tool="diagnose_alpha_formula",
        arguments={"source": "private-formula-canary"},
        output={"valid": True},
        completed_at=1,
    )
    _write_evidence(evidence_path, safe_base)

    with pytest.raises(AssertionError) as raised:
        _write_success_evidence(
            evidence_path,
            {**safe_base, "status": "passed", "conclusion": "private-formula-canary"},
            calls=[call],
        )
    _write_failure_evidence(
        evidence_path,
        safe_base=safe_base,
        error=raised.value,
        first=None,
        second=None,
    )

    persisted = evidence_path.read_text()
    assert json.loads(persisted)["status"] == "failed"
    assert "private-formula-canary" not in persisted


def test_failure_evidence_closes_unknown_host_controlled_strings(tmp_path: Path) -> None:
    canaries = {
        "event-formula-canary",
        "item-formula-canary",
        "field-formula-canary",
        "diagnostic-formula-canary",
        "host-error-formula-canary",
        "tool-formula-canary",
    }
    phase = _CodexPhase(
        events=[
            {
                "type": "event-formula-canary",
                "item": {"type": "item-formula-canary"},
            },
            {
                "type": "error",
                "message": (
                    "MCP server failed to start after handshake timeout: "
                    "host-error-formula-canary"
                ),
            },
        ],
        calls=[],
        final_output={},
        stderr="",
        operational_traces=(),
    )
    error = _CodexPhaseFailure(
        {
            "phase_failure": "tool-formula-canary",
            "returncode": 1,
            "events": {
                "event_types": {"event-formula-canary": 1},
                "item_types": {"item-formula-canary": 1},
                "completed_mcp_tool_names": ["tool-formula-canary"],
            },
            "mcp_ledger": [
                {
                    "tool": "tool-formula-canary",
                    "argument_fields": ["field-formula-canary"],
                    "result_fields": ["field-formula-canary"],
                    "status": "status-formula-canary",
                    "diagnostic_codes": ["diagnostic-formula-canary"],
                }
            ],
            "stderr": {
                "total_bytes": 1,
                "tail_sha256": "0" * 64,
                "categories": ["diagnostic-formula-canary"],
            },
        }
    )
    evidence_path = tmp_path / "failure.json"

    _write_failure_evidence(
        evidence_path,
        safe_base={"acceptance": "real_codex_stdio", "status": "running"},
        error=error,
        first=phase,
        second=None,
    )

    persisted = evidence_path.read_text()
    assert not any(canary in persisted for canary in canaries)
    assert '"unknown"' in persisted
    assert '"handshake_error"' in persisted
    assert '"mcp_startup_error"' in persisted
    assert '"timeout"' in persisted


def test_host_failure_diagnostics_are_closed_and_actionable() -> None:
    message = (
        "MCP client failed to start: initialize response connection closed; "
        "permission denied; private-formula-canary"
    )

    event_diagnostics = _closed_host_error_diagnostics([message])
    stderr_diagnostics = _stderr_diagnostics(message, len(message.encode()))

    assert event_diagnostics["categories"] == [
        "connection_closed",
        "handshake_error",
        "mcp_startup_error",
        "permission_error",
    ]
    assert event_diagnostics["safe_terms"] == [
        "client",
        "closed",
        "connection",
        "failed",
        "initialize",
        "mcp",
        "permission",
        "response",
        "start",
    ]
    assert stderr_diagnostics["categories"] == [
        "connection_closed",
        "handshake_error",
        "mcp_startup_error",
        "permission_error",
    ]
    assert "private-formula-canary" not in json.dumps(event_diagnostics)
    assert "private-formula-canary" not in json.dumps(stderr_diagnostics)


def test_host_failure_categories_require_bounded_startup_semantics() -> None:
    unrelated_path = _stderr_diagnostics(
        "failed to open /tmp/theoffice-note",
        len(b"failed to open /tmp/theoffice-note"),
    )
    ordinary_tool_error = _closed_host_error_diagnostics(
        ["MCP server returned a tool error"]
    )

    assert "connection_closed" not in unrelated_path["categories"]
    assert "mcp_startup_error" not in ordinary_tool_error["categories"]


def test_host_failure_diagnostics_classify_protocol_contracts_without_raw_text() -> None:
    diagnostics = _closed_host_error_diagnostics(
        [
            "API request error response 400: invalid tools schema maximum length; "
            "private-formula-canary 418"
        ]
    )

    assert diagnostics["categories"] == [
        "api_request_error",
        "tool_contract_error",
    ]
    assert diagnostics["safe_status_codes"] == ["400"]
    assert "private-formula-canary" not in json.dumps(diagnostics)
    assert "418" not in json.dumps(diagnostics)


def test_host_failure_diagnostics_match_bounded_schema_contexts() -> None:
    response_schema = _closed_host_error_diagnostics(
        ["Invalid schema for response_format output-contract-canary"]
    )
    indexed_tool_schema = _closed_host_error_diagnostics(
        ["tools[0] has invalid maximum length"]
    )
    unrelated_context = _closed_host_error_diagnostics(
        ["invalid request schema; API response 400"]
    )

    assert response_schema["categories"] == ["response_schema_error"]
    assert indexed_tool_schema["categories"] == ["tool_contract_error"]
    assert "response_schema_error" not in unrelated_context["categories"]


def test_codex_output_schemas_omit_unsupported_array_constraints() -> None:
    serialized = json.dumps(
        {"submission": _submission_schema(), "result": _result_schema()},
        sort_keys=True,
    )

    assert '"minItems"' not in serialized
    assert '"maxItems"' not in serialized
    assert '"uniqueItems"' not in serialized


def test_host_failure_diagnostics_do_not_combine_unrelated_messages() -> None:
    diagnostics = _closed_host_error_diagnostics(
        [
            "request queued",
            "response cached",
            "unrelated error",
            "tool completed",
            "schema documentation is invalid",
            "Formula ts_mean(close, 400) hypothesis 500",
        ]
    )

    assert "api_request_error" not in diagnostics["categories"]
    assert "tool_contract_error" not in diagnostics["categories"]
    assert diagnostics["safe_status_codes"] == []


def test_host_failure_diagnostics_accept_json_surrogates() -> None:
    event = json.loads(
        '{"type":"error","message":"MCP handshake timeout \\ud800"}'
    )

    summary = _event_summary([event])

    assert summary["host_errors"]["count"] == 1
    assert summary["host_errors"]["total_bytes"] == len(
        _diagnostic_bytes("MCP handshake timeout \ud800")
    )
    assert summary["host_errors"]["categories"] == ["handshake_error", "timeout"]
    assert len(summary["host_errors"]["message_sha256"]) == 1


def test_post_phase_contract_failure_keeps_safe_mcp_ledger(tmp_path: Path) -> None:
    phase = _CodexPhase(
        events=[],
        calls=[
            _call(
                "get_research_run",
                {"run_id": "private-run-canary"},
                {"status": "queued", "retry_after_seconds": 2},
                1,
            )
        ],
        final_output={},
        stderr="",
        operational_traces=(),
    )
    evidence_path = tmp_path / "post-phase-failure.json"

    _write_failure_evidence(
        evidence_path,
        safe_base={"acceptance": "real_codex_stdio", "status": "running"},
        error=AssertionError("trajectory failed for private-run-canary"),
        first=phase,
        second=None,
    )

    persisted = json.loads(evidence_path.read_text())
    assert persisted["failure"]["mcp_ledger"] == [
        {
            "argument_fields": ["run_id"],
            "diagnostic_codes": [],
            "result_fields": ["retry_after_seconds", "status"],
            "status": "queued",
            "tool": "get_research_run",
        }
    ]
    assert "private-run-canary" not in evidence_path.read_text()


def test_mcp_secret_source_is_private_and_removed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="cleanup-canary"):
        with _mcp_launch_configuration(
            workspace=tmp_path,
            executable=Path("/bin/echo"),
            environment={"THESISTRACE_SECRET": "secret-canary"},
        ) as (_, arguments, operational_path):
            launcher_path, environment_path, _, configured_operational_path = map(
                Path, arguments
            )
            assert launcher_path.stat().st_mode & 0o777 == 0o700
            assert environment_path.stat().st_mode & 0o777 == 0o600
            assert configured_operational_path == operational_path
            assert operational_path.stat().st_mode & 0o777 == 0o600
            assert json.loads(environment_path.read_text()) == {
                "THESISTRACE_SECRET": "secret-canary"
            }
            raise RuntimeError("cleanup-canary")

    assert not list(tmp_path.glob(".thesistrace-mcp-*"))


def test_operational_trace_reader_accepts_only_completed_tool_events(
    tmp_path: Path,
) -> None:
    operational_path = tmp_path / "operational.jsonl"
    operational_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "component": "research_agent_mcp",
                        "event": "mcp_tool_call_completed",
                        "trace_id": "trace_0123456789abcdef0123456789abcdef",
                        "tool_name": "get_research_context",
                    }
                ),
                json.dumps(
                    {
                        "component": "research_agent_mcp",
                        "event": "mcp_startup_failed",
                        "trace_id": "trace_ffffffffffffffffffffffffffffffff",
                    }
                ),
            )
        )
        + "\n"
    )

    assert _read_operational_traces(operational_path) == (
        _OperationalTrace(
            tool="get_research_context",
            trace_id="trace_0123456789abcdef0123456789abcdef",
        ),
    )


def test_mcp_launcher_captures_private_operational_trace(tmp_path: Path) -> None:
    executable = tmp_path / "fake-mcp"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "print(json.dumps({\n"
        "    'component': 'research_agent_mcp',\n"
        "    'event': 'mcp_tool_call_completed',\n"
        "    'trace_id': 'trace_0123456789abcdef0123456789abcdef',\n"
        "    'tool_name': 'get_research_context',\n"
        "}), file=sys.stderr)\n"
    )
    executable.chmod(0o755)

    with _mcp_launch_configuration(
        workspace=tmp_path,
        executable=executable,
        environment={"THESISTRACE_SECRET": "secret-canary"},
    ) as (command, arguments, operational_path):
        completed = subprocess.run(
            [command, *arguments],
            check=True,
            capture_output=True,
            timeout=5,
        )

        assert completed.stderr == b""
        assert _read_operational_traces(operational_path) == (
            _OperationalTrace(
                tool="get_research_context",
                trace_id="trace_0123456789abcdef0123456789abcdef",
            ),
        )

    assert not list(tmp_path.glob(".thesistrace-mcp-*"))


def test_operational_trace_reader_rejects_duplicate_or_unbounded_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operational_path = tmp_path / "operational.jsonl"
    event = json.dumps(
        {
            "component": "research_agent_mcp",
            "event": "mcp_tool_call_completed",
            "trace_id": "trace_0123456789abcdef0123456789abcdef",
            "tool_name": "get_research_context",
        }
    )
    operational_path.write_text(f"{event}\n{event}\n")
    with pytest.raises(AssertionError, match="must be unique"):
        _read_operational_traces(operational_path)

    monkeypatch.setattr(sys.modules[__name__], "MAX_MCP_OPERATIONAL_BYTES", 8)
    with pytest.raises(AssertionError, match="byte limit"):
        _read_operational_traces(operational_path)


def test_operational_trace_sequence_rejects_balanced_tool_mismatch() -> None:
    calls = [
        _call("get_research_context", {}, {"folders": []}, 1),
        _call(
            "get_alpha_catalog",
            {"identifiers": ["close"]},
            {"fields": []},
            2,
        ),
    ]
    traces = (
        _OperationalTrace(
            tool="get_research_context",
            trace_id="trace_0123456789abcdef0123456789abcdef",
        ),
        _OperationalTrace(
            tool="get_research_context",
            trace_id="trace_ffffffffffffffffffffffffffffffff",
        ),
    )

    with pytest.raises(AssertionError, match="must match"):
        _assert_operational_traces_match_calls(traces, calls)


@pytest.mark.parametrize("trace_error_type", (AssertionError, OSError))
def test_operational_trace_failure_does_not_mask_process_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trace_error_type: type[Exception],
) -> None:
    codex = tmp_path / "codex"
    codex.write_text("#!/bin/sh\nexit 7\n")
    codex.chmod(0o755)

    def reject_trace(_path: Path) -> tuple[_OperationalTrace, ...]:
        raise trace_error_type("malformed-operational-canary")

    monkeypatch.setattr(sys.modules[__name__], "_read_operational_traces", reject_trace)

    with pytest.raises(_CodexPhaseFailure) as raised:
        _run_codex_phase(
            codex=str(codex),
            mcp_environment=_test_mcp_environment(tmp_path),
            workspace=tmp_path / "workspace",
            schema={"type": "object"},
            prompt="test",
        )

    assert raised.value.diagnostics["phase_failure"] == (
        "nonzero_exit_or_missing_result"
    )
    assert raised.value.diagnostics["operational_trace_status"] == "invalid"
    assert not list((tmp_path / "workspace").glob(".thesistrace-mcp-*"))


@pytest.mark.parametrize("trace_error_type", (AssertionError, OSError))
def test_operational_trace_failure_is_closed_after_successful_host_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trace_error_type: type[Exception],
) -> None:
    codex = tmp_path / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "result_path = pathlib.Path(\n"
        "    sys.argv[sys.argv.index('--output-last-message') + 1]\n"
        ")\n"
        "result_path.write_text('{}')\n"
    )
    codex.chmod(0o755)

    def reject_trace(_path: Path) -> tuple[_OperationalTrace, ...]:
        raise trace_error_type("malformed-operational-canary")

    monkeypatch.setattr(sys.modules[__name__], "_read_operational_traces", reject_trace)

    with pytest.raises(_CodexPhaseFailure) as raised:
        _run_codex_phase(
            codex=str(codex),
            mcp_environment=_test_mcp_environment(tmp_path),
            workspace=tmp_path / "workspace",
            schema={"type": "object"},
            prompt="test",
        )

    assert raised.value.diagnostics["phase_failure"] == "operational_trace_contract"
    assert raised.value.diagnostics["operational_trace_status"] == "invalid"
    assert not list((tmp_path / "workspace").glob(".thesistrace-mcp-*"))


def test_mcp_secret_source_cleans_up_when_initialization_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_fdopen = os.fdopen
    fdopen_count = 0
    failed_descriptor: int | None = None

    def fail_second_fdopen(fd: int, *args: object, **kwargs: object) -> object:
        nonlocal failed_descriptor, fdopen_count
        fdopen_count += 1
        if fdopen_count == 2:
            failed_descriptor = fd
            raise OSError("write-canary")
        return original_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", fail_second_fdopen)

    with pytest.raises(OSError, match="write-canary"):
        with _mcp_launch_configuration(
            workspace=tmp_path,
            executable=Path("/bin/echo"),
            environment={"THESISTRACE_SECRET": "secret-canary"},
        ):
            pytest.fail("initialization unexpectedly completed")

    assert not list(tmp_path.glob(".thesistrace-mcp-*"))
    assert failed_descriptor is not None
    with pytest.raises(OSError):
        os.fstat(failed_descriptor)


def test_codex_host_environment_excludes_product_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THESISTRACE_DATABASE_URL", "private-database-canary")
    monkeypatch.setenv("THESISTRACE_S3_SECRET_ACCESS_KEY", "private-s3-canary")

    environment = _codex_host_environment(
        codex="/opt/codex/bin/codex",
        mcp_executable=Path("/opt/thesistrace/bin/thesistrace-research-agent-mcp"),
    )

    assert not any(name.startswith("THESISTRACE_") for name in environment)
    assert "private-database-canary" not in json.dumps(environment)
    assert "private-s3-canary" not in json.dumps(environment)


def test_codex_process_group_cleanup_is_bounded() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )

    _terminate_process_group(process)

    assert process.poll() is not None


@pytest.mark.parametrize("stream", ("stdout", "stderr"))
def test_codex_phase_rejects_unbounded_host_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stream: str,
) -> None:
    codex = tmp_path / "codex"
    if stream == "stdout":
        monkeypatch.setattr(sys.modules[__name__], "MAX_CODEX_EVENT_BYTES", 64)
        payload = "print('x' * 256, flush=True)"
    else:
        monkeypatch.setattr(sys.modules[__name__], "MAX_CODEX_STDERR_BYTES", 64)
        payload = "print('x' * 256, file=sys.stderr, flush=True)"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "import time\n"
        f"{payload}\n"
        "time.sleep(60)\n"
    )
    codex.chmod(0o755)

    started = time.monotonic()
    with pytest.raises(_CodexPhaseFailure) as raised:
        _run_codex_phase(
            codex=str(codex),
            mcp_environment=_test_mcp_environment(tmp_path),
            workspace=tmp_path / "workspace",
            schema={"type": "object"},
            prompt="test",
        )

    assert time.monotonic() - started < 5
    assert raised.value.diagnostics["phase_failure"] == "host_output_contract"
    assert "stderr" in raised.value.diagnostics
    assert "mcp_ledger" in raised.value.diagnostics


def test_codex_phase_rejects_oversized_structured_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "MAX_CODEX_RESULT_BYTES", 64)
    codex = tmp_path / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "result_path = pathlib.Path(\n"
        "    sys.argv[sys.argv.index('--output-last-message') + 1]\n"
        ")\n"
        "result_path.write_bytes(b'x' * 256)\n"
    )
    codex.chmod(0o755)

    with pytest.raises(_CodexPhaseFailure) as raised:
        _run_codex_phase(
            codex=str(codex),
            mcp_environment=_test_mcp_environment(tmp_path),
            workspace=tmp_path / "workspace",
            schema={"type": "object"},
            prompt="test",
        )

    assert raised.value.diagnostics["phase_failure"] == "oversized_structured_output"


def test_codex_phase_cleans_up_when_event_callback_fails(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    configuration_confirmed = tmp_path / "configuration-confirmed"
    event = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "thesistrace",
            "tool": "get_research_run",
            "status": "completed",
            "arguments": {"run_id": "run_test"},
            "result": {
                "content": [],
                "structured_content": {"status": "queued"},
            },
        },
    }
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import pathlib\n"
        "import sys\n"
        "import time\n"
        "assert not any(key.startswith('THESISTRACE_') for key in os.environ)\n"
        "assert sys.argv.index('--ask-for-approval') < sys.argv.index('exec')\n"
        "assert sys.argv[sys.argv.index('--ask-for-approval') + 1] == 'never'\n"
        f"features = {CODEX_FEATURES_DISABLED!r}\n"
        "for feature in features:\n"
        "    pair_found = any(\n"
        "        left == '--disable' and right == feature\n"
        "        for left, right in zip(sys.argv, sys.argv[1:])\n"
        "    )\n"
        "    assert pair_found\n"
        "joined = ' '.join(sys.argv)\n"
        "assert 'postgresql://acceptance-secret-canary' not in joined\n"
        "assert 'private-s3-access-canary' not in joined\n"
        "assert 'private-s3-secret-canary' not in joined\n"
        "args_config = next(\n"
        "    arg for arg in sys.argv\n"
        "    if arg.startswith('mcp_servers.thesistrace.args=')\n"
        ")\n"
        "mcp_args = json.loads(args_config.split('=', 1)[1])\n"
        "environment_path = pathlib.Path(mcp_args[1])\n"
        "assert environment_path.stat().st_mode & 0o777 == 0o600\n"
        "environment = json.loads(environment_path.read_text())\n"
        "assert environment['THESISTRACE_DATABASE_URL'] == "
        "'postgresql://acceptance-secret-canary'\n"
        "assert environment['THESISTRACE_S3_ACCESS_KEY_ID'] == "
        "'private-s3-access-canary'\n"
        "assert environment['THESISTRACE_S3_SECRET_ACCESS_KEY'] == "
        "'private-s3-secret-canary'\n"
        f"pathlib.Path({str(configuration_confirmed)!r}).write_text('ok')\n"
        f"print(json.dumps({event!r}), flush=True)\n"
        "time.sleep(60)\n"
    )
    codex.chmod(0o755)

    def fail_callback() -> None:
        raise RuntimeError("callback-canary")

    started = time.monotonic()
    with pytest.raises(_CodexPhaseFailure):
        _run_codex_phase(
            codex=str(codex),
            mcp_environment=_test_mcp_environment(tmp_path),
            workspace=tmp_path / "workspace",
            schema={"type": "object"},
            prompt="test",
            on_completed_poll=fail_callback,
        )

    assert time.monotonic() - started < 5
    assert configuration_confirmed.read_text() == "ok"
    assert not list((tmp_path / "workspace").glob(".thesistrace-mcp-*"))


def _test_mcp_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "THESISTRACE_DATABASE_URL": "postgresql://acceptance-secret-canary",
        "THESISTRACE_S3_ENDPOINT_URL": "http://127.0.0.1:1",
        "THESISTRACE_S3_ACCESS_KEY_ID": "private-s3-access-canary",
        "THESISTRACE_S3_SECRET_ACCESS_KEY": "private-s3-secret-canary",
        "THESISTRACE_S3_BUCKET": "test",
        "THESISTRACE_S3_REGION": "test",
        "THESISTRACE_DATA_MOUNT": str(tmp_path / "data"),
        "THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY": str(tmp_path / "attempts"),
    }
