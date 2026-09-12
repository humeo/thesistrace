"""Typed daily Factor evidence shared by calculation and result publication."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

Count = Annotated[StrictInt, Field(ge=0)]
PositiveCount = Annotated[StrictInt, Field(gt=0)]
Number = StrictFloat | StrictInt
Quantile = Literal["q1", "q2", "q3", "q4", "q5"]


class FactorDailyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    horizon: Literal[1, 5, 20]
    label_entry_session: StrictStr | None
    label_exit_session: StrictStr | None
    label_status: Literal["within_research_period", "right_censored_by_research_period_end"]
    alpha_candidate_count: Count
    alpha_sample_count: Count
    alpha_exclusions: dict[
        Literal["missing_expression", "missing_industry", "industry_group_too_small"], PositiveCount
    ]
    sample_count: Count
    label_exclusions: dict[
        Literal[
            "confirmed_market_open_unavailable",
            "data_unavailable",
            "right_censored_by_research_period_end",
        ],
        PositiveCount,
    ]
    ic: Number | None
    rank_ic: Number | None
    correlation_reason: Literal["sample_insufficient", "constant_array"] | None
    quantile_returns: dict[Quantile, Number | None]
    quantile_counts: dict[Quantile, Count]
    top_bottom_return: Number | None
    quantile_reason: Literal["sample_insufficient"] | None

    @model_validator(mode="after")
    def validate_evidence(self) -> FactorDailyObservation:
        quantiles = {"q1", "q2", "q3", "q4", "q5"}
        if set(self.quantile_counts) != quantiles or set(self.quantile_returns) != quantiles:
            raise ValueError("Factor evidence requires all five groups")
        if self.alpha_candidate_count != self.alpha_sample_count + sum(
            self.alpha_exclusions.values()
        ):
            raise ValueError("Factor Alpha coverage is inconsistent")
        if self.alpha_sample_count != self.sample_count + sum(self.label_exclusions.values()):
            raise ValueError("Factor label coverage is inconsistent")
        censored = self.label_status == "right_censored_by_research_period_end"
        if censored != (self.label_exit_session is None):
            raise ValueError("Factor label boundary is inconsistent")
        if censored:
            if self.sample_count or self.label_exclusions != (
                {"right_censored_by_research_period_end": self.alpha_sample_count}
                if self.alpha_sample_count
                else {}
            ):
                raise ValueError("Censored Factor labels cannot be evaluated")
        elif (
            self.label_entry_session is None
            or "right_censored_by_research_period_end" in self.label_exclusions
        ):
            raise ValueError("Factor label coordinates are incomplete")
        values = (self.ic, self.rank_ic, self.top_bottom_return, *self.quantile_returns.values())
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("Factor evidence must be finite or missing")
        if any(value is not None and not -1 <= value <= 1 for value in (self.ic, self.rank_ic)):
            raise ValueError("Factor correlation is outside its range")
        if (self.correlation_reason is None) != (self.ic is not None and self.rank_ic is not None):
            raise ValueError("Factor correlation availability is inconsistent")
        insufficient = self.sample_count < 30
        if insufficient != (self.quantile_reason == "sample_insufficient"):
            raise ValueError("Factor group availability is inconsistent")
        if insufficient and self.correlation_reason != "sample_insufficient":
            raise ValueError("Factor sample insufficiency is unexplained")
        if sum(self.quantile_counts.values()) != (0 if insufficient else self.sample_count):
            raise ValueError("Factor group counts do not reconcile")
        for name in quantiles:
            if (self.quantile_counts[name] == 0) != (self.quantile_returns[name] is None):
                raise ValueError("Factor empty group must be missing")
        bottom, top = self.quantile_returns["q1"], self.quantile_returns["q5"]
        expected = None if bottom is None or top is None else top - bottom
        if self.top_bottom_return != expected:
            raise ValueError("Factor Top-Bottom does not reconcile")
        return self


def validate_factor_observations(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = [FactorDailyObservation.model_validate(row).model_dump(mode="json") for row in rows]
    coordinates = [(row["horizon"], row["session"]) for row in result]
    if coordinates != sorted(set(coordinates)):
        raise ValueError("Factor daily coordinates must be unique and ordered")
    return result


def factor_resolution_coordinates(
    sessions: tuple[str, ...], *, before: int, after: int, final: bool,
) -> list[tuple[int, str]]:
    """Exactly the signals whose labels this Chunk resolves, including terminal censoring."""
    if (
        sessions != tuple(sorted(set(sessions)))
        or not 0 <= before <= after <= len(sessions)
        or (final and after != len(sessions))
    ):
        raise ValueError("Factor resolution boundary is invalid")
    return [
        (horizon, session)
        for horizon in (1, 5, 20)
        for session in sessions[
            max(0, before - horizon - 1):
            (len(sessions) if final else max(0, after - horizon - 1))
        ]
    ]
