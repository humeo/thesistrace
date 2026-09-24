from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

StrictNumber = StrictInt | StrictFloat
OptionalNumber = StrictNumber | None


class DurableResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FactorCorrelation(DurableResultModel):
    icir: OptionalNumber
    mean: OptionalNumber
    positive_fraction: OptionalNumber
    sample_deviation: OptionalNumber
    valid_session_count: StrictInt


class FactorQuantileReturns(DurableResultModel):
    q1: OptionalNumber
    q2: OptionalNumber
    q3: OptionalNumber
    q4: OptionalNumber
    q5: OptionalNumber


class FactorMetrics(DurableResultModel):
    ic: FactorCorrelation
    quantile_returns: FactorQuantileReturns
    rank_ic: FactorCorrelation
    top_bottom_return: OptionalNumber


class FactorCoverage(DurableResultModel):
    signal_session_count: StrictInt
    ic_valid_session_count: StrictInt
    rank_ic_valid_session_count: StrictInt
    quantile_valid_session_count: StrictInt


class FactorHorizon(DurableResultModel):
    horizon: Literal[1, 5, 20]
    alpha_checksum: StrictStr
    label_checksum: StrictStr
    source_checksum: StrictStr
    summary: FactorMetrics
    coverage: FactorCoverage


class FactorHorizons(DurableResultModel):
    one: FactorHorizon = Field(alias="1")
    five: FactorHorizon = Field(alias="5")
    twenty: FactorHorizon = Field(alias="20")

    @model_validator(mode="after")
    def validate_horizon_identity(self) -> FactorHorizons:
        if (self.one.horizon, self.five.horizon, self.twenty.horizon) != (1, 5, 20):
            raise ValueError("Factor horizon identity is invalid")
        return self


class FactorSummaryValue(DurableResultModel):
    horizons: FactorHorizons


class CashRatioMaximum(DurableResultModel):
    session: StrictStr
    value: StrictNumber


class CashRatio(DurableResultModel):
    ending: StrictNumber
    maximum: CashRatioMaximum
    mean: StrictNumber


class HoldingsCount(DurableResultModel):
    ending: StrictInt
    maximum: StrictInt
    mean: StrictNumber
    minimum: StrictInt


class MarketRejections(DurableResultModel):
    lower_limit_sell: StrictInt
    suspension: StrictInt
    upper_limit_buy: StrictInt


class MaximumDrawdown(DurableResultModel):
    peak_session: StrictStr
    recovery_session: StrictStr | None
    trough_session: StrictStr
    unrecovered: StrictBool
    value: StrictNumber


class MaximumWeightPoint(DurableResultModel):
    session: StrictStr
    value: StrictNumber


class MaximumSingleNameWeight(DurableResultModel):
    ending: StrictNumber
    period_maximum: MaximumWeightPoint


class TransactionCosts(DurableResultModel):
    cumulative_amount: StrictNumber
    ratio: StrictNumber
    return_drag: StrictNumber


class Turnover(DurableResultModel):
    annualized: OptionalNumber
    average_rebalance: OptionalNumber


class StrategyMetrics(DurableResultModel):
    annualized_volatility: OptionalNumber
    calmar: OptionalNumber
    cash_ratio: CashRatio
    gross_cagr: OptionalNumber
    gross_cumulative_return: OptionalNumber
    holdings_count: HoldingsCount
    market_rejections: MarketRejections
    maximum_drawdown: MaximumDrawdown
    maximum_single_name_weight: MaximumSingleNameWeight
    net_cagr: OptionalNumber
    net_cumulative_return: OptionalNumber
    risk_free_rate: OptionalNumber
    sharpe: OptionalNumber
    transaction_costs: TransactionCosts
    turnover: Turnover


class StrategySummaryValue(DurableResultModel):
    alpha_checksum: StrictStr | None
    entry_session: StrictStr | None
    initial_cash_cny: StrictStr
    source_checksum: StrictStr
    metrics: StrategyMetrics


