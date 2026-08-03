"""Legacy Factor facade; the calculation implementation lives in Research Kernel."""

from thesistrace.research_kernel.factor import (
    HORIZONS,
    FactorDataError,
    average_ranks,
    build_forward_labels,
    correlation_summary,
    empty_quantiles,
    evaluate_factor,
    factor_day,
    mean_or_none,
    pearson,
    unavailable_reason,
)

__all__ = [
    "HORIZONS",
    "FactorDataError",
    "average_ranks",
    "build_forward_labels",
    "correlation_summary",
    "empty_quantiles",
    "evaluate_factor",
    "factor_day",
    "mean_or_none",
    "pearson",
    "unavailable_reason",
]
