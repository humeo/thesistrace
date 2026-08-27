from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from io import StringIO
from types import SimpleNamespace
from uuid import UUID

from fastapi import Body, FastAPI, HTTPException
from fastapi.testclient import TestClient

from thesistrace.entrypoints.http import create_app
from thesistrace.operational_events import (
    OperationalEvent,
    OperationalEventSink,
)

_FIXED_OBSERVED_AT = datetime(2026, 8, 24, tzinfo=UTC)


def test_operational_event_sink_emits_one_allowlisted_json_line() -> None:
    output = StringIO()
    sink = _sink(output)

    sink(
        OperationalEvent(
            level="ERROR",
            component="core_api",
            event="http_request_failed",
            context={
                "http_request_id": "request-1",
                "method": "GET",
                "route": "/api/research-runs/{run_id}",
                "status_code": 500,
                "exception_type": "RuntimeError",
                "stack_frames": [
                    {
                        "module": "/private/top-secret/service.py",
                        "function": "handle",
                        "line": 17,
                        "source": "password = 'canary-secret'",
                    }
                ],
                "password": "canary-secret",
                "arbitrary_object": object(),
            },
        )
    )

    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event == {
        "component": "core_api",
        "event": "http_request_failed",
        "exception_type": "RuntimeError",
        "http_request_id": "request-1",
        "level": "ERROR",
        "method": "GET",
        "route": "/api/research-runs/{run_id}",
        "stack_frames": [
            {
                "function": "handle",
                "line": 17,
                "module": "service",
            }
        ],
        "status_code": 500,
        "timestamp": "2026-08-24T00:00:00.000Z",
    }
    assert "canary-secret" not in lines[0]
    assert "source" not in lines[0]
    assert "password" not in lines[0]
    assert "arbitrary_object" not in lines[0]


def test_operational_event_sink_disables_debug_by_default() -> None:
    output = StringIO()
    sink = _sink(output)

    sink(
        OperationalEvent(
            level="DEBUG",
            component="core_api",
            event="debug_probe",
        )
    )

    assert output.getvalue() == ""


def test_operational_event_rejects_sensitive_values_in_allowlisted_fields() -> None:
    output = StringIO()
    sink = _sink(output)

    sink(
        OperationalEvent(
            level="ERROR",
            component="core_api",
            event="sensitive_value_probe",
            context={
                "run_id": "postgresql://user:canary-password@host/database",
                "phase": "ts_mean(close, 20)",
                "status": "Hypothesis: canary alpha should rise",
                "retry_at": "/private/canary-secret/config",
                "route": "s3://private-bucket/canary-object",
                "http_request_id": "Bearer canary-authorization-token",
                "failure_code": "password=canary-secret",
            },
        )
    )

    assert json.loads(output.getvalue()) == {
        "component": "core_api",
        "event": "sensitive_value_probe",
        "level": "ERROR",
        "timestamp": "2026-08-24T00:00:00.000Z",
    }
    assert "canary" not in output.getvalue()


def test_operational_event_accepts_canonical_data_refresh_operation_ids() -> None:
    output = StringIO()
    sink = _sink(output)

    for operation_id in (
        "bootstrap:0123456789abcdef0123456789abcdef",
        "refresh:0123456789abcdef0123456789abcdef",
        "financial-refresh:0123456789abcdef0123456789abcdef",
    ):
        sink(
            OperationalEvent(
                level="INFO",
                component="data_operator",
                event="data_refresh_started",
                context={"operation_id": operation_id},
            )
        )

    assert [event["operation_id"] for event in _events(output)] == [
        "bootstrap:0123456789abcdef0123456789abcdef",
        "refresh:0123456789abcdef0123456789abcdef",
        "financial-refresh:0123456789abcdef0123456789abcdef",
    ]


def test_operational_event_keeps_safe_mcp_completion_context() -> None:
    output = StringIO()
    sink = _sink(output)

    sink(
        OperationalEvent(
            level="ERROR",
            component="research_agent_mcp",
            event="mcp_tool_call_completed",
            context={
                "subject": "local_operator",
                "transport": "stdio",
                "tool_name": "diagnose_alpha_formula",
                "outcome": "failed",
                "failure_code": "INTERNAL",
                "trace_id": "trace_0123456789abcdef0123456789abcdef",
                "run_id": "run_0123456789abcdef",
                "request_id": "request_0123456789abcdef",
                "duration_ms": 2,
                "response_bytes": 128,
                "formula": "canary-secret-formula",
            },
        )
    )

    assert json.loads(output.getvalue()) == {
        "component": "research_agent_mcp",
        "duration_ms": 2,
        "event": "mcp_tool_call_completed",
        "failure_code": "INTERNAL",
        "level": "ERROR",
        "outcome": "failed",
        "response_bytes": 128,
        "run_id": "run_0123456789abcdef",
        "request_id": "request_0123456789abcdef",
        "subject": "local_operator",
        "timestamp": "2026-08-24T00:00:00.000Z",
        "tool_name": "diagnose_alpha_formula",
        "trace_id": "trace_0123456789abcdef0123456789abcdef",
        "transport": "stdio",
    }
    assert "canary-secret-formula" not in output.getvalue()


