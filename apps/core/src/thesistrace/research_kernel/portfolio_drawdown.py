"""Close risk-cycle state; release requires a fresh portfolio decision."""

from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


class PortfolioDrawdownPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    drawdown_threshold: float = Field(gt=0, le=1, allow_inf_nan=False)
    maximum_stock_exposure: float = Field(ge=0, le=1, allow_inf_nan=False)
    cooldown_sessions: StrictInt = Field(ge=1)


class PortfolioDrawdownState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cycle_started_session: StrictStr
    peak_close_nav_cny: StrictStr = Field(max_length=128)
    triggered_session: StrictStr | None
    triggered_session_number: StrictInt | None = Field(ge=1)


    @model_validator(mode="after")
    def risk_cycle_is_possible(self):
        try:
            peak = Decimal(self.peak_close_nav_cny)
            dates = [self.cycle_started_session]
            if self.triggered_session is not None:
                dates.append(self.triggered_session)
            for session in dates:
                if date.fromisoformat(session).isoformat() != session:
                    raise ValueError("Noncanonical date")
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Invalid drawdown risk cycle") from error
        if (not peak.is_finite() or peak < 0
                or canonical_decimal(peak) != self.peak_close_nav_cny
                or (self.triggered_session is None) != (self.triggered_session_number is None)
                or (self.triggered_session is not None
                    and self.triggered_session < self.cycle_started_session)):
            raise ValueError("Invalid drawdown risk cycle")
        return self

    def validate_boundary(self, *, session, completed_sessions, close_nav):
        if (self.cycle_started_session > session
                or Decimal(self.peak_close_nav_cny) < Decimal(close_nav)
                or (self.triggered_session is not None and self.triggered_session > session)
                or (self.triggered_session_number is not None
                    and self.triggered_session_number > completed_sessions)):
            raise ValueError("Drawdown risk cycle exceeds its checkpoint boundary")


def portfolio_drawdown_decision(*, policy, nav, session, session_number, new_proposal, previous):
    with localcontext(ACCOUNTING_CONTEXT):
        current = Decimal(nav)
        if not current.is_finite() or current < 0:
            raise ValueError("Close Risk NAV must be finite and nonnegative")
        state = (PortfolioDrawdownState.model_validate(previous).model_dump() if previous else {
            "cycle_started_session": session, "peak_close_nav_cny": canonical_decimal(current),
            "triggered_session": None, "triggered_session_number": None,
        })
        peak = max(Decimal(state["peak_close_nav_cny"]), current)
        drawdown = 1 - current / peak if peak > 0 else Decimal(0)
        elapsed = 0
        reason = "observing"
        if state["triggered_session_number"] is not None:
            elapsed = session_number - state["triggered_session_number"]
            if elapsed >= policy.cooldown_sessions and new_proposal:
                state = {"cycle_started_session": session,
                         "peak_close_nav_cny": canonical_decimal(current),
                         "triggered_session": None, "triggered_session_number": None}
                peak, drawdown, reason = current, Decimal(0), "new_portfolio_recovery"
            else:
                reason = ("awaiting_new_portfolio" if elapsed >= policy.cooldown_sessions
                          else "cooldown")
        elif drawdown >= Decimal(str(policy.drawdown_threshold)):
            state["triggered_session"] = session
            state["triggered_session_number"] = session_number
            reason = "threshold_reached"
        state["peak_close_nav_cny"] = canonical_decimal(peak)
        cap = (policy.maximum_stock_exposure
               if state["triggered_session_number"] is not None else None)
        observation = {
            "reason": "portfolio_drawdown", "status": reason,
            "cycle_started_session": state["cycle_started_session"],
            "peak_close_nav_cny": state["peak_close_nav_cny"],
            "close_risk_nav_cny": canonical_decimal(current),
            "drawdown": canonical_decimal(drawdown),
            "drawdown_threshold": policy.drawdown_threshold,
            "maximum_stock_exposure": cap, "cooldown_sessions": policy.cooldown_sessions,
            "completed_cooldown_sessions": elapsed,
            "triggered_session": state["triggered_session"],
        }
        return state, cap, observation
