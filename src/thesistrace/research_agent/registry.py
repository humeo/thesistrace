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
    CancelResearchRunInput,
    DiagnoseAlphaFormulaInput,
    FormulaSource,
    GetAlphaCatalogInput,
    GetResearchContextInput,
    GetResearchRunInput,
    ListResearchRunsInput,
    ResearchAgentAuthority,
    ResearchAgentErrorCode,
    ResearchAgentScope,
    ResearchAgentToolError,
    ResearchContext,
    SubmitResearchRunAccepted,
    SubmitResearchRunOutcome,
    SubmitResearchRunRejected,
)
from thesistrace.research_authoring.models import ResearchAuthoringConstraints
from thesistrace.research_folder.models import ResearchFolderList
from thesistrace.research_run import (
    ResearchRunAdmissionAccepted,
    ResearchRunAdmissionCommand,
    ResearchRunAdmissionConflict,
    ResearchRunAdmissionOutcome,
    ResearchRunCancelCommand,
    ResearchRunCancelIdempotencyConflict,
    ResearchRunCancelOutcome,
    ResearchRunCancelStateConflict,
    ResearchRunInvalidCursor,
    ResearchRunList,
    ResearchRunPollingDetail,
    ResearchRunResultSectionIncompatible,
    ResearchRunResultSectionInput,
    ResearchRunResultSectionResponse,
    ResearchRunResultUnavailable,
    ResearchRunTemporarilyUnavailable,
)
from thesistrace.research_run.models import ResearchKind


class DataOverviewReader(Protocol):
    def overview(self) -> DataOverview: ...


class ResearchFolderReader(Protocol):
    def list(self) -> ResearchFolderList: ...


class AlphaAuthoringLanguage(Protocol):
    def catalog(self, *, financial_authoring_ready: bool = True) -> AlphaAuthoringCatalog: ...

    def diagnose(self, source: str) -> FormulaDiagnostics: ...


class ResearchAuthoringReader(Protocol):
    def constraints(self) -> ResearchAuthoringConstraints: ...


