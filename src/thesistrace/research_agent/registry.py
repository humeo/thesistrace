from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic import BaseModel, TypeAdapter, ValidationError

from thesistrace.alpha_language.models import AlphaAuthoringCatalog, FormulaDiagnostics
from thesistrace.daily_track import (
    DailyTrackInvalidCursor,
    DailyTrackList,
    DailyTrackPollingDetail,
    DailyTrackRefreshConflict,
    DailyTrackRefreshUnavailable,
    DailyTrackResultSectionInput,
    DailyTrackResultSectionResponse,
    DailyTrackResultUnavailable,
    DailyTrackRetryConflict,
    DailyTrackRetryUnavailable,
    DailyTrackStopConflict,
    DailyTrackStopUnavailable,
    DailyTrackTemporarilyUnavailable,
    RefreshDailyTrackCommand,
    RetryDailyTrackCommand,
    StopDailyTrackCommand,
)
from thesistrace.daily_track import (
    DailyTrackRefreshOutcome as DomainDailyTrackRefreshOutcome,
)
from thesistrace.daily_track import (
    DailyTrackRetryOutcome as DomainDailyTrackRetryOutcome,
)
from thesistrace.daily_track import (
    DailyTrackStopOutcome as DomainDailyTrackStopOutcome,
)
from thesistrace.data.models import DataOverview
from thesistrace.research_agent.models import (
    AlphaCatalogIdentifiers,
    AlphaCatalogView,
    CancelResearchBatchInput,
    CancelResearchBatchOutcome,
    CancelResearchRunInput,
    DiagnoseAlphaFormulaInput,
    FormulaSource,
    GetAlphaCatalogInput,
    GetDailyTrackInput,
    GetResearchBatchInput,
    GetResearchContextInput,
    GetResearchRunInput,
    ListDailyTracksInput,
    ListResearchBatchesInput,
    ListResearchRunsInput,
    RefreshDailyTrackInput,
    RefreshDailyTrackOutcome,
    ResearchAgentAuthority,
    ResearchAgentErrorCode,
    ResearchAgentScope,
    ResearchAgentToolError,
    ResearchContext,
    RetryDailyTrackInput,
    RetryDailyTrackOutcome,
    StartDailyTrackInput,
    StartDailyTrackOutcome,
    StopDailyTrackInput,
    StopDailyTrackOutcome,
    SubmitResearchBatchAccepted,
    SubmitResearchBatchOutcome,
    SubmitResearchBatchRejected,
    SubmitResearchRunAccepted,
    SubmitResearchRunOutcome,
    SubmitResearchRunRejected,
)
from thesistrace.research_agent.safe_context import safe_tool_call_context
from thesistrace.research_authoring.models import ResearchAuthoringConstraints
from thesistrace.research_batch import (
    ResearchBatchAdmissionAccepted,
    ResearchBatchAdmissionCommand,
    ResearchBatchAdmissionConflict,
    ResearchBatchAdmissionOutcome,
    ResearchBatchCancelCommand,
    ResearchBatchCancelIdempotencyConflict,
    ResearchBatchCancelStateConflict,
    ResearchBatchInvalidCursor,
    ResearchBatchList,
    ResearchBatchPollingDetail,
    ResearchBatchTemporarilyUnavailable,
    research_batch_polling_detail,
)
from thesistrace.research_batch import (
    ResearchBatchCancelOutcome as DomainResearchBatchCancelOutcome,
)
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
    ResearchRunStartTrackingConflict,
    ResearchRunStartTrackingOutcome,
    ResearchRunTemporarilyUnavailable,
    ResearchRunTrackingTemporarilyUnavailable,
    ResearchRunTrackingUnavailable,
    StartTrackingCommand,
)
from thesistrace.research_run.models import ResearchKind


class DataOverviewReader(Protocol):
    def overview(self) -> DataOverview: ...


class ResearchFolderReader(Protocol):
    def list(self, researcher_id: UUID) -> ResearchFolderList: ...


class AlphaAuthoringLanguage(Protocol):
    def catalog(self, *, financial_authoring_ready: bool = True) -> AlphaAuthoringCatalog: ...

    def diagnose(self, source: str) -> FormulaDiagnostics: ...


class ResearchAuthoringReader(Protocol):
    def constraints(self) -> ResearchAuthoringConstraints: ...


