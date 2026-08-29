from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ComparisonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BenchmarkCoverageView(ComparisonModel):
    start_session: str
    end_session: str


class BenchmarkIdentityView(ComparisonModel):
    id: Literal["csi300-price-index-open"]
    display_name: Literal["沪深300"]
    ts_code: Literal["399300.SZ"]
    kind: Literal["price_index"]
    coordinate: Literal["open"]
    snapshot_sha256: str
    coverage: BenchmarkCoverageView
    published_at: datetime


class StrategyComparisonEntry(ComparisonModel):
    session: str
    benchmark_open_level: str
    initial_cash_cny: str


class StrategyComparisonTerminal(ComparisonModel):
    session: str
    benchmark_open_level: str
    net_nav: str


class StrategyComparisonMetrics(ComparisonModel):
    net_strategy_cumulative_return: float
    benchmark_cumulative_return: float
    net_strategy_cagr: float | None
    benchmark_cagr: float | None
    annualized_excess_return: float | None


class StrategyComparisonCurvePoint(ComparisonModel):
    session: str
    net_strategy_return: float
    benchmark_relative_return: float
    net_excess_nav: float
    net_excess_return: float


class AvailableStrategyComparisonSummary(ComparisonModel):
    status: Literal["available"]
    benchmark: BenchmarkIdentityView
    entry: StrategyComparisonEntry
    terminal: StrategyComparisonTerminal
    metrics: StrategyComparisonMetrics


class AvailableStrategyComparison(AvailableStrategyComparisonSummary):
    curves: list[StrategyComparisonCurvePoint]


class UnavailableStrategyComparison(ComparisonModel):
    status: Literal["unavailable"]
    reason: Literal["benchmark_snapshot_unavailable"]


class InternalAnnualizedExcessRequest(ComparisonModel):
    entry_session: str
    terminal_session: str
    session_interval_count: Annotated[int, Field(strict=True, ge=0)]
    initial_cash_cny: str
    terminal_net_nav: str


class InternalAnnualizedExcessResponse(ComparisonModel):
    annualized_excess_return: float | None


StrategyComparison = Annotated[
    AvailableStrategyComparison | UnavailableStrategyComparison,
    Field(discriminator="status"),
]

StrategyComparisonSummary = Annotated[
    AvailableStrategyComparisonSummary | UnavailableStrategyComparison,
    Field(discriminator="status"),
]


__all__ = (
    "AvailableStrategyComparison",
    "AvailableStrategyComparisonSummary",
    "InternalAnnualizedExcessRequest",
    "InternalAnnualizedExcessResponse",
    "StrategyComparison",
    "StrategyComparisonSummary",
    "UnavailableStrategyComparison",
)
