from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import count
from threading import Event

import anyio
import pytest
from jsonschema import validate
from mcp.client import Client
from mcp.types import ListToolsResult, TextContent
from mcp_types.methods import serialize_server_result
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from pydantic import ValidationError

from thesistrace.alpha_language import AlphaAuthoringCatalog, FormulaDiagnostics, alpha_language
from thesistrace.data.models import DataOverview, DatasetCoverage
from thesistrace.operational_events import OperationalEvent
from thesistrace.research_agent import (
    ResearchAgentAuthority,
    ResearchAgentCapabilityRegistry,
    ResearchAgentModules,
    ResearchAgentScope,
    create_research_agent_mcp_server,
    local_operator_authority,
)
from thesistrace.research_agent.registry import (
    AlphaAuthoringLanguage,
    ResearchAgentForbidden,
)
from thesistrace.research_authoring import ResearchAuthoringService
from thesistrace.research_folder.models import ResearchFolderList, ResearchFolderSummary


class _DataOverviewReader:
    def overview(self) -> DataOverview:
        return DataOverview(
            market_coverage=DatasetCoverage(
                start=date(2024, 1, 2),
                end=date(2024, 1, 31),
            ),
            financial_coverage=None,
            industry_coverage=None,
            data_through_session=date(2024, 1, 31),
            last_market_refresh_at=datetime(2024, 2, 1, tzinfo=UTC),
            last_financial_refresh_at=None,
            last_industry_refresh_at=None,
            industry_refresh_status=None,
            industry_refresh_failure_code=None,
            market_research_readiness=True,
            financial_research_readiness="ready",
            industry_research_readiness=False,
        )