class ResearchRunReader(Protocol):
    def list(
        self,
        researcher_id: UUID,
        *,
        folder_id: str | None = None,
        research_kind: ResearchKind | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ResearchRunList: ...

    def get_polling_detail(
        self,
        researcher_id: UUID,
        run_id: str,
    ) -> ResearchRunPollingDetail | None: ...

    def cancel(
        self,
        researcher_id: UUID,
        run_id: str,
        command: ResearchRunCancelCommand,
    ) -> ResearchRunCancelOutcome | None: ...

    def get_result_section(
        self,
        researcher_id: UUID,
        query: ResearchRunResultSectionInput,
    ) -> ResearchRunResultSectionResponse | None: ...

    def admit_with_outcome(
        self,
        researcher_id: UUID,
        command: ResearchRunAdmissionCommand,
    ) -> ResearchRunAdmissionOutcome: ...

    def start_tracking_with_outcome(
        self,
        researcher_id: UUID,
        run_id: str,
        command: StartTrackingCommand,
    ) -> ResearchRunStartTrackingOutcome | None: ...


class ResearchBatchReader(Protocol):
    def list(
        self,
        researcher_id: UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> ResearchBatchList: ...

    def get_polling_detail(
        self,
        researcher_id: UUID,
        batch_id: str,
    ) -> ResearchBatchPollingDetail | None: ...

    def admit_with_outcome(
        self,
        researcher_id: UUID,
        command: ResearchBatchAdmissionCommand,
    ) -> ResearchBatchAdmissionOutcome: ...

    def cancel_with_outcome(
        self,
        researcher_id: UUID,
        batch_id: str,
        command: ResearchBatchCancelCommand,
    ) -> DomainResearchBatchCancelOutcome | None: ...


class DailyTrackReader(Protocol):
    def list(
        self,
        researcher_id: UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> DailyTrackList: ...

    def get_polling_detail(
        self,
        researcher_id: UUID,
        track_id: str,
    ) -> DailyTrackPollingDetail | None: ...

    def get_result_section(
        self,
        researcher_id: UUID,
        query: DailyTrackResultSectionInput,
    ) -> DailyTrackResultSectionResponse | None: ...

    def retry_with_outcome(
        self,
        researcher_id: UUID,
        track_id: str,
        command: RetryDailyTrackCommand,
    ) -> DomainDailyTrackRetryOutcome | None: ...

    def refresh_with_outcome(
        self,
        researcher_id: UUID,
        track_id: str,
        command: RefreshDailyTrackCommand,
    ) -> DomainDailyTrackRefreshOutcome | None: ...

    def stop_with_outcome(
        self,
        researcher_id: UUID,
        track_id: str,
        command: StopDailyTrackCommand,
    ) -> DomainDailyTrackStopOutcome | None: ...


@dataclass(frozen=True)
class ResearchAgentModules:
    data_overview: DataOverviewReader
    research_folders: ResearchFolderReader
    alpha_language: AlphaAuthoringLanguage
    research_authoring: ResearchAuthoringReader
    research_runs: ResearchRunReader
    research_batches: ResearchBatchReader
    daily_tracks: DailyTrackReader


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
        "list_research_batches",
        "get_research_batch",
        "submit_research_batch",
        "cancel_research_batch",
        "cancel_research_run",
        "submit_research_run",
        "list_daily_tracks",
        "get_daily_track",
        "get_daily_track_result",
        "start_daily_track",
        "refresh_daily_track",
        "retry_daily_track",
        "stop_daily_track",
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
                name="list_daily_tracks",
                description=(
                    "List durable DailyTracks newest first with stable opaque pagination; "
                    "requires tracking:read and returns compact summaries only."
                ),
                required_scope=ResearchAgentScope.TRACKING_READ,
                input_model=ListDailyTracksInput,
                output_model=DailyTrackList,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.list_daily_tracks,
            ),
            ResearchAgentCapability(
                name="get_daily_track",
                description=(
                    "Poll one durable DailyTrack lifecycle, progress, action eligibility, "
                    "timing, block reason, and available result sections; requires "
                    "tracking:read and embeds no observations, positions, or checkpoints."
                ),
                required_scope=ResearchAgentScope.TRACKING_READ,
                input_model=GetDailyTrackInput,
                output_model=DailyTrackPollingDetail,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_daily_track,
            ),
            ResearchAgentCapability(
                name="get_daily_track_result",
                description=(
                    "Read one bounded semantic DailyTrack Result section from its current "
                    "immutable checkpoint; observations and origin positions use stable "
                    "opaque pagination and require tracking:read."
                ),
                required_scope=ResearchAgentScope.TRACKING_READ,
                input_model=DailyTrackResultSectionInput,
                output_model=DailyTrackResultSectionResponse,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_daily_track_result,
            ),
            ResearchAgentCapability(
                name="start_daily_track",
                description=(
                    "Start one durable DailyTrack from a succeeded Strategy Backtest; "
                    "requires tracking:execute, is non-destructive and idempotent by "
                    "request_id, and continues after the MCP connection closes. Rejects "
                    "non-succeeded or non-Strategy origins, duplicate origins, and full "
                    "active capacity as state conflicts. After acceptance, poll "
                    "get_daily_track after retry_after_seconds."
                ),
                required_scope=ResearchAgentScope.TRACKING_EXECUTE,
                input_model=StartDailyTrackInput,
                output_model=StartDailyTrackOutcome,
                annotations=EFFECTFUL_TOOL_ANNOTATIONS,
                handler=self.start_daily_track,
            ),
            ResearchAgentCapability(
                name="refresh_daily_track",
                description=(
                    "Queue one explicit advance of an active, lagging, idle DailyTrack "
                    "to the latest available Dataset Head; requires tracking:execute, "
                    "is non-destructive and idempotent by request_id, and continues after "
                    "the MCP connection closes. A later Dataset Head requires another "
                    "Refresh. Poll get_daily_track after retry_after_seconds."
                ),
                required_scope=ResearchAgentScope.TRACKING_EXECUTE,
                input_model=RefreshDailyTrackInput,
                output_model=RefreshDailyTrackOutcome,
                annotations=EFFECTFUL_TOOL_ANNOTATIONS,
                handler=self.refresh_daily_track,
            ),
            ResearchAgentCapability(
                name="retry_daily_track",
                description=(
                    "Retry one blocked DailyTrack; requires tracking:execute, is "
                    "non-destructive and idempotent by request_id, and may remain blocked "
                    "when the frozen target still cannot fit. Poll get_daily_track after "
                    "retry_after_seconds when status becomes active."
                ),
                required_scope=ResearchAgentScope.TRACKING_EXECUTE,
                input_model=RetryDailyTrackInput,
                output_model=RetryDailyTrackOutcome,
                annotations=EFFECTFUL_TOOL_ANNOTATIONS,
                handler=self.retry_daily_track,
            ),
            ResearchAgentCapability(
                name="stop_daily_track",
                description=(
                    "Irreversibly stop one active or blocked DailyTrack; requires the "
                    "independent tracking:stop scope, is destructive and idempotent by "
                    "request_id, and does not accept a confirmation token. Poll "
                    "get_daily_track after retry_after_seconds while status is stopping."
                ),
                required_scope=ResearchAgentScope.TRACKING_STOP,
                input_model=StopDailyTrackInput,
                output_model=StopDailyTrackOutcome,
                annotations=DESTRUCTIVE_TOOL_ANNOTATIONS,
                handler=self.stop_daily_track,
            ),
            ResearchAgentCapability(
                name="list_research_batches",
                description=(
                    "List durable Research Batches newest first with opaque pagination; "
                    "requires research:read and returns no child Results."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=ListResearchBatchesInput,
                output_model=ResearchBatchList,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.list_research_batches,
            ),
            ResearchAgentCapability(
                name="get_research_batch",
                description=(
                    "Poll one durable Research Batch with aggregate progress and ordered "
                    "child run identifiers; requires research:read, embeds no Results, and "
                    "returns retry_after_seconds while work remains active."
                ),
                required_scope=ResearchAgentScope.RESEARCH_READ,
                input_model=GetResearchBatchInput,
                output_model=ResearchBatchPollingDetail,
                annotations=READ_ONLY_TOOL_ANNOTATIONS,
                handler=self.get_research_batch,
            ),
            ResearchAgentCapability(
                name="cancel_research_batch",
                description=(
                    "Cancel one queued or running Research Batch; requires research:cancel, "
                    "irreversibly cancels unfinished child work, is idempotent by request_id, "
                    "and when status is cancelling requires get_research_batch polling after "
                    "retry_after_seconds until terminal cancelled."
                ),
                required_scope=ResearchAgentScope.RESEARCH_CANCEL,
                input_model=CancelResearchBatchInput,
                output_model=CancelResearchBatchOutcome,
                annotations=DESTRUCTIVE_TOOL_ANNOTATIONS,
                handler=self.cancel_research_batch,
            ),
            ResearchAgentCapability(
                name="submit_research_batch",
                description=(
                    "Atomically submit a fully specified Factor Evaluation Batch or Strategy "
                    "Sweep with 1 to 20 caller-keyed items; requires research:execute, is "
                    "non-destructive, and is idempotent by request_id. Invalid research is a "
                    "successful structured rejected outcome; after acceptance, poll "
                    "get_research_batch using retry_after_seconds until terminal."
                ),
                required_scope=ResearchAgentScope.RESEARCH_EXECUTE,
                input_model=ResearchBatchAdmissionCommand,
                output_model=SubmitResearchBatchOutcome,
                annotations=EFFECTFUL_TOOL_ANNOTATIONS,
                handler=self.submit_research_batch,
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
                    "research:execute, is non-destructive, and is idempotent by request_id. "
                    "Invalid research is a successful structured rejected outcome; after "
                    "acceptance, poll get_research_run using retry_after_seconds until terminal."
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
                    arguments=arguments,
                    trace_id=trace_id,
                    tool_name=name,
                )
            )
        if capability.name not in self._allowed_tools:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.FORBIDDEN,
                    arguments=arguments,
                    trace_id=trace_id,
                    tool_name=capability.name,
                )
            )
        try:
            self._require(capability.required_scope)
        except ResearchAgentForbidden:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.FORBIDDEN,
                    arguments=arguments,
                    trace_id=trace_id,
                    tool_name=capability.name,
                )
            )
        try:
            validated = TypeAdapter(capability.input_model).validate_python(arguments)
        except ValidationError:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INVALID_INPUT,
                    arguments=arguments,
                    trace_id=trace_id,
                    tool_name=capability.name,
                )
            )
        if not isinstance(validated, BaseModel):
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INTERNAL,
                    arguments=arguments,
                    trace_id=trace_id,
                    tool_name=capability.name,
                ),
                exception=TypeError("Research Agent input contract must produce a model"),
            )
        validated_arguments = validated.model_dump()
        try:
            result = capability.handler(**validated_arguments)
            validated_result = TypeAdapter(capability.output_model).validate_python(result)
            if not isinstance(validated_result, BaseModel):
                raise TypeError("Research Agent output contract must produce a model")
            return ResearchAgentInvocation(result=validated_result)
        except ResearchAgentExpectedFailure as error:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    error.code,
                    arguments=validated_arguments,
                    trace_id=trace_id,
                    tool_name=capability.name,
                    retryable=error.retryable,
                    retry_after_seconds=error.retry_after_seconds,
                )
            )
        except Exception as exception:
            return ResearchAgentInvocation(
                error=self._tool_error(
                    ResearchAgentErrorCode.INTERNAL,
                    arguments=validated_arguments,
                    trace_id=trace_id,
                    tool_name=capability.name,
                ),
                exception=exception,
            )

    def _tool_error(
        self,
        code: ResearchAgentErrorCode,
        *,
        arguments: dict[str, object],
        trace_id: str,
        tool_name: str,
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
            context=safe_tool_call_context(
                tool_name,
                arguments,
                known_tool_names=RESEARCH_AGENT_TOOL_NAMES,
            ),
        )

    def get_research_context(self) -> ResearchContext:
        self._require(ResearchAgentScope.RESEARCH_READ)
        overview = self._modules.data_overview.overview()
        return ResearchContext(
            data_overview=overview,
            folders=self._modules.research_folders.list(self._authority.researcher_id),
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
                self._authority.researcher_id,
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
            detail = self._modules.research_runs.get_polling_detail(
                self._authority.researcher_id,
                run_id,
            )
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if detail is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return detail

    def get_research_run_result(self, **query_fields: object) -> BaseModel:
        self._require(ResearchAgentScope.RESEARCH_READ)
        query = TypeAdapter(ResearchRunResultSectionInput).validate_python(query_fields)
        try:
            result = self._modules.research_runs.get_result_section(
                self._authority.researcher_id,
                query,
            )
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

    def list_daily_tracks(
        self,
        cursor: str | None = None,
        limit: int = 20,
    ) -> DailyTrackList:
        self._require(ResearchAgentScope.TRACKING_READ)
        try:
            return self._modules.daily_tracks.list(
                self._authority.researcher_id,
                cursor=cursor,
                limit=limit,
            )
        except DailyTrackInvalidCursor as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.INVALID_INPUT) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error

    def get_daily_track(self, track_id: str) -> DailyTrackPollingDetail:
        self._require(ResearchAgentScope.TRACKING_READ)
        try:
            track = self._modules.daily_tracks.get_polling_detail(
                self._authority.researcher_id,
                track_id,
            )
        except DailyTrackTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if track is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return track

    def get_daily_track_result(self, **query_fields: object) -> BaseModel:
        self._require(ResearchAgentScope.TRACKING_READ)
        query = TypeAdapter(DailyTrackResultSectionInput).validate_python(query_fields)
        try:
            result = self._modules.daily_tracks.get_result_section(
                self._authority.researcher_id,
                query,
            )
        except DailyTrackInvalidCursor as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.INVALID_INPUT) from error
        except DailyTrackResultUnavailable as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if result is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        if not isinstance(result, BaseModel):
            raise TypeError("DailyTrack Result module returned an invalid section")
        return result

    def start_daily_track(
        self,
        run_id: str,
        request_id: str,
    ) -> StartDailyTrackOutcome:
        self._require(ResearchAgentScope.TRACKING_EXECUTE)
        try:
            outcome = self._modules.research_runs.start_tracking_with_outcome(
                self._authority.researcher_id,
                run_id,
                StartTrackingCommand(request_id=request_id),
            )
        except ResearchRunStartTrackingConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except ResearchRunTrackingUnavailable as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except ResearchRunTrackingTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return StartDailyTrackOutcome(
            track_id=outcome.track.id,
            status=outcome.status,
            replayed=outcome.replayed,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    def retry_daily_track(
        self,
        track_id: str,
        request_id: str,
    ) -> RetryDailyTrackOutcome:
        self._require(ResearchAgentScope.TRACKING_EXECUTE)
        try:
            outcome = self._modules.daily_tracks.retry_with_outcome(
                self._authority.researcher_id,
                track_id,
                RetryDailyTrackCommand(request_id=request_id),
            )
        except DailyTrackRetryConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except DailyTrackRetryUnavailable as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return RetryDailyTrackOutcome(
            track_id=outcome.track.id,
            status=outcome.track.status,
            replayed=outcome.replayed,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    def refresh_daily_track(
        self,
        track_id: str,
        request_id: str,
    ) -> RefreshDailyTrackOutcome:
        self._require(ResearchAgentScope.TRACKING_EXECUTE)
        try:
            outcome = self._modules.daily_tracks.refresh_with_outcome(
                self._authority.researcher_id,
                track_id,
                RefreshDailyTrackCommand(request_id=request_id),
            )
        except DailyTrackRefreshConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except DailyTrackRefreshUnavailable as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return RefreshDailyTrackOutcome(
            track_id=outcome.track.id,
            status=outcome.track.status,
            replayed=outcome.replayed,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    def stop_daily_track(
        self,
        track_id: str,
        request_id: str,
    ) -> StopDailyTrackOutcome:
        self._require(ResearchAgentScope.TRACKING_STOP)
        try:
            outcome = self._modules.daily_tracks.stop_with_outcome(
                self._authority.researcher_id,
                track_id,
                StopDailyTrackCommand(request_id=request_id),
            )
        except DailyTrackStopConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except DailyTrackStopUnavailable as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except DailyTrackTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return StopDailyTrackOutcome(
            track_id=outcome.track.id,
            status=outcome.track.status,
            replayed=outcome.replayed,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    def cancel_research_run(
        self,
        run_id: str,
        request_id: str,
    ) -> ResearchRunCancelOutcome:
        self._require(ResearchAgentScope.RESEARCH_CANCEL)
        try:
            outcome = self._modules.research_runs.cancel(
                self._authority.researcher_id,
                run_id,
                ResearchRunCancelCommand(request_id=request_id),
            )
        except ResearchRunCancelIdempotencyConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except ResearchRunCancelStateConflict as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except ResearchRunTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return outcome

    def list_research_batches(
        self,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ResearchBatchList:
        self._require(ResearchAgentScope.RESEARCH_READ)
        try:
            return self._modules.research_batches.list(
                self._authority.researcher_id,
                cursor=cursor,
                limit=limit,
            )
        except ResearchBatchInvalidCursor as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.INVALID_INPUT) from error
        except ResearchBatchTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error

    def get_research_batch(self, batch_id: str) -> ResearchBatchPollingDetail:
        self._require(ResearchAgentScope.RESEARCH_READ)
        try:
            batch = self._modules.research_batches.get_polling_detail(
                self._authority.researcher_id,
                batch_id,
            )
        except ResearchBatchTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if batch is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return batch

    def cancel_research_batch(
        self,
        batch_id: str,
        request_id: str,
    ) -> CancelResearchBatchOutcome:
        self._require(ResearchAgentScope.RESEARCH_CANCEL)
        try:
            outcome = self._modules.research_batches.cancel_with_outcome(
                self._authority.researcher_id,
                batch_id,
                ResearchBatchCancelCommand(request_id=request_id),
            )
        except ResearchBatchCancelIdempotencyConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except ResearchBatchCancelStateConflict as error:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.STATE_CONFLICT) from error
        except ResearchBatchTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if outcome is None:
            raise ResearchAgentExpectedFailure(ResearchAgentErrorCode.NOT_FOUND)
        return CancelResearchBatchOutcome(
            batch=research_batch_polling_detail(outcome.batch),
            replayed=outcome.replayed,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    def submit_research_batch(self, **command_fields: object) -> BaseModel:
        self._require(ResearchAgentScope.RESEARCH_EXECUTE)
        command = TypeAdapter(ResearchBatchAdmissionCommand).validate_python(command_fields)
        try:
            outcome = self._modules.research_batches.admit_with_outcome(
                self._authority.researcher_id,
                command,
            )
        except ResearchBatchAdmissionConflict as error:
            raise ResearchAgentExpectedFailure(
                ResearchAgentErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        except ResearchBatchTemporarilyUnavailable as error:
            raise _temporarily_unavailable() from error
        if isinstance(outcome, ResearchBatchAdmissionAccepted):
            return SubmitResearchBatchAccepted(
                batch_id=outcome.batch.id,
                status=outcome.batch.status,
                replayed=outcome.replayed,
                retry_after_seconds=outcome.retry_after_seconds,
            )
        return SubmitResearchBatchRejected(
            issues=outcome.issues,
            replayed=outcome.replayed,
        )

    def submit_research_run(self, **command_fields: object) -> BaseModel:
        self._require(ResearchAgentScope.RESEARCH_EXECUTE)
        command = TypeAdapter(ResearchRunAdmissionCommand).validate_python(command_fields)
        try:
            outcome = self._modules.research_runs.admit_with_outcome(
                self._authority.researcher_id,
                command,
            )
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
    researcher_id: UUID,
    enable_research_cancel: bool = False,
    enable_tracking_stop: bool = False,
) -> ResearchAgentAuthority:
    scopes = {
        ResearchAgentScope.RESEARCH_READ,
        ResearchAgentScope.RESEARCH_EXECUTE,
        ResearchAgentScope.TRACKING_READ,
        ResearchAgentScope.TRACKING_EXECUTE,
    }
    if enable_research_cancel:
        scopes.add(ResearchAgentScope.RESEARCH_CANCEL)
    if enable_tracking_stop:
        scopes.add(ResearchAgentScope.TRACKING_STOP)
    return ResearchAgentAuthority(
        subject="local_operator",
        researcher_id=researcher_id,
        scopes=frozenset(scopes),
    )


def _temporarily_unavailable() -> ResearchAgentExpectedFailure:
    return ResearchAgentExpectedFailure(
        ResearchAgentErrorCode.TEMPORARILY_UNAVAILABLE,
        retryable=True,
        retry_after_seconds=2,
    )
