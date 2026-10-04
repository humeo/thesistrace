"""The same bounded authoring reference is read by HTTP and MCP clients."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type AuthoringTopic = Literal["workflow", "formula", "python_sdk", "examples"]
AuthoringSymbol = Annotated[str, Field(min_length=1, max_length=100)]


class AuthoringReferenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic: AuthoringTopic = "workflow"
    symbol: AuthoringSymbol | None = None


class AuthoringTopicSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: AuthoringTopic
    title: str
    summary: str


class AuthoringGuide(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    steps: tuple[str, ...]
    topics: tuple[AuthoringTopicSummary, ...]


class AuthoringSymbolSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    description: str


class AuthoringExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    language: Literal["python", "formula", "json"]
    source: str
    entrypoint: str | None = None
    context: Literal["signal", "exposure"] | None = None


class AuthoringReferenceEntry(AuthoringSymbolSummary):
    signature: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)
    returns: str | None = None
    notes: tuple[str, ...] = ()
    examples: tuple[AuthoringExample, ...] = ()
    constraints: dict[str, object] = Field(default_factory=dict)
    # Schemas come from the same public domain models used in execution.
    data_schema: dict[str, object] | None = None


class AuthoringReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: AuthoringTopic
    title: str
    overview: tuple[str, ...]
    found: bool
    symbols: tuple[AuthoringSymbolSummary, ...]
    entry: AuthoringReferenceEntry | None
