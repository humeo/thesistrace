from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import anyio
from anyio.lowlevel import checkpoint_if_cancelled
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from mcp_types import INVALID_PARAMS, JSONRPCResponse
from mcp_types.methods import serialize_server_result
from pydantic import BaseModel

from thesistrace.operational_events import (
    OperationalEvent,
    OperationalEventWriter,
    sanitized_exception_context,
)
from thesistrace.research_agent.models import (
    ResearchAgentErrorCode,
    ResearchAgentToolError,
    ResearchAgentToolErrorContext,
    SubmitResearchBatchRejected,
    SubmitResearchRunRejected,
)
from thesistrace.research_agent.registry import (
    RESEARCH_AGENT_TOOL_NAMES,
    ResearchAgentCapabilityRegistry,
)
from thesistrace.research_agent.safe_context import (
    digested_identifier,
    safe_tool_call_context,
)

type ResearchAgentRegistryFactory = Callable[
    [ServerRequestContext[object]],
    ResearchAgentCapabilityRegistry,
]
type ResearchAgentSubjectFactory = Callable[[ServerRequestContext[object]], str]
type ResearchAgentTransport = Literal["stdio", "streamable_http"]
# Twenty Framework items with four 64 KiB source programs each, including
# JSON's six-byte ASCII escaping, must fit the same contract accepted over HTTP.
RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES = 64 * 1024 * 1024
# Complete 4 MiB Framework pages plus both MCP representations and text escaping.
RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES = 16 * 1024 * 1024
RESEARCH_AGENT_RATE_WINDOW_SECONDS = 60
RESEARCH_AGENT_MAX_CALLS_PER_WINDOW = 120
RESEARCH_AGENT_MAX_CONCURRENT_CALLS = 4
RESEARCH_AGENT_TOOL_OUTCOME_META_KEY = "thesistrace/tool-outcome"
RESEARCH_AGENT_INSTRUCTIONS = (
    "ThesisTrace performs researcher-owned research and simulated Daily Tracking. "
    "For new research, use available get_research_context/get_alpha_catalog information, "
    "read get_authoring_reference for unfamiliar Formula syntax or Python SDK members, "
    "then diagnose_research_spec before submit_research_run or submit_research_batch. "
    "Use only tools exposed to this caller. Reuse request_id with identical arguments when "
    "retrying an uncertain submission; use a new request_id for changed research or a new action. "
    "Acceptance is not completion: follow next_tool and retry_after_seconds until terminal, "
    "then read only the Result sections needed. Tool errors and rejected submissions contain "
    "issues to correct; do not treat them as accepted work. Diagnostic valid=false means "
    "the diagnosis completed and found problems. Large Result sections return section=result_page. "
    "Continue the same result tool with section=result_page, query set to the original section "
    "arguments, and result_cursor=next_result_cursor. Concatenate json_fragment values in offset "
    "order, verify total_bytes/checksum_sha256, then parse JSON. If the cursor is invalid, restart "
    "the original query; never join different results. After reconstructing a collection page, "
    "its own next_cursor continues the collection. Refresh, retry, cancellation and stop require "
    "explicit user intent and the corresponding authority; reading never starts a rerun."
)


class ResearchAgentWireResponseTooLarge(RuntimeError):
    pass


@dataclass
class _PrincipalIngressState:
    window_started_ns: int
    calls: int = 0
    active: int = 0


