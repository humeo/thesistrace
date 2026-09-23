"""Observed Framework stage outputs, separate from resumable decision state."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from thesistrace.research_kernel.terminal_state_schema import (
    ActiveStrategySignal,
    PendingTarget,
    TerminalStateModel,
)

Reason = Annotated[StrictStr, Field(min_length=1, max_length=512)]


class UniverseEvidence(TerminalStateModel):
    instrument_ids: list[StrictStr]
    updated: StrictBool
    reason: Reason | None


class AlphaValueEvidence(TerminalStateModel):
    instrument_id: StrictStr
    value: StrictFloat = Field(allow_inf_nan=False)


class FormulaEvidence(TerminalStateModel):
    kind: Literal["formula"] = "formula"
    values: list[AlphaValueEvidence]


class SignalEvidence(TerminalStateModel):
    kind: Literal["signals"] = "signals"
    signals: list[ActiveStrategySignal]
    updated: StrictBool
    reason: Reason | None
    expired_signals: list[StrictStr]
    removed_signals: list[StrictStr]


class PositionLimitEvidence(TerminalStateModel):
    mode: Literal["limit_positions"]
    reason: Reason
    position_limits: dict[StrictStr, Annotated[StrictInt, Field(ge=0)]]


class StopLossObservation(TerminalStateModel):
    reason: Literal["stop_loss"]
    instrument_id: StrictStr
    remaining_acquisition_cost_cny: StrictStr
    close_market_value_cny: StrictStr
    holding_return: StrictStr
    stop_loss_threshold: StrictStr
    execution_shares: Annotated[StrictInt, Field(gt=0)]
    holding_age: Annotated[StrictInt, Field(ge=1)]


class HoldingExpiryObservation(TerminalStateModel):
    reason: Literal["maximum_holding_period"]
    instrument_id: StrictStr
    execution_shares: Annotated[StrictInt, Field(gt=0)]
    holding_age: Annotated[StrictInt, Field(ge=1)]
    maximum_holding_sessions: Annotated[StrictInt, Field(ge=1)]


class HoldingRiskEvidence(TerminalStateModel):
    mode: Literal["holding_risk"] = "holding_risk"
    reason: Reason
    position_limits: dict[StrictStr, Annotated[StrictInt, Field(ge=0)]]
    observations: list[Annotated[
        StopLossObservation | HoldingExpiryObservation, Field(discriminator="reason"),
    ]] = Field(min_length=1, max_length=6000)


class ReplacementEvidence(TerminalStateModel):
    mode: Literal["replace"]
    reason: Reason
    target: PendingTarget | None


class HoldingRetentionEvidence(TerminalStateModel):
    reason: Literal["minimum_holding_period"] = "minimum_holding_period"
    instrument_id: StrictStr
    execution_shares: Annotated[StrictInt, Field(gt=0)]
    holding_age: Annotated[StrictInt, Field(ge=1)]
    minimum_holding_sessions: Annotated[StrictInt, Field(ge=1)]


class FrameworkEvidence(TerminalStateModel):
    """Null proposal means NoUpdate; null replacement target means explicit cancellation."""

    modules: dict[StrictStr, StrictStr]
    universe: UniverseEvidence
    alpha: Annotated[FormulaEvidence | SignalEvidence, Field(discriminator="kind")]
    proposal: PendingTarget | None
    portfolio_retentions: list[HoldingRetentionEvidence] = Field(default_factory=list)
    risk_adjustment: Annotated[
        PositionLimitEvidence | ReplacementEvidence | HoldingRiskEvidence,
        Field(discriminator="mode"),
    ] | None

    @model_validator(mode="after")
    def complete_stage_identity(self):
        if set(self.modules) != {
            "universe_selection", "alpha", "portfolio_construction", "risk_management",
        }:
            raise ValueError("Framework evidence requires all four module identities")
        return self

    @property
    def instrument_ids(self) -> frozenset[str]:
        result = set(self.universe.instrument_ids)
        if isinstance(self.alpha, SignalEvidence):
            result.update(row.instrument_id for row in self.alpha.signals)
            result.update(self.alpha.expired_signals)
            result.update(self.alpha.removed_signals)
        else:
            result.update(row.instrument_id for row in self.alpha.values)
        if self.proposal:
            result.update(self.proposal.instrument_ids)
        if isinstance(self.risk_adjustment, (PositionLimitEvidence, HoldingRiskEvidence)):
            result.update(self.risk_adjustment.position_limits)
        elif isinstance(self.risk_adjustment, ReplacementEvidence) and self.risk_adjustment.target:
            result.update(self.risk_adjustment.target.instrument_ids)
        return frozenset(result)
