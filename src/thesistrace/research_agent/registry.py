from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.types import ToolAnnotations
from pydantic import BaseModel, TypeAdapter, ValidationError

from thesistrace.alpha_language.models import AlphaAuthoringCatalog, FormulaDiagnostics
from thesistrace.data.models import DataOverview
from thesistrace.research_agent.models import (
    AlphaCatalogIdentifiers,
    AlphaCatalogView,
    DiagnoseAlphaFormulaInput,
    FormulaSource,
    GetAlphaCatalogInput,
    GetResearchContextInput,
    ResearchAgentAuthority,
    ResearchAgentErrorCode,
    ResearchAgentScope,
    ResearchAgentToolError,
    ResearchContext,
)
from thesistrace.research_authoring.models import ResearchAuthoringConstraints
from thesistrace.research_folder.models import ResearchFolderList


class DataOverviewReader(Protocol):
    def overview(self) -> DataOverview: ...


class ResearchFolderReader(Protocol):
    def list(self) -> ResearchFolderList: ...


class AlphaAuthoringLanguage(Protocol):
    def catalog(self, *, financial_authoring_ready: bool = True) -> AlphaAuthoringCatalog: ...

    def diagnose(self, source: str) -> FormulaDiagnostics: ...


class ResearchAuthoringReader(Protocol):
    def constraints(self) -> ResearchAuthoringConstraints: ...


@dataclass(frozen=True)
class ResearchAgentModules:
    data_overview: DataOverviewReader
    research_folders: ResearchFolderReader
    alpha_language: AlphaAuthoringLanguage
    research_authoring: ResearchAuthoringReader


@dataclass(frozen=True)
class ResearchAgentCapability:
    name: str
    description: str
    required_scope: ResearchAgentScope
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    annotations: ToolAnnotations
    handler: Callable[..., BaseModel]

    def input_schema(self) -> dict[str, object]:
        return self.input_model.model_json_schema()

    def output_schema(self) -> dict[str, object]:
        schema = TypeAdapter(self.output_model | ResearchAgentToolError).json_schema()
        schema["type"] = "object"
        return schema


@dataclass(frozen=True)
class ResearchAgentInvocation:
    result: BaseModel | None = None
    error: ResearchAgentToolError | None = None
    exception: Exception | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("Research Agent invocation must have one outcome")
        if self.exception is not None and self.error is None:
            raise ValueError("Research Agent exception requires an error outcome")


class ResearchAgentForbidden(PermissionError):
    pass


READ_ONLY_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

RESEARCH_AGENT_TOOL_NAMES = frozenset(
    {
        "get_research_context",
        "get_alpha_catalog",
        "diagnose_alpha_formula",
    }
)


