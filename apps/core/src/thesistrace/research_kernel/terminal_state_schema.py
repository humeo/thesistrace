from __future__ import annotations

import re
from collections.abc import Mapping
from fractions import Fraction
from math import isfinite, lcm
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from thesistrace.research_kernel.portfolio_weighting import EligibilityReason
from thesistrace.research_kernel.strategy_program_runtime import STATE_BYTES, encode_program_json

StrictNumber = StrictInt | StrictFloat
EligibilityExclusions = dict[EligibilityReason, Annotated[StrictInt, Field(gt=0)]]
_TARGET_RATIO = re.compile(r"[1-9][0-9]{0,127}(?:/[1-9][0-9]{0,127})?")


class TerminalStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TerminalPosition(TerminalStateModel):
    instrument_id: StrictStr
    execution_shares: StrictInt
    adjusted_units: StrictStr
    last_adjusted_price: StrictStr


class ResearchPhase(TerminalStateModel):
    origin_session: StrictStr
    report_session_count: Annotated[StrictInt, Field(ge=1)]


class TargetSelection(TerminalStateModel):
    signal_session: StrictStr
    selected_instrument_ids: list[StrictStr]
    relative_weights: dict[StrictStr, StrictStr]
    eligibility_exclusions: EligibilityExclusions
    signal_checksum: StrictStr
    contract_checksum: StrictStr

    @model_validator(mode="after")
    def target_weights_match_selection(self) -> TargetSelection:
        _validate_target_weights(self.selected_instrument_ids, self.relative_weights)
        return self


class FrameworkDecisionState(TerminalStateModel):
    mode: Literal["framework"]
    selection: TargetSelection
    selection_interval: Annotated[StrictInt, Field(ge=1, le=20)]
    exposure: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)


class DirectDecisionState(TerminalStateModel):
    mode: Literal["direct"]
    program_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    state: dict[str, JsonValue]

    @model_validator(mode="after")
    def explicit_state_is_bounded(self):
        encode_program_json(self.state, STATE_BYTES, "state")
        return self


type DecisionState = Annotated[
    FrameworkDecisionState | DirectDecisionState, Field(discriminator="mode"),
]

DECISION_STATE_ADAPTER = TypeAdapter(DecisionState)


def _validate_target_weights(selected: list[str], weights: dict[str, str]) -> None:
    if len(selected) != len(set(selected)) or set(weights) != set(selected):
        raise ValueError("Pending target weights do not match the unique selection")
    # Validate the bounded integer grammar before Fraction sees guest output.
    # Fraction accepts compact exponents that can allocate huge host integers.
    if any(_TARGET_RATIO.fullmatch(weight) is None for weight in weights.values()):
        raise ValueError("Target weights must be canonical positive ratios of at most 128 digits")
    ratios = [Fraction(weight) for weight in weights.values()]
    if any(str(ratio) != weight or not 0 < ratio <= 1
           for weight, ratio in zip(weights.values(), ratios, strict=True)):
        raise ValueError("Target weights must be canonical positive ratios")
    total = Fraction()
    denominator = 1
    for ratio in ratios:
        denominator = lcm(denominator, ratio.denominator)
        if denominator.bit_length() > 4096:
            raise ValueError("Target weights exceed the common denominator size limit")
        total += ratio
    if selected and total != 1:
        raise ValueError("Target weights must sum to one")


class TargetAllocation(TerminalStateModel):
    """Close-frozen weights; rebalance exits omitted names, increase only buys,
    and reduce applies an exposure ceiling proportionally to actual holdings.
    """

    mode: Literal["rebalance", "reduce", "increase"]
    instrument_ids: list[StrictStr]
    relative_weights: dict[StrictStr, StrictStr]
    exposure: StrictFloat

    @model_validator(mode="after")
    def allocation_is_valid(self) -> TargetAllocation:
        _validate_target_weights(self.instrument_ids, self.relative_weights)
        if not isfinite(self.exposure) or not 0 <= self.exposure <= 1:
            raise ValueError("Pending Exposure must be finite and between zero and one")
        return self


class PendingTarget(TerminalStateModel):
    """One final decision, independent of any module's retained selection.

    Without an allocation, unmentioned positions are unchanged. Position limits
    cap execution shares frozen at Close, including any simultaneous allocation.
    NoUpdate is represented by no pending target, never an empty decision.
    """

    decision_session: StrictStr
    execution: Literal["next_research_session_open"]
    contract_checksum: StrictStr
    reason: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    allocation: TargetAllocation | None
    position_limits: dict[StrictStr, Annotated[StrictInt, Field(ge=0)]]

    @model_validator(mode="after")
    def decision_is_not_empty(self) -> PendingTarget:
        if self.allocation is None and not self.position_limits:
            raise ValueError("Empty target must be NoUpdate")
        return self

    @property
    def instrument_ids(self) -> frozenset[str]:
        return frozenset(self.position_limits) | (
            frozenset(self.allocation.instrument_ids) if self.allocation else frozenset()
        )


class ValuationEvent(TerminalStateModel):
    session: StrictStr
    instrument_id: StrictStr
    type: Literal["valuation_carry", "terminal_delisting_writeoff"]
    adjustment_id: StrictStr
    execution_shares_delta: StrictInt
    adjusted_units_delta: StrictStr
    net_cash_delta: StrictStr
    gross_cash_delta: StrictStr
    valuation_delta: StrictStr
    last_adjusted_price: StrictStr


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
    research_phase: ResearchPhase
    contract_checksum: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    decision_state: DecisionState
    pending_target: PendingTarget | None
    last_daily_observation: LastDailyObservation
    metric_state: StrategyMetricState

    @model_validator(mode="after")
    def continuation_sessions_must_match_boundary(self) -> TerminalStrategyStateValue:
        if self.decision_state.mode == "framework":
            selection = self.decision_state.selection
            if selection.signal_session > self.session:
                raise ValueError("Retained Selection cannot come from the future")
            if selection.contract_checksum != self.contract_checksum:
                raise ValueError("Retained Selection differs from the Strategy contract")
        if self.pending_target is not None and (
            self.pending_target.contract_checksum != self.contract_checksum
        ):
            raise ValueError("Pending target differs from the Strategy contract")
        if (
            self.last_daily_observation.session != self.session
            or self.metric_state.last_session != self.session
            or self.research_phase.report_session_count != self.metric_state.session_count
            or (
                self.pending_target is not None
                and self.pending_target.decision_session != self.session
            )
        ):
            raise ValueError("Terminal continuation sessions do not match")
        return self


LAST_DAILY_OBSERVATION_KEYS = frozenset(LastDailyObservation.model_fields)
METRIC_STATE_KEYS = frozenset(StrategyMetricState.model_fields)
