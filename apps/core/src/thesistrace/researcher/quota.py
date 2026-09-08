"""Effective quota policy supplied by Auth, with no local business defaults."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

QuotaLimit = Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]


class QuotaPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    timezone: str
    daily_model_budget_nanodollars: QuotaLimit | None
    daily_run_limit: QuotaLimit | None
    active_daily_track_limit: QuotaLimit | None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Invalid quota timezone") from error
        return value


type QuotaPolicyLookup = Callable[[UUID], QuotaPolicy]


class QuotaPolicyUnavailable(RuntimeError):
    pass


def unavailable_quota_policy(_researcher_id: UUID) -> QuotaPolicy:
    raise QuotaPolicyUnavailable("Quota policy is not configured")