class ResearchAgentCapabilityRegistry:
    """Request-local authority and the complete public Research Agent tool contract."""

    def __init__(
        self,
        *,
        authority: ResearchAgentAuthority,
        modules: ResearchAgentModules,
        allowed_tools: frozenset[str] = RESEARCH_AGENT_TOOL_NAMES,
    ) -> None:
        unknown_tools = allowed_tools - RESEARCH_AGENT_TOOL_NAMES
        if unknown_tools:
            raise ValueError(
                f"unknown Research Agent deployment tools: {', '.join(sorted(unknown_tools))}"
            )
        self._authority = authority
        self._modules = modules
        self._allowed_tools = allowed_tools
        self._capabilities = (
            ResearchAgentCapability(
                name="get_research_context",
                description=(
                    "Read the current Data Overview, Research Folders, and authoring constraints."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=GetResearchContextInput,
                output_model=ResearchContext,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_research_context,
            ),
            ResearchAgentCapability(
                name="get_alpha_catalog",
                description=(
                    "Read authorable Alpha fields and builtins, optionally filtered by identifier."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=GetAlphaCatalogInput,
                output_model=AlphaCatalogView,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_alpha_catalog,
            ),
            ResearchAgentCapability(
                name="diagnose_alpha_formula",
                description="Diagnose an Alpha Formula without creating a ResearchRun.",
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=DiagnoseAlphaFormulaInput,
                output_model=FormulaDiagnostics,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.diagnose_alpha_formula,
            ),
        )

    def accessible_capabilities(self) -> tuple[ResearchAgentCapability, ...]:
        return tuple(
            capability
            for capability in self._capabilities
            if capability.name in self._allowed_tools
            and self._authority.permits(capability.required_scope)
        )

    @property
    def authority(self) -> ResearchAgentAuthority:
        return self._authority

    def invoke(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        trace_id: str,
    ) -> ResearchAgentInvocation:
        capability: ResearchAgentCapability | None = None
        for capability in self._capabilities:
            if capability.name == name:
                break
        else:
            capability = None
        if capability is None:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INVALID_INPUT,
                    trace_id=trace_id,
                )
            )
        if capability.name not in self._allowed_tools:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.FORBIDDEN,
                    trace_id=trace_id,
                )
            )
        try:
            self._require(capability.required_scope)
        except ResearchAgentForbidden:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.FORBIDDEN,
                    trace_id=trace_id,
                )
            )
        try:
            validated = capability.input_model.model_validate(arguments)
        except ValidationError:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INVALID_INPUT,
                    trace_id=trace_id,
                )
            )
        try:
            result = capability.handler(**validated.model_dump())
            return ResearchAgentInvocation(result=capability.output_model.model_validate(result))
        except Exception as exception:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INTERNAL,
                    trace_id=trace_id,
                ),
                exception=exception,
            )

    def _tool_error(
        self,
        code: ResearchAgentErrorCode,
        *,
        trace_id: str,
    ) -> ResearchAgentToolError:
        messages = {
            ResearchAgentErrorCode.INVALID_INPUT: "Tool input is invalid",
            ResearchAgentErrorCode.FORBIDDEN: "Tool authority is insufficient",
            ResearchAgentErrorCode.INTERNAL: "Tool execution failed",
        }
        message = messages.get(code)
        if message is None:
            raise ValueError(f"unsupported Research Agent error mapping: {code.value}")
        return ResearchAgentToolError(
            code=code,
            message=message,
            retryable=False,
            trace_id=trace_id,
        )

    def get_research_context(self) -> ResearchContext:
        self._require(ResearchAgentScope.RESEARCH_READ)
        overview = self._modules.data_overview.overview()
        return ResearchContext(
            data_overview=overview,
            folders=self._modules.research_folders.list(),
            authoring_constraints=self._modules.research_authoring.constraints(),
        )

    def get_alpha_catalog(
        self,
        identifiers: AlphaCatalogIdentifiers | None = None,
    ) -> AlphaCatalogView:
        self._require(ResearchAgentScope.RESEARCH_READ)
        request = GetAlphaCatalogInput(identifiers=identifiers)
        overview = self._modules.data_overview.overview()
        catalog = self._modules.alpha_language.catalog(
            financial_authoring_ready=(overview.financial_research_readiness != "not_ready")
        )
        fields = sorted(catalog.fields, key=lambda item: item.identifier)
        builtins = sorted(catalog.builtins, key=lambda item: item.identifier)
        if request.identifiers is None:
            return AlphaCatalogView(
                fields=fields,
                builtins=builtins,
                unknown_identifiers=[],
            )

        requested = set(request.identifiers)
        known = {item.identifier for item in fields}
        known.update(item.identifier for item in builtins)
        return AlphaCatalogView(
            fields=[item for item in fields if item.identifier in requested],
            builtins=[item for item in builtins if item.identifier in requested],
            unknown_identifiers=sorted(requested - known),
        )

    def diagnose_alpha_formula(self, source: FormulaSource) -> FormulaDiagnostics:
        self._require(ResearchAgentScope.RESEARCH_READ)
        request = DiagnoseAlphaFormulaInput(source=source)
        return self._modules.alpha_language.diagnose(request.source)

    def _require(self, scope: ResearchAgentScope) -> None:
        if not self._authority.permits(scope):
            raise ResearchAgentForbidden(
                f"{self._authority.subject} lacks required scope {scope.value}"
            )


def local_operator_authority() -> ResearchAgentAuthority:
    return ResearchAgentAuthority(
        subject="local_operator",
        scopes=frozenset(
            {
                ResearchAgentScope.RESEARCH_READ,
                ResearchAgentScope.RESEARCH_EXECUTE,
                ResearchAgentScope.TRACKING_READ,
                ResearchAgentScope.TRACKING_EXECUTE,
            }
        ),
    )