def test_operational_event_keeps_safe_batch_qualification_evidence_only() -> None:
    output = StringIO()
    sink = _sink(output)

    sink(
        OperationalEvent(
            level="INFO",
            component="batch_research_worker",
            event="research_batch_execution_item_succeeded",
            context={
                "batch_id": "batch_0123456789abcdef",
                "attempt_id": "batch_attempt_0123456789abcdef",
                "worker_role": "batch-research",
                "slot": 1,
                "slot_count": 1,
                "item_ordinal": 2,
                "child_peak_rss_bytes": 1024,
                "acknowledged": True,
                "alpha_factor_task_started": False,
                "alpha_factor_task_completed": True,
                "strategy_task_started": True,
                "strategy_task_completed": True,
                "data_io": {"bytes_read": 2048, "rows_scanned": 16},
                "child_calculation_phase_seconds": {
                    "factor": 0.25,
                    "strategy": 0.5,
                },
                "item_key": "private-user-item",
                "message": "canary-secret",
            },
        )
    )

    event = json.loads(output.getvalue())
    assert event == {
        "acknowledged": True,
        "alpha_factor_task_completed": True,
        "alpha_factor_task_started": False,
        "attempt_id": "batch_attempt_0123456789abcdef",
        "batch_id": "batch_0123456789abcdef",
        "child_calculation_phase_seconds": {"factor": 0.25, "strategy": 0.5},
        "child_peak_rss_bytes": 1024,
        "component": "batch_research_worker",
        "data_io": {"bytes_read": 2048, "rows_scanned": 16},
        "event": "research_batch_execution_item_succeeded",
        "item_ordinal": 2,
        "level": "INFO",
        "slot": 1,
        "slot_count": 1,
        "strategy_task_completed": True,
        "strategy_task_started": True,
        "timestamp": "2026-08-24T00:00:00.000Z",
        "worker_role": "batch-research",
    }
    assert "private-user-item" not in output.getvalue()
    assert "canary-secret" not in output.getvalue()


def test_operational_event_keeps_safe_long_research_qualification_evidence() -> None:
    output = StringIO()
    sink = _sink(output)

    sink(
        OperationalEvent(
            level="INFO",
            component="research_worker",
            event="research_execution_chunk_received",
            context={
                "run_id": "run_0123456789abcdef",
                "attempt_id": "attempt_0123456789abcdef",
                "worker_role": "research",
                "exit_code": -15,
                "child_chunk_seconds": 1.5,
                "child_data_read_seconds": 0.25,
                "child_calculation_seconds": 1.0,
                "supervisor_commit_seconds": 0.125,
                "strategy_continuation_present": True,
                "strategy_observation_count": 32,
                "formula": "rank(close)",
            },
        )
    )

    assert json.loads(output.getvalue()) == {
        "attempt_id": "attempt_0123456789abcdef",
        "child_calculation_seconds": 1.0,
        "child_chunk_seconds": 1.5,
        "child_data_read_seconds": 0.25,
        "component": "research_worker",
        "event": "research_execution_chunk_received",
        "exit_code": -15,
        "level": "INFO",
        "run_id": "run_0123456789abcdef",
        "strategy_continuation_present": True,
        "strategy_observation_count": 32,
        "supervisor_commit_seconds": 0.125,
        "timestamp": "2026-08-24T00:00:00.000Z",
        "worker_role": "research",
    }
    assert "rank(close)" not in output.getvalue()


def test_http_default_sink_emits_json_to_process_stderr() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                (
                    "from fastapi.testclient import TestClient",
                    "from thesistrace.entrypoints.http import create_app",
                    "app = create_app()",
                    "app.add_api_route('/test/default-sink', lambda: {'status': 'ok'})",
                    "response = TestClient(app).get('/test/default-sink')",
                    "assert response.status_code == 200",
                    "print(response.headers['X-Request-ID'])",
                )
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    request_id = completed.stdout.strip()
    event_lines = [line for line in completed.stderr.splitlines() if line.startswith("{")]
    assert len(event_lines) == 1
    event = json.loads(event_lines[0])
    assert event["component"] == "core_api"
    assert event["event"] == "http_request_completed"
    assert event["http_request_id"] == request_id
    assert event["method"] == "GET"
    assert event["route"] == "/test/default-sink"
    assert event["status_code"] == 200
    assert event["duration_ms"] >= 0
    assert event["timestamp"].endswith("Z")