class _ResearchFolderReader:
    def list(self) -> ResearchFolderList:
        return ResearchFolderList(
            items=[
                ResearchFolderSummary(
                    id="folder_default",
                    name="Research",
                    is_default=True,
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ]
        )


class _BlockingDataOverviewReader(_DataOverviewReader):
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.finished = Event()
        self.released_by_event_loop = False

    def overview(self) -> DataOverview:
        try:
            self.started.set()
            self.released_by_event_loop = self.release.wait(timeout=1)
            return super().overview()
        finally:
            self.finished.set()


class _ExplodingAlphaLanguage:
    def catalog(
        self,
        *,
        financial_authoring_ready: bool = True,
    ) -> AlphaAuthoringCatalog:
        del financial_authoring_ready
        raise RuntimeError("private-formula-canary")

    def diagnose(self, source: str) -> FormulaDiagnostics:
        del source
        raise RuntimeError("private-formula-canary")


def _registry(
    authority: ResearchAgentAuthority | None = None,
    *,
    allowed_tools: frozenset[str] | None = None,
    data_overview: _DataOverviewReader | None = None,
    selected_alpha_language: AlphaAuthoringLanguage = alpha_language,
) -> ResearchAgentCapabilityRegistry:
    return ResearchAgentCapabilityRegistry(
        authority=authority or local_operator_authority(),
        modules=ResearchAgentModules(
            data_overview=data_overview or _DataOverviewReader(),
            research_folders=_ResearchFolderReader(),
            alpha_language=selected_alpha_language,
            research_authoring=ResearchAuthoringService(),
        ),
        **({} if allowed_tools is None else {"allowed_tools": allowed_tools}),
    )


def test_local_operator_has_only_safe_default_scopes() -> None:
    authority = local_operator_authority()

    assert authority.subject == "local_operator"
    assert authority.scopes == {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
    assert ResearchAgentScope.RESEARCH_CANCEL not in authority.scopes
    assert ResearchAgentScope.TRACKING_STOP not in authority.scopes


def test_registry_filters_discovery_and_rechecks_scope_at_invocation() -> None:
    denied = _registry(ResearchAgentAuthority(subject="reader", scopes=frozenset()))

    assert denied.accessible_capabilities() == ()
    with pytest.raises(ResearchAgentForbidden, match="research:read"):
        denied.get_research_context()


def test_registry_composes_context_without_generation_or_folder_mutation() -> None:
    first = _registry().get_research_context().model_dump(mode="json")
    second = _registry().get_research_context().model_dump(mode="json")

    assert first == second
    assert first["folders"]["items"][0]["id"] == "folder_default"
    assert first["authoring_constraints"]["holdings_count"] == {
        "minimum": 1,
        "maximum": 100,
    }
    assert first["authoring_constraints"]["rebalance_every_sessions"] == {
        "minimum": 1,
        "maximum": 20,
    }
    assert first["authoring_constraints"]["batch_items"] == {
        "minimum": 1,
        "maximum": 20,
    }
    serialized = str(first).lower()
    assert "generation" not in serialized
    assert "create_folder" not in serialized
    assert "rename_folder" not in serialized
    assert "delete_folder" not in serialized


def test_registry_catalog_filter_is_bounded_sorted_and_reports_unknowns() -> None:
    catalog = _registry().get_alpha_catalog(identifiers=["ts_mean", "missing_identifier", "close"])

    assert [item.identifier for item in catalog.fields] == ["close"]
    assert [item.identifier for item in catalog.builtins] == ["ts_mean"]
    assert catalog.unknown_identifiers == ["missing_identifier"]
    with pytest.raises(ValidationError):
        _registry().get_alpha_catalog(identifiers=["close"] * 51)


def test_registry_formula_diagnostics_are_structured_and_source_ranged() -> None:
    valid = _registry().diagnose_alpha_formula("close")
    invalid = _registry().diagnose_alpha_formula("unknown_alpha + close")

    assert valid.model_dump(mode="json") == {"valid": True, "diagnostics": []}
    assert invalid.valid is False
    assert invalid.diagnostics[0].code == "UNKNOWN_IDENTIFIER"
    assert invalid.diagnostics[0].range.start.offset == 0
    assert invalid.diagnostics[0].range.end.offset == len("unknown_alpha")


def test_registry_intersects_deployment_allowlist_and_rechecks_it_on_invocation() -> None:
    registry = _registry(allowed_tools=frozenset({"get_research_context"}))

    assert [capability.name for capability in registry.accessible_capabilities()] == [
        "get_research_context"
    ]
    denied = registry.invoke(
        "get_alpha_catalog",
        {},
        trace_id="trace_allowlist",
    )

    assert denied.error is not None
    assert denied.error.code == "FORBIDDEN"


def test_in_memory_protocol_exposes_exact_read_only_tool_contract() -> None:
    anyio.run(_exercise_in_memory_protocol)


def test_in_memory_protocol_sanitizes_unexpected_tool_failures() -> None:
    anyio.run(_exercise_sanitized_failure)


def test_in_memory_protocol_rechecks_request_authority_after_discovery() -> None:
    anyio.run(_exercise_stale_discovery_authority)


def test_http_protocol_pseudonymizes_oauth_subject_in_operational_events() -> None:
    anyio.run(_exercise_oauth_subject_event)


def test_in_memory_protocol_keeps_event_loop_responsive_during_core_read() -> None:
    anyio.run(_exercise_non_blocking_core_read)


def test_in_memory_protocol_waits_for_cancelled_core_read_without_success_event() -> None:
    anyio.run(_exercise_cancelled_core_read)


async def _exercise_in_memory_protocol() -> None:
    events: list[OperationalEvent] = []
    async with Client(_server(_registry(), events=events)) as client:
        discovered = await client.list_tools()
        tools = {tool.name: tool for tool in discovered.tools}

        assert set(tools) == {
            "get_research_context",
            "get_alpha_catalog",
            "diagnose_alpha_formula",
        }
        assert client.server_capabilities is not None
        assert client.server_capabilities.prompts is None
        assert client.server_capabilities.resources is None
        assert client.server_capabilities.completions is None
        assert client.server_capabilities.tasks is None
        for tool in tools.values():
            assert tool.input_schema["additionalProperties"] is False
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            assert len(tool.output_schema["anyOf"]) == 2
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
            assert tool.annotations.idempotent_hint is True
            assert tool.annotations.open_world_hint is False
        assert tools["get_research_context"].input_schema["properties"] == {}
        assert (
            tools["get_alpha_catalog"].input_schema["properties"]["identifiers"]["anyOf"][0][
                "maxItems"
            ]
            == 50
        )
        assert (
            tools["diagnose_alpha_formula"].input_schema["properties"]["source"]["maxLength"]
            == 4096
        )
        serialize_server_result(
            "tools/list",
            LATEST_HANDSHAKE_VERSION,
            ListToolsResult(tools=list(tools.values())).model_dump(
                by_alias=True,
                mode="json",
                exclude_none=True,
            ),
        )

        catalog = await client.call_tool(
            "get_alpha_catalog",
            {"identifiers": ["ts_mean", "unknown_identifier", "close"]},
        )
        assert catalog.is_error is False
        validate(catalog.structured_content, tools["get_alpha_catalog"].output_schema)
        assert catalog.structured_content["unknown_identifiers"] == ["unknown_identifier"]

        invalid = await client.call_tool(
            "diagnose_alpha_formula",
            {"source": "missing_alpha + close"},
        )
        assert invalid.is_error is False
        validate(
            invalid.structured_content,
            tools["diagnose_alpha_formula"].output_schema,
        )
        assert invalid.structured_content["valid"] is False

        malformed = await client.call_tool(
            "get_alpha_catalog",
            {"identifiers": ["close"] * 51},
        )
        assert malformed.is_error is True
        validate(
            malformed.structured_content,
            tools["get_alpha_catalog"].output_schema,
        )
        extra = await client.call_tool(
            "get_research_context",
            {"generation_id": "must-not-be-accepted"},
        )
        assert extra.is_error is True
        validate(
            extra.structured_content,
            tools["get_research_context"].output_schema,
        )

    assert [event.context["outcome"] for event in events] == [
        "succeeded",
        "succeeded",
        "failed",
        "failed",
    ]
    assert events[2].context["failure_code"] == "INVALID_INPUT"
    assert events[3].context["failure_code"] == "INVALID_INPUT"


async def _exercise_sanitized_failure() -> None:
    registry = _registry(selected_alpha_language=_ExplodingAlphaLanguage())
    events: list[OperationalEvent] = []
    async with Client(_server(registry, events=events)) as client:
        result = await client.call_tool("get_alpha_catalog", {})

    assert result.is_error is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Tool execution failed"
    assert "private-formula-canary" not in result.content[0].text
    assert result.structured_content == {
        "code": "INTERNAL",
        "message": "Tool execution failed",
        "retryable": False,
        "trace_id": "trace_test_0",
        "retry_after_seconds": None,
    }
    assert events[0].context["failure_code"] == "INTERNAL"
    assert events[0].context["trace_id"] == "trace_test_0"
    assert "private-formula-canary" not in str(events[0].context)


async def _exercise_stale_discovery_authority() -> None:
    current = {"registry": _registry()}
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: current["registry"],
        event_sink=lambda _event: None,
        monotonic_ns=lambda: 0,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="stdio",
    )
    async with Client(server) as client:
        discovered = await client.list_tools()
        assert "get_research_context" in {tool.name for tool in discovered.tools}

        current["registry"] = _registry(
            ResearchAgentAuthority(subject="reader", scopes=frozenset())
        )
        denied = await client.call_tool("get_research_context", {})

    assert denied.is_error is True
    assert denied.structured_content["code"] == "FORBIDDEN"


async def _exercise_oauth_subject_event() -> None:
    raw_subject = f"auth0|{'a' * 194}"
    events: list[OperationalEvent] = []
    registry = _registry(
        ResearchAgentAuthority(
            subject=raw_subject,
            scopes=frozenset({ResearchAgentScope.RESEARCH_READ}),
        )
    )
    trace_ids = count()
    server = create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=events.append,
        monotonic_ns=lambda: 0,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="streamable_http",
    )

    async with Client(server) as client:
        first = await client.call_tool("get_research_context", {})
        second = await client.call_tool("get_research_context", {})

    assert first.is_error is False
    assert second.is_error is False
    assert len(events) == 2
    event_subjects = [event.context["subject"] for event in events]
    assert event_subjects[0] == event_subjects[1]
    assert isinstance(event_subjects[0], str)
    assert event_subjects[0].startswith("oauth_")
    assert len(event_subjects[0]) == 38
    assert raw_subject not in str(events)


