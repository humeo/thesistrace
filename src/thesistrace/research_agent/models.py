from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from thesistrace.alpha_language.models import (
    AlphaBuiltinCatalogEntry,
    AlphaFieldCatalogEntry,
)
from thesistrace.data.models import DataOverview
from thesistrace.research_authoring.models import ResearchAuthoringConstraints
from thesistrace.research_folder.models import ResearchFolderList


class ResearchAgentScope(StrEnum):
    RESEARCH_READ = "research:read"
    RESEARCH_EXECUTE = "research:execute"
    RESEARCH_CANCEL = "research:cancel"
    TRACKING_READ = "tracking:read"
    TRACKING_EXECUTE = "tracking:execute"
    TRACKING_STOP = "tracking:stop"


class ResearchAgentErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    STATE_CONFLICT = "STATE_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INTERNAL = "INTERNAL"


class ResearchAgentToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: ResearchAgentErrorCode
    message: Annotated[str, Field(min_length=1, max_length=200)]
    retryable: bool
    trace_id: Annotated[
        str,
        Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    ]
    retry_after_seconds: Annotated[int, Field(ge=1, le=60)] | None = None


class ResearchAgentAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject: Annotated[str, Field(min_length=1, max_length=200)]
    scopes: frozenset[ResearchAgentScope]

    def permits(self, scope: ResearchAgentScope) -> bool:
        return scope in self.scopes


class ResearchContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    data_overview: DataOverview
    folders: ResearchFolderList
    authoring_constraints: ResearchAuthoringConstraints


AlphaCatalogIdentifier = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$"),
]
AlphaCatalogIdentifiers = Annotated[
    list[AlphaCatalogIdentifier],
    Field(min_length=1, max_length=50),
]
FormulaSource = Annotated[str, Field(strict=True, max_length=4096)]


class GetResearchContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GetAlphaCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    identifiers: AlphaCatalogIdentifiers | None = None


class DiagnoseAlphaFormulaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: FormulaSource


class AlphaCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fields: list[AlphaFieldCatalogEntry]
    builtins: list[AlphaBuiltinCatalogEntry]
    unknown_identifiers: list[str]
