from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReleaseSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    predecessor_id: str | None


class DataOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["idle", "updating", "failed"]
    latest_release: ReleaseSummary | None
    latest_update_outcome: Literal["published", "no_change", "failed"] | None


class ReleaseHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ReleaseSummary]
    next_cursor: str | None
