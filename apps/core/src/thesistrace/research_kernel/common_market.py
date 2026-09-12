from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CommonMarketSeries:
    equal_weight_return: np.ndarray
    advancing_fraction: np.ndarray
    member_count: tuple[int, ...]
    valid_count: tuple[int, ...]
    exclusions: tuple[dict[str, int], ...]


def compute_common_market_series(
    *,
    sessions: tuple[str, ...],
    instruments: tuple[str, ...],
    adjusted_close: np.ndarray,
    universe_members: Mapping[str, tuple[str, ...]],
    industries: Mapping[tuple[str, str], str],
    industry_code: str | None = None,
) -> CommonMarketSeries:
    """Aggregate governed membership before Alpha eligibility or label filtering."""
    closes = np.asarray(adjusted_close, dtype=np.float64)
    if closes.shape != (len(instruments), len(sessions)):
        raise ValueError("Common market Close coordinates do not align")
    if len(set(instruments)) != len(instruments) or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Common market coordinates must be unique and sessions ordered")
    positions = {instrument: index for index, instrument in enumerate(instruments)}
    means = np.full(len(sessions), np.nan)
    breadth = np.full(len(sessions), np.nan)
    counts: list[int] = []
    valid_counts: list[int] = []
    exclusions: list[dict[str, int]] = []
    for day, session in enumerate(sessions):
        members = universe_members.get(session, ())
        if len(set(members)) != len(members) or any(member not in positions for member in members):
            raise ValueError("Common market inputs must cover unique Universe members")
        selected = [
            member
            for member in members
            if industry_code is None or industries.get((session, member)) == industry_code
        ]
        counts.append(len(selected))
        excluded: Counter[str] = Counter()
        returns: list[float] = []
        for member in sorted(selected):
            if day == 0:
                excluded["insufficient_history"] += 1
                continue
            current = closes[positions[member], day]
            previous = closes[positions[member], day - 1]
            if not np.isfinite(current) or current <= 0:
                excluded["invalid_current_close"] += 1
                continue
            if not np.isfinite(previous) or previous <= 0:
                excluded["invalid_previous_close"] += 1
                continue
            with np.errstate(over="ignore", invalid="ignore"):
                change = current / previous - 1
            if not np.isfinite(change):
                excluded["non_finite_return"] += 1
                continue
            returns.append(float(change))
        valid_counts.append(len(returns))
        exclusions.append(dict(excluded))
        if returns:
            # Scaling before summation avoids overflowing a finite arithmetic mean.
            means[day] = sum(value / len(returns) for value in returns)
            breadth[day] = sum(value > 0 for value in returns) / len(returns)
    means.setflags(write=False)
    breadth.setflags(write=False)
    return CommonMarketSeries(means, breadth, tuple(counts), tuple(valid_counts), tuple(exclusions))