class ResearchRunReader(Protocol):
    def list(
        self,
        *,
        folder_id: str | None = None,
        research_kind: ResearchKind | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ResearchRunList: ...

    def get_polling_detail(self, run_id: str) -> ResearchRunPollingDetail | None: ...

    def cancel(
        self,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunCancelOutcome | None: ...

    def get_result_section(
        self,
        query: ResearchRunResultSectionInput,
    ) -> ResearchRunResultSectionResponse | None: ...

    def admit_with_outcome(
        self,
        command: ResearchRunAdmissionCommand,
    ) -> ResearchRunAdmissionOutcome: ...


@dataclass(frozen=True)
class ResearchAgentModules:
    data_overview: DataOverviewReader
    research_folders: ResearchFolderReader
    alpha_language: AlphaAuthoringLanguage
    research_authoring: ResearchAuthoringReader
    research_runs: ResearchRunReader


@dataclass(frozen=True)
class ResearchAgentCapability:
    name: str
    description: str
    required_scope: ResearchAgentScope
    input_model: object
    output_model: object
    annotations: ToolAnnotations
    handler: Callable[..., BaseModel]

    def input_schema(self) -> dict[str, object]:
        schema = TypeAdapter(self.input_model).json_schema()
        schema["type"] = "object"
        return schema

    def output_schema(self) -> dict[str, object]:
        schema = TypeAdapter(self.output_model | ResearchAgentToolError).json_schema()  # type: ignore[operator]
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


class ResearchAgentExpectedFailure(RuntimeError):
    def __init__(
        self,
        code: ResearchAgentErrorCode,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


READ_ONLY_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
EFFECTFUL_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
DESTRUCTIVE_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)

RESEARCH_AGENT_TOOL_NAMES = frozenset(
    {
        "get_research_context",
        "get_alpha_catalog",
        "diagnose_alpha_formula",
        "list_research_runs",
        "get_research_run",
        "get_research_run_result",
        "cancel_research_run",
        "submit_research_run",
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
            ResearchAgentCapability(
                name="list_research_runs",
                description=(
                    "List durable ResearchRuns with stable pagination; requires research:read."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=ListResearchRunsInput,
                output_model=ResearchRunList,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.list_research_runs,
            ),
            ResearchAgentCapability(
                name="get_research_run",
                description=(
                    "Poll one durable ResearchRun without embedding its Result; requires "
                    "research:read and may recommend a retry delay while work is active."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=GetResearchRunInput,
                output_model=ResearchRunPollingDetail,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_research_run,
            ),
            ResearchAgentCapability(
                name="get_research_run_result",
                description=(
                    "Read one bounded semantic Result section from a succeeded ResearchRun; "
                    "collection sections use stable pagination and require research:read."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=ResearchRunResultSectionInput,
                output_model=ResearchRunResultSectionResponse,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_research_run_result,
            ),
            ResearchAgentCapability(
                name="cancel_research_run",
                description=(
                    "Cancel one queued or running ordinary ResearchRun; requires "
                    "research:cancel, irreversibly prevents a Result, is idempotent by "
                    "request_id, and when status is cancelling requires calling "
                    "get_research_run after retry_after_seconds until terminal cancelled."
                ),
                required_scope=ResearchAgentScope.RESEARCH_CANCEL,
                input_model=CancelResearchRunInput,
                output_model=ResearchRunCancelOutcome,
                annotations=DESTRUCTIVE_TOOL_ANNOTATIONS,
                handler=self.cancel_research_run,
            ),
            ResearchAgentCapability(
                name="submit_research_run",
                description=(
                    "Submit a fully specified Factor Evaluation or Strategy Backtest; requires "
                    "research:execute, is non-destructive, and is idempotent by request_id."
                ),
                required_scope=ResearchAgentScope.RESEARCH_EXECUTE,
                input_model=ResearchRunAdmissionCommand,
                output_model=SubmitResearchRunOutcome,
                annotations=EFFECTFUL_TOOL_ANNOTATIONS,
                handler=self.submit_research_run,
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
            validated = TypeAdapter(capability.input_model).validate_python(arguments)
        except ValidationError:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INVALID_INPUT,
                    trace_id=trace_id,
                )
            )
        try:
            if not isinstance(validated, BaseModel):
                raise TypeError("Research Agent input contract must produce a model")
            result = capability.handler(**validated.model_dump())
            validated_result = TypeAdapter(capability.output_model).validate_python(result)
            if not isinstance(validated_result, BaseModel):
                raise TypeError("Research Agent output contract must produce a model")
            return ResearchAgentInvocation(result=validated_result)
        except ResearchAgentExpectedFailure as error:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    error.code,
                    trace_id=trace_id,
                    retryable=error.retryable,
                    retry_after_seconds=error.retry_after_seconds,
                )
            )
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
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> ResearchAgentToolError:
        messages = {
            ResearchAgentErrorCode.INVALID_INPUT: "Tool input is invalid",
            ResearchAgentErrorCode.FORBIDDEN: "Tool authority is insufficient",
            ResearchAgentErrorCode.NOT_FOUND: "Requested resource was not found",
            ResearchAgentErrorCode.STATE_CONFLICT: "Resource state does not allow this operation",
            ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT: "Request identifier conflicts",
            ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE: "Tool is temporarily unavailable",
            ResearchAgentErrorCode.INTERNAL: "Tool execution failed",
        }
        message = messages.get(code)
        if message is None:
            raise ValueError(f"unsupported Research Agent error mapping: {code.value}")
        return ResearchAgentToolError(
            code=code,
            message=message,
            retryable=retryable,
            trace_id=trace_id,
            retry_after_seconds=retry_after_seconds,
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

    def list_research_runs(
        self,
        folder_id: str | None = None,
        research_kind: ResearchKind | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ResearchRunList:
        self._require(ResearchAgentScope.RESEARCH_READ)
        try:
            return self._modules.research_runs.list(
                folder_id=folder_id,
                research_kind=research_kind,
                cursor=cursor,
                limit=limit,
            )
        except ResearchRunInvalidCursor as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.INVALID_INPUT) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error

    def get_research_run(self, run_id: str) -> ResearchRunPollingDetail:
        self._require(ResearchAgentScope.RESEARCH_READ)
        try:
            detail = self._modules.research_runs.get_polling_detail(run_id)
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if detail is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return detail

    def get_research_run_result(self, **query_fields: object) -> BaseModel:
        self._require(ResearchAgentScope.RESEARCH_READ)
        query = TypeAdapter(ResearchRunResultSectionInput).validate_python(query_fields)
        try:
            result = self._modules.research_runs.get_result_section(query)
        except ResearchRunInvalidCursor as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.INVALID_INPUT) from error
        except (
            ResearchRunResultSectionIncompatible,
            ResearchRunResultUnavailable,
        ) as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if result is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        if not isinstance(result, BaseModel):
            raise TypeError("ResearchRun Result module returned an invalid section")
        return result

    def cancel_research_run(
        self,
        run_id: str,
        request_id: str,
    ) -> ResearchRunCancelOutcome:
        self._require(ResearchAgentScope.RESEARCH_CANCEL)
        try:
            outcome = self._modules.research_runs.cancel(
                run_id,
                ResearchRunCancelCommand(request_id=request_id),
            )
        except ResearchRunCancelIdempotencyConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except ResearchRunCancelStateConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.STATE_CONFLICT
            ) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return outcome

    def submit_research_run(self, **command_fields: object) -> BaseModel:
        self._require(ResearchAgentScope.RESEARCH_EXECUTE)
        command = TypeAdapter(ResearchRunAdmissionCommand).validate_python(command_fields)
        try:
            outcome = self._modules.research_runs.admit_with_outcome(command)
        except ResearchRunAdmissionConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if isinstance(outcome, ResearchRunAdmissionAccepted):
            return SubmitResearchRunAccepted(
                run_id=outcome.run.id,
                status=outcome.run.status,
                replayed=outcome.replayed,
                retry_after_seconds=outcome.retry_after_seconds,
            )
        return SubmitResearchRunRejected(
            issues=outcome.issues,
            replayed=outcome.replayed,
        )

    def _require(self, scope: ResearchAgentScope) -> None:
        if not self._authority.permits(scope):
            raise ResearchAgentForbidden(
                f"{self._authority.subject} lacks required scope {scope.value}"
            )


def local_operator_authority(
    *,
    enable_research_cancel: bool = False,
) -> ResearchAgentAuthority:
    scopes = {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
    if enable_research_cancel:
        scopes.add(ResearchAgentScope.RESEARCH_CANCEL)
    return ResearchAgentAuthority(
        subject="local_operator",
        scopes=frozenset(scopes),
    )


def _temporarily_unavailable() -> ResearchAgentExpectedFailure:
    return ResearchAgentExpectedFailure(
        ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE,
        retryable=True,
        retry_after_seconds=2,
    )