def test_http_request_returns_id_and_normalized_completion_event() -> None:
    output = StringIO()
    app = _test_app(
        output,
        request_ids=["00000000-0000-4000-8000-000000000001"],
        ticks=[1_000_000, 3_000_000],
    )

    @app.get("/test/items/{item_id}")
    def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    client = TestClient(app)
    response = client.get(
        "/test/items/private-value?token=canary-secret",
        headers={
            "Authorization": "Bearer canary-authorization",
            "Cookie": "session=canary-cookie",
        },
    )

    assert response.status_code == 200
    UUID(response.headers["X-Request-ID"])
    events = _events(output)
    assert events == [
        {
            "component": "core_api",
            "duration_ms": 2,
            "event": "http_request_completed",
            "http_request_id": response.headers["X-Request-ID"],
            "level": "INFO",
            "method": "GET",
            "route": "/test/items/{item_id}",
            "status_code": 200,
            "timestamp": "2026-08-24T00:00:00.000Z",
        }
    ]
    assert events[0]["duration_ms"] >= 0
    assert "private-value" not in output.getvalue()
    assert "canary-secret" not in output.getvalue()
    assert "canary-authorization" not in output.getvalue()
    assert "canary-cookie" not in output.getvalue()


def test_http_expected_client_errors_emit_completion_without_stack() -> None:
    output = StringIO()
    app = _test_app(
        output,
        request_ids=[
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000003",
            "00000000-0000-4000-8000-000000000004",
        ],
        ticks=[0, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000],
    )

    @app.post("/test/values")
    def create_value(value: int = Body(embed=True)) -> dict[str, int]:
        return {"value": value}

    @app.post("/test/conflict")
    def create_conflict() -> None:
        raise HTTPException(status_code=409, detail="canary-conflict-detail")

    client = TestClient(app)
    invalid = client.post(
        "/test/values?token=canary-query",
        json={"value": "canary-body"},
    )
    conflict = client.post(
        "/test/conflict",
        headers={"Cookie": "session=canary-cookie"},
    )
    missing = client.get("/private-missing-path?secret=canary-query")

    assert invalid.status_code == 422
    assert conflict.status_code == 409
    assert missing.status_code == 404
    events = _events(output)
    assert [event["event"] for event in events] == [
        "http_request_completed",
        "http_request_completed",
        "http_request_completed",
    ]
    assert [event["status_code"] for event in events] == [422, 409, 404]
    assert [event["route"] for event in events] == [
        "/test/values",
        "/test/conflict",
        "unmatched",
    ]
    assert all(event["level"] == "INFO" for event in events)
    assert "stack_frames" not in output.getvalue()
    assert "canary-" not in output.getvalue()


def test_http_health_requests_emit_no_operational_event() -> None:
    output = StringIO()
    app = _test_app(output, request_ids=[], ticks=[])
    app.state.core_runtime = SimpleNamespace(
        readiness=SimpleNamespace(
            snapshot=lambda: {"status": "ready", "dependencies": {}}
        )
    )

    client = TestClient(app)

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert output.getvalue() == ""


def test_http_unexpected_failure_is_sanitized_once_and_returns_request_id() -> None:
    output = StringIO()
    serialized_sink = _sink(output)
    captured_events: list[OperationalEvent] = []

    def capture_and_serialize(event: OperationalEvent) -> None:
        captured_events.append(event)
        serialized_sink(event)

    ticks = iter([10_000_000, 13_000_000])
    app = create_app(
        event_sink=capture_and_serialize,
        http_request_id_factory=lambda: "00000000-0000-4000-8000-000000000005",
        monotonic_ns=ticks.__next__,
    )

    @app.get("/test/failure/{failure_id}")
    def fail_request(failure_id: str) -> None:
        raise RuntimeError(f"private failure {failure_id} canary-secret")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/test/failure/private-value?authorization=canary-query"
    )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    UUID(response.headers["X-Request-ID"])
    events = _events(output)
    assert [event["event"] for event in events] == [
        "http_request_failed",
        "http_request_completed",
    ]
    failure, completion = events
    assert failure["level"] == "ERROR"
    assert failure["exception_type"] == "RuntimeError"
    assert failure["route"] == "/test/failure/{failure_id}"
    assert failure["http_request_id"] == response.headers["X-Request-ID"]
    assert failure["stack_frames"]
    assert all(set(frame) == {"module", "function", "line"} for frame in failure["stack_frames"])
    assert all("/" not in frame["module"] for frame in failure["stack_frames"])
    assert captured_events[0].context["stack_frames"] == failure["stack_frames"]
    assert completion["level"] == "INFO"
    assert completion["status_code"] == 500
    assert completion["duration_ms"] == 3
    assert completion["http_request_id"] == response.headers["X-Request-ID"]
    assert "private-value" not in output.getvalue()
    assert "canary-" not in output.getvalue()


def _events(output: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.getvalue().splitlines()]


def _sink(output: StringIO) -> OperationalEventSink:
    return OperationalEventSink(output, clock=lambda: _FIXED_OBSERVED_AT)


def _test_app(
    output: StringIO,
    *,
    request_ids: Iterable[str],
    ticks: Iterable[int],
) -> FastAPI:
    request_id_iterator = iter(request_ids)
    tick_iterator = iter(ticks)
    return create_app(
        event_sink=_sink(output),
        http_request_id_factory=request_id_iterator.__next__,
        monotonic_ns=tick_iterator.__next__,
    )
