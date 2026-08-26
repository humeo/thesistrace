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
    ResearchAgentToolError,
)
from thesistrace.research_agent.registry import (
    ResearchAgentCapabilityRegistry,
)

type ResearchAgentRegistryFactory = Callable[
    [ServerRequestContext[object]],
    ResearchAgentCapabilityRegistry,
]
type ResearchAgentTransport = Literal["stdio", "streamable_http"]


def create_research_agent_mcp_server(
    registry_factory: ResearchAgentRegistryFactory,
    *,
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int],
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
        registry = registry_factory(context)
        invocation = await anyio.to_thread.run_sync(
            lambda: registry.invoke(
                params.name,
                params.arguments or {},
                trace_id=trace_id,
            )
        )
        await checkpoint_if_cancelled()
        if invocation.error is not None:
            return _failure_result(
                registry,
                error=invocation.error,
                event_sink=event_sink,
                exception=invocation.exception,
                monotonic_ns=monotonic_ns,
                params=params,
                started=started,
                trace_id=trace_id,
                transport=transport,
            )
        assert invocation.result is not None
        result = CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=invocation.result.model_dump_json(),
                )
            ],
            structured_content=invocation.result.model_dump(mode="json"),
        )
        _emit_completion(
            event_sink,
            duration_ms=(monotonic_ns() - started) // 1_000_000,
            outcome="succeeded",
            registry=registry,
            response=result,
            tool_name=params.name,
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
    registry: ResearchAgentCapabilityRegistry,
    *,
    error: ResearchAgentToolError,
    event_sink: OperationalEventWriter,
    monotonic_ns: Callable[[], int],
    params: CallToolRequestParams,
    started: int,
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
        registry=registry,
        response=result,
        tool_name=params.name,
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
    outcome: Literal["succeeded", "failed"],
    registry: ResearchAgentCapabilityRegistry,
    response: CallToolResult,
    tool_name: str,
    trace_id: str,
    transport: ResearchAgentTransport,
    exception: Exception | None = None,
    failure_code: str | None = None,
) -> None:
    context: dict[str, object] = {
        "duration_ms": duration_ms,
        "outcome": outcome,
        "response_bytes": len(response.model_dump_json(by_alias=True, exclude_none=True).encode()),
        "subject": registry.authority.subject,
        "tool_name": tool_name,
        "trace_id": trace_id,
        "transport": transport,
    }
    if failure_code is not None:
        context["failure_code"] = failure_code
    if exception is not None:
        context.update(sanitized_exception_context(exception))
    try:
        event_sink(
            OperationalEvent(
                level="INFO" if outcome == "succeeded" else "ERROR",
                component="research_agent_mcp",
                event="mcp_tool_call_completed",
                context=context,
            )
        )
    except Exception:
        pass
