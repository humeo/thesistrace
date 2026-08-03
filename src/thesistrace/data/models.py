from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReleaseSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    predecessor_id: str | None
    session_count: int
    covered_session_range: dict[str, str]


class DataOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["idle", "updating", "failed"]
    latest_release: ReleaseSummary | None
    latest_update_outcome: Literal["published", "no_change", "failed"] | None


class ReleaseHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ReleaseSummary]
    next_cursor: str | None


class UpdateAcceptance(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    outcome: Literal["accepted", "published", "no_change", "failed"]
