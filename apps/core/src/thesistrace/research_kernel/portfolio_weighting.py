"""Select and weight the final portfolio using current Final Alpha scores."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from heapq import nsmallest
from itertools import groupby
from typing import Annotated, Literal

from pydantic import Field, StrictInt

PortfolioWeighting = Literal["equal_weight", "rank_weight", "inverse_volatility"]
EligibilityReason = Literal["zero_volatility", "insufficient_history", "unavailable_return"]
VolatilityWindow = Annotated[StrictInt, Field(ge=1, le=252)]


def select_portfolio(
    candidates: Sequence[Mapping[str, object]],
    holdings_count: int,
    weighting: PortfolioWeighting,
) -> tuple[list[Mapping[str, object]], dict[str, str]]:
    if weighting not in {"equal_weight", "rank_weight"}:
        raise ValueError("Unsupported portfolio weighting")
    selected = nsmallest(
        holdings_count, candidates,
        key=_candidate_order,
    )
    count = len(selected)
    if not count:
        return selected, {}
    if weighting == "equal_weight":
        return selected, {str(item["instrument_id"]): str(Fraction(1, count)) for item in selected}
    weights = {}
    offset = 0
    for _, tied in groupby(selected, key=lambda item: Decimal(str(item["value"]))):
        group = list(tied)
        # Twice the average occupied raw rank, divided by twice the total.
        weight = str(Fraction(
            2 * count - 2 * offset - len(group) + 1, count * (count + 1),
        ))
        weights.update((str(item["instrument_id"]), weight) for item in group)
        offset += len(group)
    return selected, weights


def _candidate_order(item: Mapping[str, object]) -> tuple[Decimal, str]:
    return -Decimal(str(item["value"])), str(item["instrument_id"])


def inverse_volatility_selection(
    candidates: Sequence[Mapping[str, object]],
    holdings_count: int,
    close_windows: Mapping[str, Sequence[object]],
    window: int,
) -> tuple[list[Mapping[str, object]], dict[str, str], list[dict[str, str]]]:
    """Select eligible candidates from Close histories ending at the decision Close."""
    if type(window) is not int or not 1 <= window <= 252:
        raise ValueError("Invalid volatility window")
    selected: list[Mapping[str, object]] = []
    raw_weights: dict[str, Fraction] = {}
    excluded: list[dict[str, str]] = []
    for item in sorted(candidates, key=_candidate_order):
        if len(selected) >= holdings_count:
            break
        instrument_id = str(item["instrument_id"])
        # Missing mapping entries are data-access contract errors, not eligibility failures.
        history = close_windows[instrument_id]
        if len(history) < window + 1:
            excluded.append({"instrument_id": instrument_id, "reason": "insufficient_history"})
            continue
        try:
            closes = [Decimal(str(value)) for value in history[-window - 1:]]
        except (InvalidOperation, ValueError):
            closes = []
        if not closes or any(not value.is_finite() or value <= 0 for value in closes):
            excluded.append({"instrument_id": instrument_id, "reason": "unavailable_return"})
            continue
        with localcontext() as context:
            context.prec = 34
            sigma = population_return_volatility(closes)
            if sigma == 0:
                excluded.append({"instrument_id": instrument_id, "reason": "zero_volatility"})
                continue
            inverse = 1 / sigma
        selected.append(item)
        # Round the inverse in the numeric context before rational normalization.
        # Decimal denominators share powers of ten, keeping frozen weights bounded.
        raw_weights[instrument_id] = Fraction(inverse)
    total = sum(raw_weights.values(), Fraction())
    return selected, {name: str(value / total) for name, value in raw_weights.items()}, excluded


def population_return_volatility(closes: Sequence[Decimal]) -> Decimal:
    """Population deviation of single-session returns from validated ordered Close values."""
    if len(closes) < 2:
        raise ValueError("Volatility needs at least two Close observations")
    with localcontext() as context:
        context.prec = 34
        returns = [
            current / prior - 1
            for prior, current in zip(closes[:-1], closes[1:], strict=True)
        ]
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / len(returns)
        return variance.sqrt()
