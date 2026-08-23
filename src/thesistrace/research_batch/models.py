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
    data_generation_id: str
    data_through_session: date


class ResearchBatchItemSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int
    item_key: str
    research_run_id: str
    dependency_role: Literal["factor", "strategy"]
    status: Literal[
        "queued", "running", "cancelling", "succeeded", "failed", "cancelled"
    ]


class ResearchBatchProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed_items: int
    total_items: int


class ResearchBatchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    batch_kind: ResearchBatchKind
    status: ResearchBatchStatus
    created_at: datetime
    scope: ResearchBatchScope
    progress: ResearchBatchProgress
    items: list[ResearchBatchItemSummary]


class ResearchBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ResearchBatchSummary]
    next_cursor: str | None
