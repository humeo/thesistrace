"""Typed execution evidence from the shared Strategy account transition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictInt, StrictStr, model_validator

from thesistrace.research_kernel.terminal_state_schema import (
    PendingTarget,
    TerminalStateModel,
    ValuationEvent,
)


def _finite_decimal(value: str) -> str:
    try:
        valid = Decimal(value).is_finite()
    except InvalidOperation:
        valid = False
    if not valid:
        raise ValueError("Execution evidence requires a finite decimal")
    return value


DecimalEvidence = Annotated[StrictStr, AfterValidator(_finite_decimal)]
Session = StrictStr
PositiveShares = Annotated[StrictInt, Field(gt=0)]
RejectionReason = Literal["suspension", "data_unavailable", "upper_limit_buy", "lower_limit_sell"]
StrategyEventSection = Literal[
    "strategy_targets", "strategy_orders", "strategy_child_orders", "strategy_fills",
    "strategy_adjustments", "strategy_execution_constraints",
]


class StrategyTargetEvent(PendingTarget):
    target_id: StrictStr
    decision_session: Session


class TradeEvent(TerminalStateModel):
    target_id: StrictStr
    decision_session: Session
    session: Session
    instrument_id: StrictStr
    side: Literal["buy", "sell"]
    reason: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    order_id: StrictStr

    @model_validator(mode="after")
    def decision_precedes_execution(self) -> TradeEvent:
        if self.decision_session >= self.session:
            raise ValueError("Trade execution must follow its decision Session")
        return self


class StrategyOrderEvent(TradeEvent):
    intended_value: DecimalEvidence
    unrounded_quantity: Annotated[StrictInt, Field(ge=0)] | None
    legal_quantity: PositiveShares | None
    rejection_reason: RejectionReason | None

    @model_validator(mode="after")
    def unavailable_open_has_no_quantity(self) -> StrategyOrderEvent:
        if (self.unrounded_quantity is None) != (self.legal_quantity is None):
            raise ValueError("Unknown order quantity requires both coordinates absent")
        if self.legal_quantity is None and self.rejection_reason not in {
            "suspension", "data_unavailable",
        }:
            raise ValueError("Only an unavailable Open can leave order quantity unknown")
        return self


class StrategyChildOrderEvent(TradeEvent):
    child_order_id: StrictStr
    quantity: PositiveShares


class StrategyFillEvent(StrategyChildOrderEvent):
    fill_id: StrictStr
    raw_open: DecimalEvidence
    adjusted_open: DecimalEvidence
    raw_notional: DecimalEvidence
    cost: DecimalEvidence
    research_settlement: DecimalEvidence
    gross_cash_delta: DecimalEvidence
    net_cash_delta: DecimalEvidence
    cash_rounding_delta: DecimalEvidence
    execution_shares_delta: StrictInt
    adjusted_units_delta: DecimalEvidence

    @model_validator(mode="after")
    def quantity_and_settlement_direction(self) -> StrategyFillEvent:
        direction = 1 if self.side == "buy" else -1
        if self.execution_shares_delta != direction * self.quantity:
            raise ValueError("Fill execution share delta differs from its direction")
        if any(Decimal(value) <= 0 for value in (
            self.raw_open, self.adjusted_open, self.raw_notional, self.research_settlement,
        )) or Decimal(self.cost) < 0:
            raise ValueError("Fill amounts are invalid")
        settlement = Decimal(self.research_settlement)
        expected_cash = settlement.copy_negate() if direction == 1 else settlement
        if Decimal(self.gross_cash_delta) != expected_cash:
            raise ValueError("Fill settlement differs from gross cash mutation")
        if direction * Decimal(self.adjusted_units_delta) <= 0:
            raise ValueError("Fill holding mutation differs from its direction")
        return self


class StrategyAdjustmentEvent(ValuationEvent):
    session: Session
    adjusted_units_delta: DecimalEvidence
    net_cash_delta: DecimalEvidence
    gross_cash_delta: DecimalEvidence
    valuation_delta: DecimalEvidence
    last_adjusted_price: DecimalEvidence


class StrategyExecutionConstraintEvent(TerminalStateModel):
    constraint_id: StrictStr
    target_id: StrictStr
    decision_session: Session
    session: Session
    instrument_id: StrictStr
    side: Literal["buy", "sell"]
    mode: Literal["rebalance", "reduce", "increase", "local"]
    decision_reason: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    reason: Literal["below_board_lot", "insufficient_cash"]
    intended_value: DecimalEvidence
    unrounded_quantity: Annotated[StrictInt, Field(ge=0)]
    legal_quantity: Annotated[StrictInt, Field(ge=0)]
    submitted_quantity: Annotated[StrictInt, Field(ge=0)]
    available_cash_cny: DecimalEvidence
    order_id: StrictStr | None

    @model_validator(mode="after")
    def constrained_quantity_matches_reason(self) -> StrategyExecutionConstraintEvent:
        if self.decision_session >= self.session:
            raise ValueError("Execution constraint must follow its decision Session")
        if not self.submitted_quantity <= self.legal_quantity <= self.unrounded_quantity:
            raise ValueError("Execution constraint quantities must not increase")
        if (self.order_id is None) != (self.submitted_quantity == 0):
            raise ValueError("Only a submitted constraint can reference an order")
        if Decimal(self.intended_value) <= 0 or Decimal(self.available_cash_cny) < 0:
            raise ValueError("Execution constraint amounts are invalid")
        if self.reason == "below_board_lot":
            if self.legal_quantity != 0:
                raise ValueError("Below-lot constraint cannot submit an order")
        elif self.side != "buy" or self.submitted_quantity >= self.legal_quantity:
            raise ValueError("Cash constraint must reduce a legal buy quantity")
        return self


EVENT_MODELS = {
    "strategy_targets": StrategyTargetEvent,
    "strategy_orders": StrategyOrderEvent,
    "strategy_child_orders": StrategyChildOrderEvent,
    "strategy_fills": StrategyFillEvent,
    "strategy_adjustments": StrategyAdjustmentEvent,
    "strategy_execution_constraints": StrategyExecutionConstraintEvent,
}
EVENT_ID_FIELDS = {
    "strategy_targets": "target_id", "strategy_orders": "order_id",
    "strategy_child_orders": "child_order_id", "strategy_fills": "fill_id",
    "strategy_adjustments": "adjustment_id",
    "strategy_execution_constraints": "constraint_id",
}


def strategy_event_rows(
    strategy: Mapping[str, object], *, sessions: Sequence[str],
) -> dict[str, list[dict[str, object]]]:
    """Select this completed segment only; never reconstruct absent historical trades."""
    covered = set(sessions)
    candidates = {
        "strategy_targets": strategy["target_events"],
        "strategy_orders": strategy["orders"],
        "strategy_child_orders": strategy["child_orders"],
        "strategy_fills": strategy["fills"],
        "strategy_execution_constraints": strategy["execution_constraints"],
        "strategy_adjustments": [
            event for day in strategy["daily"] if day["session"] in covered
            for event in day["valuation_events"]
        ],
    }
    result = {}
    for section, rows in candidates.items():
        session_key = "decision_session" if section == "strategy_targets" else "session"
        model = EVENT_MODELS[section]
        selected = [model.model_validate(row).model_dump(mode="json") for row in rows
                    if row[session_key] in covered]
        id_key = EVENT_ID_FIELDS[section]
        if len({row[id_key] for row in selected}) != len(selected):
            raise ValueError("Duplicate logical Strategy event in segment")
        result[section] = sorted(selected, key=lambda row: (row[session_key], row[id_key]))
    return result
