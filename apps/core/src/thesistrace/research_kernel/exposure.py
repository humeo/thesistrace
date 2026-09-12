"""Account Exposure validation and governed daily expression evaluation."""

import math
from collections.abc import Mapping

import numpy as np

from thesistrace.research_kernel.alpha_expression import ParsedAlpha, validate_normalized_exposure
from thesistrace.research_kernel.common_inputs import CLOSE_FIELD_ID, common_input_references
from thesistrace.research_kernel.series_plan import (
    CommonInputObserver,
    build_series_execution_plan,
    evaluate_common_execution_series,
    evaluate_series_execution_plan,
)
from thesistrace.research_series import AlignedResearchData, ColumnarResearchSeries


def validate_exposure(expression: Mapping[str, object]) -> ParsedAlpha:
    parsed = validate_normalized_exposure(expression)
    if not common_input_references(expression):
        constant_exposure(expression)
    return parsed


def constant_exposure(expression: Mapping[str, object]) -> float:
    if not isinstance(expression, Mapping):
        raise ValueError("Exposure expression must be a normalized tree")
    parsed = validate_normalized_exposure(expression)
    value = evaluate_series_execution_plan(build_series_execution_plan(parsed), {})[0]
    if value is None or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Exposure must be a finite number between 0 and 1")
    return float(value)



def evaluate_exposure_series(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    expression: Mapping[str, object],
    *,
    observe_common: CommonInputObserver | None = None,
) -> dict[str, float | None]:
    parsed = validate_exposure(expression)
    sessions = tuple(research_data.sessions)
    if not common_input_references(expression):
        value = constant_exposure(expression)
        return dict.fromkeys(sessions, value)
    members = research_data.historical_universe_members
    instruments = tuple(sorted({item for session in sessions for item in members.get(session, ())}))
    if isinstance(research_data, ColumnarResearchSeries):
        closes = research_data.numeric_field_matrices(
            (CLOSE_FIELD_ID,), instruments,
        )[CLOSE_FIELD_ID]
    else:
        closes = np.array([
            [
                float(value) if (value := research_data.fields[CLOSE_FIELD_ID].get((session, item)))
                is not None else np.nan
                for session in sessions
            ]
            for item in instruments
        ], dtype=np.float64).reshape((len(instruments), len(sessions)))
    values = evaluate_common_execution_series(
        build_series_execution_plan(parsed), instruments, sessions, closes,
        members, research_data.industries, observe_common=observe_common,
    )
    return dict(zip(sessions, values, strict=True))


def require_exposure_value(value: float | None, session: str) -> float:
    if value is None or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"Exposure must be finite and between zero and one on {session}")
    return float(value)