class StrategyDailyObservation(DurableResultModel):
    session: StrictStr
    gross_nav: StrictStr
    net_nav: StrictStr
    close_risk_nav_cny: StrictStr
    net_cash: StrictStr
    transaction_cost_cny: StrictStr
    holdings_count: StrictInt
    maximum_single_name_weight: StrictNumber
    upper_limit_buy_rejections: StrictInt
    lower_limit_sell_rejections: StrictInt
    suspension_rejections: StrictInt


class StrategyDailyObservationsValue(RootModel[list[StrategyDailyObservation]]):
    model_config = ConfigDict(frozen=True, strict=True)

    @model_validator(mode="after")
    def validate_positive_ordered_sessions(self) -> StrategyDailyObservationsValue:
        sessions = [row.session for row in self.root]
        if not sessions or sessions != sorted(set(sessions)):
            raise ValueError("Strategy Daily Observation sessions are invalid")
        return self


STRATEGY_METRIC_KEYS = frozenset(StrategyMetrics.model_fields)


class FactorPeriodCoverage(FactorCoverage):
    first_signal_session: StrictStr
    last_signal_session: StrictStr
    label_evaluable_session_count: StrictInt
    first_evaluable_signal_session: StrictStr | None
    last_evaluable_signal_session: StrictStr | None
    right_censored_session_count: StrictInt
    sample_available_session_count: StrictInt
    alpha_candidate_count: StrictInt
    alpha_sample_count: StrictInt
    sample_count: StrictInt
    alpha_exclusions: dict[StrictStr, StrictInt]
    label_exclusions: dict[StrictStr, StrictInt]


class FactorPeriodStatistic(DurableResultModel):
    horizon: Literal[1, 5, 20]
    granularity: Literal["all", "month", "year"]
    period: StrictStr
    summary: FactorMetrics
    coverage: FactorPeriodCoverage

    @model_validator(mode="after")
    def validate_period_evidence(self) -> FactorPeriodStatistic:
        coverage = self.coverage
        for value in coverage.model_dump().values():
            if isinstance(value, int) and value < 0:
                raise ValueError("Factor period count is negative")
        if (
            coverage.label_evaluable_session_count + coverage.right_censored_session_count
            != coverage.signal_session_count
            or not 0
            <= coverage.sample_available_session_count
            <= coverage.label_evaluable_session_count
            or coverage.ic_valid_session_count > coverage.sample_available_session_count
            or coverage.rank_ic_valid_session_count > coverage.sample_available_session_count
            or coverage.quantile_valid_session_count > coverage.sample_available_session_count
            or coverage.alpha_candidate_count
            != coverage.alpha_sample_count + sum(coverage.alpha_exclusions.values())
            or coverage.alpha_sample_count
            != coverage.sample_count + sum(coverage.label_exclusions.values())
            or any(
                count <= 0
                for count in (
                    *coverage.alpha_exclusions.values(),
                    *coverage.label_exclusions.values(),
                )
            )
        ):
            raise ValueError("Factor period coverage is inconsistent")
        first, last = coverage.first_signal_session, coverage.last_signal_session
        if (
            date.fromisoformat(first).isoformat() != first
            or date.fromisoformat(last).isoformat() != last
            or first > last
        ):
            raise ValueError("Factor period signal range is invalid")
        if self.granularity == "all":
            valid_period = self.period == "all"
        else:
            width = 7 if self.granularity == "month" else 4
            valid_period = first[:width] == self.period == last[:width]
        if not valid_period:
            raise ValueError("Factor period must follow signal dates")
        evaluable = coverage.first_evaluable_signal_session, coverage.last_evaluable_signal_session
        if coverage.label_evaluable_session_count == 0:
            if evaluable != (None, None):
                raise ValueError("Unevaluable period cannot have an evaluation range")
        elif (
            any(value is None for value in evaluable)
            or not first <= evaluable[0] <= evaluable[1] <= last
        ):
            raise ValueError("Factor period evaluation range is invalid")
        if (
            self.summary.ic.valid_session_count != coverage.ic_valid_session_count
            or self.summary.rank_ic.valid_session_count != coverage.rank_ic_valid_session_count
        ):
            raise ValueError("Factor period metric coverage is inconsistent")
        return self
