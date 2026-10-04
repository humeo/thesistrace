"""Bounded, lossless MCP reads of large semantic Result sections."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from thesistrace.daily_track.models import (
    DailyTrackResultSectionInput,
    DailyTrackResultSectionResponse,
)
from thesistrace.research_run.models import (
    ResearchRunResultSectionInput,
    ResearchRunResultSectionResponse,
)

INLINE_RESULT_BYTES = 128 * 1024
RESULT_FRAGMENT_BYTES = 32 * 1024
# Includes the original event cursor (up to 8192 characters), read metadata and
# the authenticated envelope. Result fragments remain independently bounded.
ResultPageCursor = Annotated[str, Field(min_length=1, max_length=16 * 1024)]


class ResearchRunResultPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    section: Literal["result_page"]
    query: ResearchRunResultSectionInput = Field(description="The original Result section query.")
    result_cursor: ResultPageCursor


class DailyTrackResultPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    section: Literal["result_page"]
    query: DailyTrackResultSectionInput = Field(description="The original Result section query.")
    result_cursor: ResultPageCursor


class ResearchResultPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    section: Literal["result_page"] = "result_page"
    result_section: str
    encoding: Literal["ascii-json"] = "ascii-json"
    json_fragment: Annotated[str, Field(max_length=RESULT_FRAGMENT_BYTES, description=(
        "One fragment of the semantic Result JSON. Concatenate in offset order before parsing; "
        "never interpret an incomplete fragment as a complete Result."
    ))]
    offset: Annotated[int, Field(ge=0)]
    total_bytes: Annotated[int, Field(gt=0)]
    checksum_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    next_result_cursor: ResultPageCursor | None


type GetResearchRunResultInput = Annotated[
    ResearchRunResultSectionInput | ResearchRunResultPageInput, Field(discriminator="section"),
]
type GetDailyTrackResultInput = Annotated[
    DailyTrackResultSectionInput | DailyTrackResultPageInput, Field(discriminator="section"),
]
type GetResearchRunResultOutput = Annotated[
    ResearchRunResultSectionResponse | ResearchResultPage, Field(discriminator="section"),
]
type GetDailyTrackResultOutput = Annotated[
    DailyTrackResultSectionResponse | ResearchResultPage, Field(discriminator="section"),
]
