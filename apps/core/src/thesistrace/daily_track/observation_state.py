from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, localcontext

from pydantic import BaseModel, ConfigDict, model_validator

from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


class TrackingObservationState(BaseModel):
    """Tracking metrics through the last completed, immutable observation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    boundary_session: str
    peak_net_nav: str
    maximum_drawdown: str

    @model_validator(mode="after")
    def validate_prefix(self) -> "TrackingObservationState":
        date.fromisoformat(self.boundary_session)
        peak = Decimal(self.peak_net_nav)
        loss = Decimal(self.maximum_drawdown)
        if not peak.is_finite() or peak <= 0 or not loss.is_finite() or not 0 <= loss < 1:
            raise ValueError("Tracking observation metric state is invalid")
        return self


def initial_tracking_observation_state(session: str, net_nav: str) -> TrackingObservationState:
    return TrackingObservationState(
        boundary_session=session,
        peak_net_nav=net_nav, maximum_drawdown="0",
    )


def advance_tracking_observation_state(
    prior: TrackingObservationState,
    observations: Sequence[Mapping[str, object]],
) -> TrackingObservationState:
    if not observations or str(observations[0]["session"]) <= prior.boundary_session:
        raise ValueError("Tracking observations must follow the completed boundary")
    with localcontext(ACCOUNTING_CONTEXT):
        peak = Decimal(prior.peak_net_nav)
        loss = Decimal(prior.maximum_drawdown)
        previous = prior.boundary_session
        for row in observations:
            session = str(row["session"])
            date.fromisoformat(session)
            nav = Decimal(str(row["net_nav"]))
            if not nav.is_finite() or nav <= 0 or (previous is not None and session <= previous):
                raise ValueError("Tracking observations have invalid values or ordering")
            previous = session
            peak = max(peak, nav)
            loss = max(loss, 1 - nav / peak)
        return TrackingObservationState(
            boundary_session=previous,
            peak_net_nav=canonical_decimal(peak), maximum_drawdown=canonical_decimal(loss),
        )


def tracking_maximum_drawdown(state: TrackingObservationState, boundary_nav: str) -> Decimal:
    with localcontext(ACCOUNTING_CONTEXT):
        nav = Decimal(boundary_nav)
        if not nav.is_finite() or nav <= 0:
            raise ValueError("Tracking boundary NAV must be positive and finite")
        return max(Decimal(state.maximum_drawdown), 1 - nav / max(Decimal(state.peak_net_nav), nav))
