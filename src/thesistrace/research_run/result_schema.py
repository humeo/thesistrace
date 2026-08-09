from __future__ import annotations

from collections.abc import Mapping
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
    annualized_excess_return: OptionalNumber
    annualized_volatility: OptionalNumber
    benchmark_cagr: OptionalNumber
    benchmark_cumulative_return: OptionalNumber
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


class StrategyBenchmark(DurableResultModel):
    universe: StrictStr
    methodology: Literal["selected_universe_equal_weight"]


class StrategySummaryValue(DurableResultModel):
    alpha_checksum: StrictStr
    initial_cash_cny: StrictStr
    source_checksum: StrictStr
    benchmark: StrategyBenchmark
    metrics: StrategyMetrics


class StrategyDailyObservation(DurableResultModel):
    session: StrictStr
    gross_nav: StrictStr
    net_nav: StrictStr
    benchmark_nav: StrictStr
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


class TerminalPosition(DurableResultModel):
    instrument_id: StrictStr
    execution_shares: StrictInt
    adjusted_units: StrictStr
    last_adjusted_price: StrictStr


class RebalancePhase(DurableResultModel):
    origin_session: StrictStr
    report_session_count: StrictInt
    rebalance_interval: StrictInt
    completed_intervals: StrictInt


class PendingSignal(DurableResultModel):
    signal_session: StrictStr
    execution: Literal["next_research_session_open"]


class ValuationEvent(DurableResultModel):
    session: StrictStr
    instrument_id: StrictStr
    type: StrictStr


class LastDailyObservation(DurableResultModel):
    benchmark_nav: StrictStr
    benchmark_return: StrictNumber
    cash_ratio: StrictNumber
    cumulative_transaction_cost: StrictStr
    cycle_type: StrictStr
    execution_rounding_residual: StrictStr
    gross_cash: StrictStr
    gross_nav: StrictStr
    gross_return: StrictNumber
    holdings_count: StrictInt
    maximum_single_name_weight: StrictNumber
    net_cash: StrictStr
    net_nav: StrictStr
    net_return: StrictNumber
    pre_trade_gross_nav: StrictStr
    pre_trade_net_nav: StrictStr
    rebalance: StrictBool
    session: StrictStr
    valuation_events: list[ValuationEvent]


OPTIONAL_METRIC_ACCUMULATORS = frozenset(
    {
        "return_sum_numerator",
        "return_sum_denominator",
        "return_square_sum_numerator",
        "return_square_sum_denominator",
        "turnover_sum_numerator",
        "turnover_sum_denominator",
    }
)


class StrategyMetricState(DurableResultModel):
    contract: StrictStr
    first_gross_nav: StrictStr
    first_net_nav: StrictStr
    first_benchmark_nav: StrictStr
    return_count: StrictInt
    peak_net_nav: StrictStr
    peak_session: StrictStr
    worst_drawdown: StrictStr
    worst_peak_nav: StrictStr
    worst_peak_session: StrictStr
    worst_trough_session: StrictStr
    worst_recovery_session: StrictStr | None
    holdings_sum: StrictInt
    holdings_minimum: StrictInt
    holdings_maximum: StrictInt
    weight_maximum: StrictNumber
    weight_maximum_session: StrictStr
    cash_maximum: StrictNumber
    cash_maximum_session: StrictStr
    turnover_count: StrictInt
    session_count: StrictInt
    last_gross_nav: StrictStr
    last_net_nav: StrictStr
    last_benchmark_nav: StrictStr
    last_session: StrictStr
    holdings_ending: StrictInt
    weight_ending: StrictNumber
    cash_sum_numerator: StrictInt
    cash_sum_denominator: StrictInt
    cash_ending: StrictNumber
    return_sum_numerator: StrictInt | None = None
    return_sum_denominator: StrictInt | None = None
    return_square_sum_numerator: StrictInt | None = None
    return_square_sum_denominator: StrictInt | None = None
    turnover_sum_numerator: StrictInt | None = None
    turnover_sum_denominator: StrictInt | None = None
    cumulative_cost: StrictStr
    upper_limit_buy_rejections: StrictInt
    lower_limit_sell_rejections: StrictInt
    suspension_rejections: StrictInt

    @model_validator(mode="before")
    @classmethod
    def optional_accumulators_must_be_absent_or_integers(cls, value: object) -> object:
        if isinstance(value, Mapping) and any(
            name in value and value[name] is None for name in OPTIONAL_METRIC_ACCUMULATORS
        ):
            raise ValueError("Metric accumulators cannot be null")
        return value


class TerminalStrategyStateValue(DurableResultModel):
    session: StrictStr
    gross_cash: StrictStr
    net_cash: StrictStr
    gross_nav: StrictStr
    net_nav: StrictStr
    benchmark_nav: StrictStr
    cumulative_transaction_cost: StrictStr
    positions: list[TerminalPosition]
    rebalance_phase: RebalancePhase
    pending_signal: PendingSignal | None
    last_daily_observation: LastDailyObservation
    metric_state: StrategyMetricState


STRATEGY_METRIC_KEYS = frozenset(StrategyMetrics.model_fields)
LAST_DAILY_OBSERVATION_KEYS = frozenset(LastDailyObservation.model_fields)
METRIC_STATE_KEYS = frozenset(StrategyMetricState.model_fields)
