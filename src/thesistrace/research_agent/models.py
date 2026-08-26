from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from thesistrace.alpha_language.models import (
    AlphaBuiltinCatalogEntry,
    AlphaFieldCatalogEntry,
)
from thesistrace.data.models import DataOverview
from thesistrace.research_authoring.models import ResearchAuthoringConstraints
from thesistrace.research_batch.models import (
    ResearchBatchAdmissionIssue,
    ResearchBatchPollingDetail,
    ResearchBatchStatus,
)
from thesistrace.research_folder.models import ResearchFolderList
from thesistrace.research_run.models import (
    RequestId,
    ResearchKind,
    ResearchRunAdmissionIssue,
    ResearchRunStatus,
)


class ResearchAgentScope(StrEnum):
    RESEARCH_READ = "research:read"
    RESEARCH_EXECUTE = "research:execute"
    RESEARCH_CANCEL = "research:cancel"
    TRACKING_READ = "tracking:read"
    TRACKING_EXECUTE = "tracking:execute"
    TRACKING_STOP = "tracking:stop"


class ResearchAgentErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    STATE_CONFLICT = "STATE_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INTERNAL = "INTERNAL"


class ResearchAgentToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: ResearchAgentErrorCode
    message: Annotated[str, Field(min_length=1, max_length=200)]
    retryable: bool
    trace_id: Annotated[
        str,
        Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    ]
    retry_after_seconds: Annotated[int, Field(ge=1, le=60)] | None = None


class ResearchAgentAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject: Annotated[str, Field(min_length=1, max_length=200)]
    scopes: frozenset[ResearchAgentScope]

    def permits(self, scope: ResearchAgentScope) -> bool:
        return scope in self.scopes


class ResearchContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    data_overview: DataOverview
    folders: ResearchFolderList
    authoring_constraints: ResearchAuthoringConstraints


AlphaCatalogIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"),
]
AlphaCatalogIdentifiers = Annotated[
    list[AlphaCatalogIdentifier],
    Field(min_length=1, max_length=50),
]
FormulaSource = Annotated[str, Field(strict=True, max_length=4096)]


class GetResearchContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GetAlphaCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    identifiers: AlphaCatalogIdentifiers | None = None


class DiagnoseAlphaFormulaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: FormulaSource


class AlphaCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fields: list[AlphaFieldCatalogEntry]
    builtins: list[AlphaBuiltinCatalogEntry]
    unknown_identifiers: list[str]


ResearchRunId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
ResearchRunCursor = Annotated[str, Field(strict=True, min_length=1, max_length=1024)]
ResearchBatchId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
ResearchBatchCursor = Annotated[str, Field(strict=True, min_length=1, max_length=1024)]
DailyTrackId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
DailyTrackCursor = Annotated[str, Field(strict=True, min_length=1, max_length=1024)]


class ListResearchRunsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    folder_id: Annotated[str, Field(strict=True, min_length=1, max_length=200)] | None = None
    research_kind: ResearchKind | None = None
    cursor: ResearchRunCursor | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20


class GetResearchRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: ResearchRunId


class CancelResearchRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: ResearchRunId
    request_id: RequestId


class ListResearchBatchesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cursor: ResearchBatchCursor | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20


class GetResearchBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    batch_id: ResearchBatchId


class CancelResearchBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    batch_id: ResearchBatchId
    request_id: RequestId


class CancelResearchBatchOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["accepted"] = "accepted"
    batch: ResearchBatchPollingDetail
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class ListDailyTracksInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cursor: DailyTrackCursor | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20


class GetDailyTrackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track_id: DailyTrackId


class StartDailyTrackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: ResearchRunId
    request_id: RequestId


class StartDailyTrackOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["accepted"] = "accepted"
    track_id: DailyTrackId
    status: Literal["active"]
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)]


class RetryDailyTrackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track_id: DailyTrackId
    request_id: RequestId


class RetryDailyTrackOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["accepted"] = "accepted"
    track_id: DailyTrackId
    status: Literal["active", "blocked"]
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class StopDailyTrackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track_id: DailyTrackId
    request_id: RequestId


class StopDailyTrackOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["accepted"] = "accepted"
    track_id: DailyTrackId
    status: Literal["stopping", "stopped"]
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class SubmitResearchBatchAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["accepted"] = "accepted"
    batch_id: ResearchBatchId
    status: ResearchBatchStatus
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class SubmitResearchBatchRejected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["rejected"] = "rejected"
    issues: Annotated[list[ResearchBatchAdmissionIssue], Field(min_length=1)]
    replayed: bool


type SubmitResearchBatchOutcome = Annotated[
    SubmitResearchBatchAccepted | SubmitResearchBatchRejected,
    Field(discriminator="outcome"),
]


class SubmitResearchRunAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["accepted"] = "accepted"
    run_id: ResearchRunId
    status: ResearchRunStatus
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class SubmitResearchRunRejected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["rejected"] = "rejected"
    issues: Annotated[list[ResearchRunAdmissionIssue], Field(min_length=1)]
    replayed: bool


type SubmitResearchRunOutcome = Annotated[
    SubmitResearchRunAccepted | SubmitResearchRunRejected,
    Field(discriminator="outcome"),
]
