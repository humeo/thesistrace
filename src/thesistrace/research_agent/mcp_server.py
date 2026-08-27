from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import anyio
from anyio.lowlevel import checkpoint_if_cancelled
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from thesistrace.operational_events import (
    OperationalEvent,
    OperationalEventWriter,
    sanitized_exception_context,
)
from thesistrace.research_agent.models import (
    ResearchAgentErrorCode,
    ResearchAgentToolError,
    ResearchAgentToolErrorContext,
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
RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES = 64 * 1024


class ResearchAgentWireResponseTooLarge(RuntimeError):
    pass


def create_research_agent_mcp_server(
    registry_factory: ResearchAgentRegistryFactory,
    *,
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int],
    subject_factory: ResearchAgentSubjectFactory,
    trace_id_factory: Callable[[], str],
    transport: ResearchAgentTransport,
) -> Server[object]:
    async def list_tools(
        context: ServerRequestContext[object],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        registry = registry_factory(context)
        return ListToolsResult(
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

    async def call_tool(
        context: ServerRequestContext[object],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        trace_id = trace_id_factory()
        started = monotonic_ns()
        registry: ResearchAgentCapabilityRegistry | None = None
        subject = "unavailable"
        try:
            subject = subject_factory(context)
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
                error=ResearchAgentToolError(
                    code=ResearchAgentErrorCode.INTERNAL,
                    message="Tool execution failed",
                    retryable=False,
                    trace_id=trace_id,
                    context=_safe_call_context(params),
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
        result = CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Structured result is available.",
                )
            ],
            structured_content=invocation.result.model_dump(mode="json"),
        )
        wire_bytes = len(result.model_dump_json(by_alias=True, exclude_none=True).encode())
        if wire_bytes > RESEARCH_AGENT_MAX_WIRE_RESPONSE_BYTES:
            return _failure_result(
                error=ResearchAgentToolError(
                    code=ResearchAgentErrorCode.INTERNAL,
                    message="Tool execution failed",
                    retryable=False,
                    trace_id=trace_id,
                    context=_safe_call_context(params),
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
            outcome="succeeded",
            call_context=_safe_call_context(params, response=result),
            response=result,
            subject=subject,
            trace_id=trace_id,
            transport=transport,
        )
        return result

    return Server(
        name="ThesisTrace Research Agent",
        version="0.1.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


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
    return CallToolResult(
        content=[TextContent(type="text", text=error.message)],
        structured_content=error.model_dump(mode="json"),
        is_error=True,
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