class _ResearchAgentIngressGuard:
    def __init__(self, monotonic_ns: Callable[[], int]) -> None:
        self._monotonic_ns = monotonic_ns
        self._lock = anyio.Lock()
        self._principals: dict[str, _PrincipalIngressState] = {}

    async def acquire(self, subject: str) -> int | None:
        principal = digested_identifier("principal", subject)
        now = self._monotonic_ns()
        window_ns = RESEARCH_AGENT_RATE_WINDOW_SECONDS * 1_000_000_000
        async with self._lock:
            self._prune(now, window_ns)
            state = self._principals.get(principal)
            if state is None:
                state = _PrincipalIngressState(window_started_ns=now)
                self._principals[principal] = state
            elif now - state.window_started_ns >= window_ns:
                state.window_started_ns = now
                state.calls = 0
            if state.calls >= RESEARCH_AGENT_MAX_CALLS_PER_WINDOW:
                remaining_ns = max(1, window_ns - (now - state.window_started_ns))
                return min(
                    RESEARCH_AGENT_RATE_WINDOW_SECONDS,
                    max(1, (remaining_ns + 999_999_999) // 1_000_000_000),
                )
            state.calls += 1
            if state.active >= RESEARCH_AGENT_MAX_CONCURRENT_CALLS:
                return 1
            state.active += 1
        return None

    async def release(self, subject: str) -> None:
        principal = digested_identifier("principal", subject)
        async with self._lock:
            state = self._principals.get(principal)
            if state is None or state.active < 1:
                raise RuntimeError("Research Agent ingress release has no active call")
            state.active -= 1

    def _prune(self, now: int, window_ns: int) -> None:
        expired = [
            principal
            for principal, state in self._principals.items()
            if state.active == 0 and now - state.window_started_ns >= window_ns
        ]
        for principal in expired:
            del self._principals[principal]


def create_research_agent_mcp_server(
    registry_factory: ResearchAgentRegistryFactory,
    *,
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int],
    subject_factory: ResearchAgentSubjectFactory,
    trace_id_factory: Callable[[], str],
    transport: ResearchAgentTransport,
) -> Server[object]:
    ingress = _ResearchAgentIngressGuard(monotonic_ns)

    async def list_tools(
        context: ServerRequestContext[object],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        registry = registry_factory(context)
        result = ListToolsResult(
            tools=[
                Tool(
                    name=capability.name,
                    description=capability.description,
                    input_schema=capability.input_schema(),
                    output_schema=capability.output_schema(),
                    annotations=capability.annotations,
                )
                for capability in registry.accessible_capabilities()
            ]
        )
        if (
            _wire_response_bytes(context, method="tools/list", result=result)
            > RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES
        ):
            raise ResearchAgentWireResponseTooLarge(
                "Research Agent wire response exceeds its byte limit"
            )
        return result

    async def call_tool(
        context: ServerRequestContext[object],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        trace_id = trace_id_factory()
        started = monotonic_ns()
        subject = "unavailable"
        try:
            subject = subject_factory(context)
            if _wire_request_bytes(params) > RESEARCH_AGENT_MAX_WIRE_REQUEST_BYTES:
                return _failure_result(
                    error=_boundary_error(
                        ResearchAgentErrorCode.INVALID_INPUT,
                        params=params,
                        trace_id=trace_id,
                    ),
                    event_sink=event_sink,
                    monotonic_ns=monotonic_ns,
                    started=started,
                    subject=subject,
                    trace_id=trace_id,
                    transport=transport,
                )
            retry_after_seconds = await ingress.acquire(subject)
            if retry_after_seconds is not None:
                return _failure_result(
                    error=_boundary_error(
                        ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE,
                        params=params,
                        retry_after_seconds=retry_after_seconds,
                        trace_id=trace_id,
                    ),
                    event_sink=event_sink,
                    monotonic_ns=monotonic_ns,
                    started=started,
                    subject=subject,
                    trace_id=trace_id,
                    transport=transport,
                )
        except Exception as exception:
            return _failure_result(
                error=_boundary_error(
                    ResearchAgentErrorCode.INTERNAL,
                    params=params,
                    trace_id=trace_id,
                ),
                event_sink=event_sink,
                exception=exception,
                monotonic_ns=monotonic_ns,
                started=started,
                subject=subject,
                trace_id=trace_id,
                transport=transport,
            )
        try:
            if params.name not in RESEARCH_AGENT_TOOL_NAMES:
                _emit_completion(
                    event_sink,
                    duration_ms=(monotonic_ns() - started) // 1_000_000,
                    outcome="failed",
                    failure_code="UNKNOWN_TOOL",
                    call_context=_safe_call_context(params),
                    response=None,
                    subject=subject,
                    trace_id=trace_id,
                    transport=transport,
                )
                raise MCPError(INVALID_PARAMS, "Unknown tool")
            return await _invoke_admitted_tool(
                context,
                params,
                event_sink=event_sink,
                monotonic_ns=monotonic_ns,
                registry_factory=registry_factory,
                started=started,
                subject=subject,
                trace_id=trace_id,
                transport=transport,
            )
        finally:
            with anyio.CancelScope(shield=True):
                await ingress.release(subject)

    return Server(
        name="ThesisTrace Research Agent",
        version="0.1.0",
        instructions=RESEARCH_AGENT_INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def _invoke_admitted_tool(
    context: ServerRequestContext[object],
    params: CallToolRequestParams,
    *,
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int],
    registry_factory: ResearchAgentRegistryFactory,
    started: int,
    subject: str,
    trace_id: str,
    transport: ResearchAgentTransport,
) -> CallToolResult:
    try:
        registry = registry_factory(context)
        invocation = await anyio.to_thread.run_sync(
            lambda: registry.invoke(
                params.name,
                params.arguments or {},
                trace_id=trace_id,
            )
        )
        await checkpoint_if_cancelled()
    except anyio.get_cancelled_exc_class():
        _emit_completion(
            event_sink,
            duration_ms=(monotonic_ns() - started) // 1_000_000,
            outcome="cancelled",
            call_context=_safe_call_context(params),
            response=None,
            subject=subject,
            trace_id=trace_id,
            transport=transport,
        )
        raise
    except Exception as exception:
        return _failure_result(
            error=_boundary_error(
                ResearchAgentErrorCode.INTERNAL,
                params=params,
                trace_id=trace_id,
            ),
            event_sink=event_sink,
            exception=exception,
            monotonic_ns=monotonic_ns,
            started=started,
            subject=subject,
            trace_id=trace_id,
            transport=transport,
        )
    if invocation.error is not None:
        return _failure_result(
            error=invocation.error,
            event_sink=event_sink,
            exception=invocation.exception,
            monotonic_ns=monotonic_ns,
            started=started,
            subject=subject,
            trace_id=trace_id,
            transport=transport,
        )
    assert invocation.result is not None
    structured_result = invocation.result.model_dump(mode="json")
    rejected = isinstance(
        invocation.result, (SubmitResearchRunRejected, SubmitResearchBatchRejected),
    )
    outcome = "failed" if rejected else "succeeded"
    result = CallToolResult(
        content=[TextContent(type="text", text=_model_result_text(structured_result))],
        structured_content=structured_result,
        is_error=rejected,
        meta={RESEARCH_AGENT_TOOL_OUTCOME_META_KEY: outcome},
    )
    wire_bytes = _wire_response_bytes(context, method="tools/call", result=result)
    if wire_bytes > RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES:
        return _failure_result(
            error=_boundary_error(
                ResearchAgentErrorCode.INTERNAL,
                params=params,
                trace_id=trace_id,
            ),
            event_sink=event_sink,
            exception=ResearchAgentWireResponseTooLarge(
                "Research Agent wire response exceeds its byte limit"
            ),
            monotonic_ns=monotonic_ns,
            started=started,
            subject=subject,
            trace_id=trace_id,
            transport=transport,
        )
    _emit_completion(
        event_sink,
        duration_ms=(monotonic_ns() - started) // 1_000_000,
        outcome=outcome,
        failure_code=ResearchAgentErrorCode.INVALID_INPUT.value if rejected else None,
        call_context=_safe_call_context(params, response=result),
        response=result,
        subject=subject,
        trace_id=trace_id,
        transport=transport,
    )
    return result


def _boundary_error(
    code: ResearchAgentErrorCode,
    *,
    params: CallToolRequestParams,
    trace_id: str,
    retry_after_seconds: int | None = None,
) -> ResearchAgentToolError:
    messages = {
        ResearchAgentErrorCode.INVALID_INPUT: "Tool input is invalid",
        ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE: "Tool is temporarily unavailable",
        ResearchAgentErrorCode.INTERNAL: "Tool execution failed",
    }
    return ResearchAgentToolError(
        code=code,
        message=messages[code],
        retryable=code is ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE,
        retry_after_seconds=retry_after_seconds,
        trace_id=trace_id,
        context=_safe_call_context(params),
    )


def _wire_request_bytes(params: CallToolRequestParams) -> int:
    payload = {
        "jsonrpc": "2.0",
        "id": "request",
        "method": "tools/call",
        "params": {
            "name": params.name,
            "arguments": params.arguments or {},
        },
    }
    return len(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )


def _wire_response_bytes(
    context: ServerRequestContext[object],
    *,
    method: str,
    result: BaseModel,
) -> int:
    surface_result = serialize_server_result(
        method,
        context.protocol_version,
        result.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    response = JSONRPCResponse(
        jsonrpc="2.0",
        id=context.request_id if context.request_id is not None else "request",
        result=surface_result,
    )
    return len(response.model_dump_json(by_alias=True, exclude_none=True).encode())


def _failure_result(
    *,
    error: ResearchAgentToolError,
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int],
    started: int,
    subject: str,
    trace_id: str,
    transport: ResearchAgentTransport,
    exception: Exception | None = None,
) -> CallToolResult:
    result = _tool_error_result(error)
    _emit_completion(
        event_sink,
        duration_ms=(monotonic_ns() - started) // 1_000_000,
        exception=exception,
        failure_code=error.code.value,
        outcome="failed",
        call_context=error.context,
        response=result,
        subject=subject,
        trace_id=trace_id,
        transport=transport,
    )
    return result


def _tool_error_result(error: ResearchAgentToolError) -> CallToolResult:
    structured_error = error.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=_model_result_text(structured_error))],
        structured_content=structured_error,
        is_error=True,
        meta={RESEARCH_AGENT_TOOL_OUTCOME_META_KEY: "failed"},
    )


