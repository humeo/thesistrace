"""Current constant account Exposure, validated and evaluated by the expression engine."""

import math
from collections.abc import Mapping

from thesistrace.research_kernel.alpha_expression import validate_normalized_exposure
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_series_execution_plan,
)


def constant_exposure(expression: Mapping[str, object]) -> float:
    if not isinstance(expression, Mapping):
        raise ValueError("Exposure expression must be a normalized tree")
    parsed = validate_normalized_exposure(expression)
    value = evaluate_series_execution_plan(build_series_execution_plan(parsed), {})[0]
    if value is None or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Exposure must be a finite number between 0 and 1")
    return float(value)
