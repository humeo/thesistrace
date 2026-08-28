from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

CanonicalEmail = Annotated[
    str,
    StringConstraints(min_length=3, max_length=254, strict=True),
]
DisplayLabel = Annotated[
    str,
    StringConstraints(min_length=1, max_length=254, strict=True),
]


class ResearcherIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    researcher_id: UUID
    email: CanonicalEmail
    display_label: DisplayLabel

    @field_validator("email")
    @classmethod
    def validate_canonical_email(cls, value: str) -> str:
        local, separator, domain = value.partition("@")
        if (
            value != value.strip().lower()
            or not separator
            or not local
            or not domain
            or "@" in domain
        ):
            raise ValueError("email must be canonical")
        return value

    @field_validator("display_label")
    @classmethod
    def validate_display_label(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("display label must be trimmed")
        return value


class SystemResearchFolders(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: Literal["folder_default"]
    batch_research: Literal["folder_batch_research"]


class ResearcherBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    researcher_id: UUID
    system_folders: SystemResearchFolders


__all__ = (
    "ResearcherBootstrapResult",
    "ResearcherIdentity",
    "SystemResearchFolders",
)
