"""Structured report requirements; dates come from disclosure_date, never titles."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

from thesistrace.publication.serialization import canonical_json_bytes

# Published coverage records retain their original source provenance permanently.
DISCOVERY_COVERAGE_KINDS = frozenset(
    {"financial-disclosure-observation-range", "financial-announcement-observation-range"}
)


@dataclass(frozen=True)
class FinancialDisclosure:
    ts_code: str
    report_period: str
    actual_date: str


@dataclass(frozen=True)
class FinancialDiscoveryGap:
    report_period: str
    failure_code: str


@dataclass(frozen=True)
class FinancialDisclosureDiscovery:
    start_date: str
    end_date: str
    completed_periods: tuple[str, ...]
    reports: tuple[FinancialDisclosure, ...]
    gaps: tuple[FinancialDiscoveryGap, ...]
    source_lineage_sha256: str

    def evidence(self) -> dict[str, object]:
        return asdict(self)


class FinancialDisclosureSource(Protocol):
    def discover(
        self,
        *,
        start_date: str,
        end_date: str,
        allowed_ts_codes: set[str] | frozenset[str],
    ) -> FinancialDisclosureDiscovery: ...


def disclosure_periods(start_date: str, end_date: str) -> tuple[str, ...]:
    """Three closed quarters, plus any quarters crossed during a catch-up."""
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start > end:
        raise ValueError("Invalid disclosure interval")
    periods = [
        date(year, month, day)
        for year in range(start.year - 1, end.year + 1)
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
        if date(year, month, day) <= end
    ]
    lower = min(start, periods[-3])
    return tuple(period.isoformat() for period in periods if period >= lower)


def discovery_lineage(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
