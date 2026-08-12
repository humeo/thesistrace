from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ResearchFolderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    is_default: bool
    created_at: datetime


class ResearchFolderList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ResearchFolderSummary]
    next_cursor: None = None
