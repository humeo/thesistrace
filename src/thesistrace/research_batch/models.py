from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from thesistrace.alpha_language.models import DiagnosticDetails, SourceRange
from thesistrace.research_run.models import (
    Formula,
    HoldingsCount,
    NaturalDate,
    RebalanceInterval,
    RequestId,
    ResearchName,
)


def _normalized_item_key(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


ItemKey = Annotated[
    str,
    BeforeValidator(_normalized_item_key),
    Field(strict=True, min_length=1, max_length=200),
]
type ResearchBatchKind = Literal["factor_evaluation", "strategy_sweep"]
type ResearchBatchStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "succeeded",
    "completed_with_failures",
    "failed",
    "cancelled",
]


class _ResearchBatchAdmissionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId
    start_date: NaturalDate
    end_date: NaturalDate
    universe: Literal["top300", "top1000", "top2000", "top3000"]
    neutralization: Literal["none", "industry"]

    @model_validator(mode="after")
    def validate_research_period(self) -> _ResearchBatchAdmissionBase:
        if self.start_date > self.end_date:
            raise ValueError("Research end date must not precede start date")
        return self


class FactorBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    item_key: ItemKey
    name: ResearchName | None = None
    formula: Formula
    hypothesis: str | None = None


class FactorEvaluationBatchAdmissionCommand(_ResearchBatchAdmissionBase):
    batch_kind: Literal["factor_evaluation"]
    factors: list[FactorBatchItem] = Field(min_length=1, max_length=20)


class StrategySweepAlpha(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    formula: Formula
    hypothesis: str | None = None


class StrategySweepItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    item_key: ItemKey
    name: ResearchName | None = None
    holdings_count: HoldingsCount
    rebalance_every_sessions: RebalanceInterval


class StrategySweepBatchAdmissionCommand(_ResearchBatchAdmissionBase):
    batch_kind: Literal["strategy_sweep"]
    alpha: StrategySweepAlpha
    strategies: list[StrategySweepItem] = Field(min_length=1, max_length=20)


type ResearchBatchAdmissionCommand = Annotated[
    FactorEvaluationBatchAdmissionCommand | StrategySweepBatchAdmissionCommand,
    Field(discriminator="batch_kind"),
]


class ResearchBatchCancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class ResearchBatchAdmissionIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str
    message: str
    item_key: str | None = None
    severity: Literal["error"] = "error"
    range: SourceRange | None = None
    details: DiagnosticDetails | None = None


class ResearchBatchAdmissionRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issues: list[ResearchBatchAdmissionIssue]


class ResearchBatchScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date
    universe: Literal["top300", "top1000", "top2000", "top3000"]
    neutralization: Literal["none", "industry"]
    numeric_execution_contract: str
    semantic_versions: dict[str, str]
    data_through_session: date


class ResearchBatchStorageScope(ResearchBatchScope):
    data_generation_id: str


class ResearchBatchItemSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int
    item_key: str
    research_run_id: str
    dependency_role: Literal["factor", "strategy"]
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    outcome: Literal["succeeded", "failed", "cancelled"] | None = None
    run_availability: Literal["available", "deleted"]
    task_attempt_count: int = Field(ge=0, le=3)
    diagnostic: ResearchBatchDiagnostic | None = None
    deleted_at: datetime | None = None


class ResearchBatchDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    category: str
    message: str


class FactorEvaluationBatchProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed_factor_tasks: int
    total_factor_tasks: int


class StrategySweepBatchProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shared_alpha_factor_status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    completed_strategy_tasks: int
    total_strategy_tasks: int


type ResearchBatchProgress = FactorEvaluationBatchProgress | StrategySweepBatchProgress


class ResearchBatchExecutionTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    started_at: datetime | None
    finished_at: datetime | None
    elapsed_seconds: float | None
    is_final: bool


class ResearchBatchAttemptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    number: int
    status: Literal["running", "succeeded", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime | None
    diagnostic: ResearchBatchDiagnostic | None = None


class ResearchBatchLiveProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: int
    task_role: Literal["preparation", "factor", "shared_alpha_factor", "strategy"]
    item_key: str | None
    phase: Literal["preparing_data", "warmup", "research", "strategy", "finalizing"]
    completed_research_sessions: int | None
    total_research_sessions: int | None
    estimated_percentage: float = Field(ge=0, le=100)
    elapsed_seconds: float = Field(ge=0)
    remaining_duration_estimate_seconds: int | None = Field(default=None, ge=1)
    is_estimate: Literal[True] = True
    observed_at: datetime


class ResearchBatchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    batch_kind: ResearchBatchKind
    status: ResearchBatchStatus
    created_at: datetime
    scope: ResearchBatchScope
    progress: ResearchBatchProgress
    execution_timing: ResearchBatchExecutionTiming


class ResearchBatchDetail(ResearchBatchSummary):
    attempt: ResearchBatchAttemptSummary | None
    live_progress: ResearchBatchLiveProgress | None
    items: list[ResearchBatchItemSummary]


class ResearchBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ResearchBatchSummary]
    next_cursor: str | None
