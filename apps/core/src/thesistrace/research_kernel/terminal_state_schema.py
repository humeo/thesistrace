from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from math import isfinite
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from thesistrace.research_kernel.portfolio_weighting import EligibilityReason

StrictNumber = StrictInt | StrictFloat
EligibilityExclusions = dict[EligibilityReason, Annotated[StrictInt, Field(gt=0)]]


class TerminalStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TerminalPosition(TerminalStateModel):
    instrument_id: StrictStr
    execution_shares: StrictInt
    adjusted_units: StrictStr
    last_adjusted_price: StrictStr


class SelectionPhase(TerminalStateModel):
    origin_session: StrictStr
    report_session_count: StrictInt
    selection_interval: StrictInt
    completed_intervals: StrictInt


class TargetSelection(TerminalStateModel):
    signal_session: StrictStr
    selected_instrument_ids: list[StrictStr]
    relative_weights: dict[StrictStr, StrictStr]
    eligibility_exclusions: EligibilityExclusions
    signal_checksum: StrictStr
    contract_checksum: StrictStr

    @model_validator(mode="after")
    def target_weights_match_selection(self) -> TargetSelection:
        selected = self.selected_instrument_ids
        weights = self.relative_weights
        if len(selected) != len(set(selected)) or set(weights) != set(selected):
            raise ValueError("Pending target weights do not match the unique selection")
        try:
            ratios = [Fraction(weight) for weight in weights.values()]
        except (ValueError, ZeroDivisionError):
            raise ValueError("Target weights must be canonical positive ratios") from None
        if any(str(ratio) != weight or not 0 < ratio <= 1
               for weight, ratio in zip(weights.values(), ratios, strict=True)):
            raise ValueError("Target weights must be canonical positive ratios")
        if selected and sum(ratios) != 1:
            raise ValueError("Target weights must sum to one")
        return self


class PendingTarget(TargetSelection):
    decision_session: StrictStr
    mode: Literal["selection", "reduce", "increase"]
    execution: Literal["next_research_session_open"]
    exposure: StrictFloat

    @model_validator(mode="after")
    def exposure_is_valid(self) -> PendingTarget:
        if not isfinite(self.exposure) or not 0 <= self.exposure <= 1:
            raise ValueError("Pending Exposure must be finite and between zero and one")
        return self


class ValuationEvent(TerminalStateModel):
    session: StrictStr
    instrument_id: StrictStr
    type: StrictStr


class LastDailyObservation(TerminalStateModel):
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


class StrategyMetricState(TerminalStateModel):
    contract: StrictStr
    entry_session: StrictStr | None
    entry_session_ordinal: StrictInt | None
    initial_cash_cny: StrictStr
    first_gross_nav: StrictStr
    first_net_nav: StrictStr
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


class TerminalStrategyStateValue(TerminalStateModel):
    session: StrictStr
    gross_cash: StrictStr
    net_cash: StrictStr
    gross_nav: StrictStr
    net_nav: StrictStr
    cumulative_transaction_cost: StrictStr
    positions: list[TerminalPosition]
    selection_phase: SelectionPhase
    target_selection: TargetSelection
    target_exposure: StrictFloat
    pending_target: PendingTarget | None
    last_daily_observation: LastDailyObservation
    metric_state: StrategyMetricState

    @model_validator(mode="after")
    def continuation_sessions_must_match_boundary(self) -> TerminalStrategyStateValue:
        if not isfinite(self.target_exposure) or not 0 <= self.target_exposure <= 1:
            raise ValueError("Target Exposure must be finite and between zero and one")
        if self.target_selection.signal_session > self.session:
            raise ValueError("Retained Selection cannot come from the future")
        if self.pending_target is not None and (
            self.pending_target.exposure != self.target_exposure
            or self.pending_target.model_dump(
                exclude={"execution", "exposure", "decision_session", "mode"},
            )
            != self.target_selection.model_dump()
        ):
            raise ValueError("Pending target differs from the decided Selection and Exposure")
        if (
            self.last_daily_observation.session != self.session
            or self.metric_state.last_session != self.session
            or (
                self.pending_target is not None
                and self.pending_target.decision_session != self.session
            )
        ):
            raise ValueError("Terminal continuation sessions do not match")
        return self


LAST_DAILY_OBSERVATION_KEYS = frozenset(LastDailyObservation.model_fields)
METRIC_STATE_KEYS = frozenset(StrategyMetricState.model_fields)
