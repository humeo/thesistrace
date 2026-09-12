"""Shared Run and Track evidence for a common market input."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from thesistrace.research_kernel.common_inputs import COMMON_INPUTS
from thesistrace.research_kernel.common_market import CommonMarketSeries


class CommonInputObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session: Annotated[StrictStr, Field(min_length=1, max_length=32)]
    identifier: Literal[
        "universe_return",
        "universe_advancing_fraction",
        "industry_return",
        "industry_advancing_fraction",
    ]
    industry_code: StrictStr | None
    value: StrictInt | StrictFloat | None
    member_count: Annotated[StrictInt, Field(ge=0)]
    valid_count: Annotated[StrictInt, Field(ge=0)]
    exclusions: dict[
        Literal[
            "insufficient_history",
            "invalid_current_close",
            "invalid_previous_close",
            "non_finite_return",
        ],
        Annotated[StrictInt, Field(gt=0)],
    ]

    @model_validator(mode="after")
    def validate_evidence(self) -> CommonInputObservation:
        from thesistrace.research_kernel.common_inputs import validate_common_reference

        validate_common_reference(
            {
                "kind": "common",
                "identifier": self.identifier,
                "industry_code": self.industry_code,
            }
        )
        if self.valid_count + sum(self.exclusions.values()) != self.member_count:
            raise ValueError("Common input sample accounting is inconsistent")
        if (self.value is None) != (self.valid_count == 0):
            raise ValueError("Common input value must reflect valid sample availability")
        if self.value is not None:
            if not math.isfinite(self.value):
                raise ValueError("Common input value must be finite")
            if self.identifier.endswith("advancing_fraction") and not 0 <= self.value <= 1:
                raise ValueError("Common advancing fraction must be within zero and one")
        return self


class CommonInputObservationError(ValueError):
    pass


def common_input_observation_rows(
    alpha_matrix: Mapping[str, object],
    *,
    sessions: tuple[str, ...],
) -> list[dict[str, object]]:
    """Select this chunk's observations, excluding warm-up and retained pending rows."""
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise CommonInputObservationError("Common observation Sessions are invalid")
    matrix_rows = alpha_matrix.get("sessions")
    if not isinstance(matrix_rows, list):
        raise CommonInputObservationError("Common observation matrix is invalid")
    selected = set(sessions)
    seen_sessions: set[str] = set()
    identities: set[tuple[str, str, str]] = set()
    result: list[dict[str, object]] = []
    for row in matrix_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("session"), str):
            raise CommonInputObservationError("Common observation Session is invalid")
        session = row["session"]
        if session not in selected:
            continue
        if session in seen_sessions:
            raise CommonInputObservationError("Common observation Session is duplicated")
        seen_sessions.add(session)
        if "common_inputs" not in row:
            continue
        observations = row["common_inputs"]
        if not isinstance(observations, list):
            raise CommonInputObservationError("Common observations are invalid")
        for observation in observations:
            if not isinstance(observation, Mapping) or "session" in observation:
                raise CommonInputObservationError("Common observation is invalid")
            try:
                value = CommonInputObservation.model_validate({"session": session, **observation})
            except ValidationError as error:
                raise CommonInputObservationError(
                    "Common observation evidence is invalid"
                ) from error
            identity = (session, value.identifier, value.industry_code or "")
            if identity in identities:
                raise CommonInputObservationError("Common observation identity is duplicated")
            identities.add(identity)
            result.append(value.model_dump(mode="json"))
    if seen_sessions != selected:
        raise CommonInputObservationError("Common observation Sessions are incomplete")
    return sorted(
        result,
        key=lambda value: (
            value["session"],
            value["identifier"],
            value["industry_code"] or "",
        ),
    )


def record_common_input(
    observations: dict[str, list[dict[str, object]]],
    sessions: list[str] | tuple[str, ...],
    identifier: str,
    industry_code: str | None,
    series: CommonMarketSeries,
) -> None:
    values = getattr(series, COMMON_INPUTS[identifier][0])
    for index, session in enumerate(sessions):
        observations.setdefault(session, []).append(
            {
                "identifier": identifier,
                "industry_code": industry_code,
                "value": (float(values[index]) if math.isfinite(float(values[index])) else None),
                "member_count": series.member_count[index],
                "valid_count": series.valid_count[index],
                "exclusions": dict(series.exclusions[index]),
            }
        )


def merge_common_input_sessions(
    signal_sessions: list[dict[str, object]],
    exposure_observations: Mapping[str, list[dict[str, object]]],
    sessions: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    """Combine per-strategy evidence without mutating a shared Signal artifact."""
    signal = {row["session"]: row.get("common_inputs", []) for row in signal_sessions}
    result = []
    for session in sessions:
        combined = {}
        for row in [*signal.get(session, []), *exposure_observations.get(session, [])]:
            key = (row["identifier"], row["industry_code"] or "")
            if key in combined and combined[key] != row:
                raise CommonInputObservationError("Signal and Exposure common evidence disagrees")
            combined[key] = dict(row)
        if combined:
            result.append({
                "session": session,
                "common_inputs": [combined[key] for key in sorted(combined)],
            })
    return tuple(result)


def attach_common_input_evidence(
    matrix: dict[str, object],
    exposure_observations: Mapping[str, list[dict[str, object]]],
    sessions: tuple[str, ...],
) -> None:
    """Enrich a privately owned result matrix; shared Alpha artifacts stay immutable."""
    rows = matrix["sessions"]
    merged = {
        row["session"]: row["common_inputs"]
        for row in merge_common_input_sessions(
            rows, exposure_observations, sessions,
        )
    }
    for row in rows:
        if row["session"] in merged:
            row["common_inputs"] = merged[row["session"]]