def _model_result_text(result: object) -> str:
    return json.dumps(
        result,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _emit_completion(
    event_sink: OperationalEventWriter,
    *,
    duration_ms: int,
    outcome: Literal["succeeded", "failed", "cancelled"],
    call_context: ResearchAgentToolErrorContext,
    response: CallToolResult | None,
    subject: str,
    trace_id: str,
    transport: ResearchAgentTransport,
    exception: Exception | None = None,
    failure_code: str | None = None,
) -> None:
    try:
        context: dict[str, object] = {
            "duration_ms": duration_ms,
            "outcome": outcome,
            "business_response_bytes": (
                0
                if response is None or response.structured_content is None
                else len(
                    json.dumps(
                        response.structured_content, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8", errors="surrogatepass")
                )
            ),
            "response_bytes": (
                0
                if response is None
                else len(
                    response.model_dump_json(by_alias=True, exclude_none=True).encode(
                        "utf-8",
                        errors="surrogatepass",
                    )
                )
            ),
            "subject": _operational_subject(subject, transport=transport),
            "trace_id": trace_id,
            "transport": transport,
        }
        context.update(call_context.model_dump(mode="json", exclude_none=True))
        if failure_code is not None:
            context["failure_code"] = failure_code
        if exception is not None:
            context.update(sanitized_exception_context(exception))
        level = "INFO"
        if failure_code == ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE.value:
            level = "WARNING"
        elif failure_code == ResearchAgentErrorCode.INTERNAL.value:
            level = "ERROR"
        event_sink(
            OperationalEvent(
                level=level,
                component="research_agent_mcp",
                event="mcp_tool_call_completed",
                context=context,
            )
        )
    except Exception:
        pass


def _operational_subject(
    subject: str,
    *,
    transport: ResearchAgentTransport,
) -> str:
    if transport == "stdio":
        if subject == "local_operator":
            return subject
        return digested_identifier("stdio", subject)
    return digested_identifier("oauth", subject)


def _safe_call_context(
    params: CallToolRequestParams,
    *,
    response: CallToolResult | None = None,
) -> ResearchAgentToolErrorContext:
    return safe_tool_call_context(
        params.name,
        params.arguments or {},
        known_tool_names=RESEARCH_AGENT_TOOL_NAMES,
        structured_response=(
            None if response is None else response.structured_content
        ),
    )
