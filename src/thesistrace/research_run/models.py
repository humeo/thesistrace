from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ImmutableRunInput(BaseModel):
    """Private, complete value input owned by one ResearchRun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: dict[str, object]
    dataset_release_id: str
    field_bindings: dict[str, str]
    strategy: dict[str, object]
    costs: dict[str, str]
    risk_free_rate: str
    numeric_execution_contract: str
    semantic_versions: dict[str, str]


class ResearchRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    definition_id: str
    definition_revision: int
    dataset_release_id: str


class ResearchRunList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ResearchRunSummary]
    next_cursor: str | None
