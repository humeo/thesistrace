from __future__ import annotations

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
    alpha_checksum: StrictStr
    entry_session: StrictStr
    initial_cash_cny: StrictStr
    source_checksum: StrictStr
    metrics: StrategyMetrics


class StrategyDailyObservation(DurableResultModel):
    session: StrictStr
    gross_nav: StrictStr
    net_nav: StrictStr
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
