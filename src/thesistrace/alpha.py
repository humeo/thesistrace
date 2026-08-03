"""Legacy Alpha facade; the calculation implementation lives in Research Kernel."""

from collections.abc import Mapping

from thesistrace.data.fields import authorable_field_bindings
from thesistrace.research_kernel.alpha import (
    AlphaValidationError,
    AlphaValidationIssue,
    ParsedAlpha,
    evaluate_node,
    evaluate_parsed_series,
    finite_or_missing,
    issue,
    resolve_industry,
)
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix as _evaluate_alpha_matrix,
)
from thesistrace.research_kernel.alpha import (
    evaluate_series as _evaluate_series,
)
from thesistrace.research_kernel.alpha import (
    validate_alpha as _validate_alpha,
)
from thesistrace.research_kernel.alpha import (
    validate_legacy_alpha as _validate_legacy_alpha,
)
from thesistrace.research_kernel.alpha_expression import AlphaExpression


def validate_alpha(expression: AlphaExpression) -> ParsedAlpha:
    return _validate_alpha(expression, field_bindings=authorable_field_bindings())


def validate_legacy_alpha(
    expression: str,
    *,
    field_bindings: Mapping[str, str] | None = None,
) -> ParsedAlpha:
    return _validate_legacy_alpha(
        expression,
        field_bindings=(authorable_field_bindings() if field_bindings is None else field_bindings),
    )


def evaluate_series(
    expression: AlphaExpression,
    values_by_field: dict[str, list[float | None]],
) -> list[float | None]:
    return _evaluate_series(
        expression,
        values_by_field,
        field_bindings=authorable_field_bindings(),
    )


def evaluate_alpha_matrix(
    canonical: dict[str, object],
    *,
    expression: AlphaExpression,
    universe_name: str,
    neutralization: str,
) -> dict[str, object]:
    return _evaluate_alpha_matrix(
        canonical,
        expression=expression,
        field_bindings=authorable_field_bindings(),
        universe_name=universe_name,
        neutralization=neutralization,
    )


__all__ = [
    "AlphaValidationError",
    "AlphaValidationIssue",
    "ParsedAlpha",
    "evaluate_alpha_matrix",
    "evaluate_node",
    "evaluate_parsed_series",
    "evaluate_series",
    "finite_or_missing",
    "issue",
    "resolve_industry",
    "validate_alpha",
    "validate_legacy_alpha",
]