async def _exercise_non_blocking_core_read() -> None:
    reader = _BlockingDataOverviewReader()
    results = []
    async with Client(_server(_registry(data_overview=reader), events=[])) as client:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_collect_context_result, client, results)
            with anyio.fail_after(2):
                while not reader.started.is_set():
                    await anyio.sleep(0)
            reader.release.set()

    assert reader.released_by_event_loop is True
    assert len(results) == 1
    assert results[0].is_error is False


async def _exercise_cancelled_core_read() -> None:
    reader = _BlockingDataOverviewReader()
    events: list[OperationalEvent] = []
    scopes: list[anyio.CancelScope] = []
    async with Client(_server(_registry(data_overview=reader), events=events)) as client:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_call_context_until_cancelled, client, scopes)
            with anyio.fail_after(2):
                while not reader.started.is_set() or not scopes:
                    await anyio.sleep(0)
            scopes[0].cancel()
            await anyio.sleep(0)
            assert reader.finished.is_set() is False
            assert not any(event.context["outcome"] == "succeeded" for event in events)
            reader.release.set()

    assert reader.finished.is_set() is True
    assert not any(event.context["outcome"] == "succeeded" for event in events)


async def _collect_context_result(client: Client, results: list) -> None:
    results.append(await client.call_tool("get_research_context", {}))


async def _call_context_until_cancelled(
    client: Client,
    scopes: list[anyio.CancelScope],
) -> None:
    with anyio.CancelScope() as scope:
        scopes.append(scope)
        await client.call_tool("get_research_context", {})


def _server(
    registry: ResearchAgentCapabilityRegistry,
    *,
    events: list[OperationalEvent],
):
    trace_ids = count()
    return create_research_agent_mcp_server(
        lambda _context: registry,
        event_sink=events.append,
        monotonic_ns=lambda: 0,
        trace_id_factory=lambda: f"trace_test_{next(trace_ids)}",
        transport="stdio",
    )
