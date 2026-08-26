import logging
import os
from time import perf_counter_ns
from uuid import uuid4

import anyio
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from thesistrace.alpha_language import alpha_language
from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime
from thesistrace.operational_events import (
    OperationalEvent,
    emit_operational_event,
    sanitized_exception_context,
)
from thesistrace.research_agent import (
    ResearchAgentCapabilityRegistry,
    ResearchAgentModules,
    create_research_agent_mcp_server,
    local_operator_authority,
)

RESEARCH_CANCEL_ENABLE_ENVIRONMENT = "THESISTRACE_RESEARCH_AGENT_ENABLE_RESEARCH_CANCEL"
TRACKING_STOP_ENABLE_ENVIRONMENT = "THESISTRACE_RESEARCH_AGENT_ENABLE_TRACKING_STOP"


def main() -> None:
    logging.getLogger("psycopg.pool").disabled = True
    try:
        settings = CoreSettings.from_environment()
    except RuntimeError as error:
        _exit_with_failure("CORE_CONFIGURATION_MISSING", error)
    phase = "startup"
    try:
        with open_core_runtime(settings) as runtime:
            modules = ResearchAgentModules(
                data_overview=runtime.data_overview,
                research_folders=runtime.research_folders,
                alpha_language=alpha_language,
                research_authoring=runtime.research_authoring,
                research_runs=runtime.research_runs,
                research_batches=runtime.research_batches,
                daily_tracks=runtime.daily_tracks,
            )
            authority = local_operator_authority(
                enable_research_cancel=_research_cancel_is_enabled(),
                enable_tracking_stop=_tracking_stop_is_enabled(),
            )

            def registry_factory(
                _context: ServerRequestContext[object],
            ) -> ResearchAgentCapabilityRegistry:
                return ResearchAgentCapabilityRegistry(
                    authority=authority,
                    modules=modules,
                )

            phase = "process"
            anyio.run(
                _serve_stdio,
                create_research_agent_mcp_server(
                    registry_factory,
                    event_sink=emit_operational_event,
                    monotonic_ns=perf_counter_ns,
                    trace_id_factory=_new_trace_id,
                    transport="stdio",
                ),
            )
            phase = "shutdown"
    except Exception as error:
        failure_codes = {
            "startup": "CORE_STARTUP_FAILED",
            "process": "MCP_PROCESS_FAILED",
            "shutdown": "CORE_SHUTDOWN_FAILED",
        }
        _exit_with_failure(failure_codes[phase], error)


def _exit_with_failure(failure_code: str, error: Exception) -> None:
    events = {
        "CORE_CONFIGURATION_MISSING": "mcp_startup_failed",
        "CORE_STARTUP_FAILED": "mcp_startup_failed",
        "MCP_PROCESS_FAILED": "mcp_process_failed",
        "CORE_SHUTDOWN_FAILED": "mcp_shutdown_failed",
    }
    emit_operational_event(
        OperationalEvent(
            level="ERROR",
            component="research_agent_mcp",
            event=events[failure_code],
            context={
                "failure_code": failure_code,
                "outcome": "failed",
                "subject": "local_operator",
                "trace_id": _new_trace_id(),
                "transport": "stdio",
                **sanitized_exception_context(error),
            },
        )
    )
    raise SystemExit(2) from None


async def _serve_stdio(server: Server[object]) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _new_trace_id() -> str:
    return f"trace_{uuid4().hex}"


def _research_cancel_is_enabled() -> bool:
    return _dangerous_scope_is_enabled(RESEARCH_CANCEL_ENABLE_ENVIRONMENT)


def _tracking_stop_is_enabled() -> bool:
    return _dangerous_scope_is_enabled(TRACKING_STOP_ENABLE_ENVIRONMENT)


def _dangerous_scope_is_enabled(name: str) -> bool:
    value = os.environ.get(name)
    if value in {None, ""}:
        return False
    if value == "true":
        return True
    raise ValueError(f"{name} must be exactly true when enabled")


if __name__ == "__main__":
    main()
