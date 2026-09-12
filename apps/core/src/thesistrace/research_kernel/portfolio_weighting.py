"""Select and weight the final portfolio using current Final Alpha scores."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from fractions import Fraction
from heapq import nsmallest
from itertools import groupby
from typing import Literal

PortfolioWeighting = Literal["equal_weight", "rank_weight"]


def select_portfolio(
    candidates: Sequence[Mapping[str, object]],
    holdings_count: int,
    weighting: PortfolioWeighting,
) -> tuple[list[Mapping[str, object]], dict[str, str]]:
    if weighting not in {"equal_weight", "rank_weight"}:
        raise ValueError("Unsupported portfolio weighting")
    selected = nsmallest(
        holdings_count, candidates,
        key=lambda item: (-Decimal(str(item["value"])), str(item["instrument_id"])),
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
