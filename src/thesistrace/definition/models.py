from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from thesistrace.research_run import ResearchRunSummary

Revision = Annotated[int, Field(strict=True, ge=1)]
HoldingsCount = Annotated[int, Field(strict=True, ge=1, le=100)]
RebalanceInterval = Annotated[int, Field(strict=True, ge=1, le=20)]
RequestId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


def _natural_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError("natural date must be an ISO YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("natural date must be an ISO YYYY-MM-DD string") from error
    if parsed.isoformat() != value:
        raise ValueError("natural date must be an ISO YYYY-MM-DD string")
    return parsed


NaturalDate = Annotated[date, BeforeValidator(_natural_date)]


class DefinitionSaveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_revision: Revision | None = None
    name: str | None = None
    hypothesis: str | None = None
    alpha: dict[str, object] | None = None
    universe: Literal["top300", "top1000", "top2000", "top3000"] | None = None
    neutralization: Literal["none", "industry"] | None = None
    holdings_count: HoldingsCount | None = None
    rebalance_every_sessions: RebalanceInterval | None = None
    start_date: NaturalDate | None = None
    end_date: NaturalDate | None = None


class DefinitionRunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId
    expected_revision: Revision | None = None
    name: str | None = None
    hypothesis: str | None = None
    alpha: dict[str, object] | None = None
    universe: Literal["top300", "top1000", "top2000", "top3000"] | None = None
    neutralization: Literal["none", "industry"] | None = None
    holdings_count: HoldingsCount | None = None
    rebalance_every_sessions: RebalanceInterval | None = None
    start_date: NaturalDate | None = None
    end_date: NaturalDate | None = None


class DefinitionDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    revision: int
    name: str
    hypothesis: str | None
    alpha: dict[str, object] | None
    universe: Literal["top300", "top1000", "top2000", "top3000"] | None
    neutralization: Literal["none", "industry"] | None
    holdings_count: int | None
    rebalance_every_sessions: int | None
    start_date: NaturalDate | None
    end_date: NaturalDate | None


class DefinitionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    revision: int


class DefinitionList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DefinitionSummary]
    next_cursor: str | None


class RunValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    field: str
    message: str


class DefinitionRunOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["rejected", "accepted"]
    definition: DefinitionDetail
    issues: list[RunValidationIssue]
    run: ResearchRunSummary | None = None


class IntegerBounds(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum: int
    maximum: int


class AuthorableFieldOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_id: str
    definition: str
    unit: str
    result_type: Literal["numeric"] = "numeric"


class OperatorOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    operator_id: str
    kind: Literal["arithmetic", "scalar", "historical", "rolling", "cross-sectional"]
    lookback_rule: Literal["none", "historical", "rolling"]
    complexity: str
    arity: int
    operand_rules: list[Literal["numeric", "window"]]
    result_type: Literal["numeric"]
    rolling_bounds: IntegerBounds | None


class DefinitionAuthoringOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    fields: list[AuthorableFieldOption]
    operators: list[OperatorOption]
    universes: list[Literal["top300", "top1000", "top2000", "top3000"]]
    neutralizations: list[Literal["none", "industry"]]
    holdings_count: IntegerBounds
    rebalance_every_sessions: IntegerBounds
