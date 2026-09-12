"""Actual post-execution Open holdings, separate from permanent account state."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, Field, StrictInt, StrictStr, model_validator

from thesistrace.research_kernel.terminal_state_schema import TerminalStateModel


def _nonnegative_decimal(value: str) -> str:
    try:
        number = Decimal(value)
        valid = number.is_finite() and number >= 0
    except InvalidOperation:
        valid = False
    if not valid:
        raise ValueError("Holding observation requires a finite nonnegative decimal")
    return value


HoldingDecimal = Annotated[StrictStr, AfterValidator(_nonnegative_decimal)]


class DailyHoldingPosition(TerminalStateModel):
    instrument_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    execution_shares: Annotated[StrictInt, Field(gt=0)]
    adjusted_units: HoldingDecimal
    adjusted_mark: HoldingDecimal
    market_value_cny: HoldingDecimal
    weight: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class DailyHoldingSession(TerminalStateModel):
    session: Annotated[StrictStr, Field(min_length=1)]
    positions: list[DailyHoldingPosition]

    @model_validator(mode="after")
    def ordered_unique_positions(self) -> DailyHoldingSession:
        names = [position.instrument_id for position in self.positions]
        if names != sorted(set(names)):
            raise ValueError("Daily holdings must be ordered and unique")
        return self


class DailyHoldingRow(DailyHoldingPosition):
    session: Annotated[StrictStr, Field(min_length=1)]


def holding_rows(observations: list[dict[str, object]]) -> tuple[list[str], list[dict]]:
    """Flatten one bounded segment while retaining coverage for empty Sessions."""
    validated = [DailyHoldingSession.model_validate(item) for item in observations]
    sessions = [item.session for item in validated]
    if sessions != sorted(set(sessions)):
        raise ValueError("Daily holding Sessions must be ordered and unique")
    return sessions, [
        {"session": item.session, **position.model_dump(mode="json")}
        for item in validated for position in item.positions
    ]
