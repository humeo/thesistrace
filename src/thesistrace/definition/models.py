from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class DefinitionSaveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int | None = None
    name: str | None = None
    hypothesis: str | None = None
    alpha: dict[str, object] | None = None
    universe: Literal["top300", "top1000", "top2000", "top3000"] | None = None
    neutralization: Literal["none", "industry"] | None = None
    holdings_count: int | None = None
    rebalance_every_sessions: int | None = None


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
