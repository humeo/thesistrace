from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Revision = Annotated[int, Field(strict=True, ge=1)]
HoldingsCount = Annotated[int, Field(strict=True, ge=1, le=100)]
RebalanceInterval = Annotated[int, Field(strict=True, ge=1, le=20)]


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


class DefinitionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    revision: int


class DefinitionList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DefinitionSummary]
    next_cursor: str | None


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
    kind: Literal["arithmetic", "scalar", "historical", "rolling"]
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
