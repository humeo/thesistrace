from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

FolderName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120, strict=True),
]


class ResearchFolderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: FolderName
    is_default: bool
    created_at: datetime


class ResearchFolderList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ResearchFolderSummary]
    next_cursor: None = None


class CreateResearchFolder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FolderName


class RenameResearchFolder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FolderName
