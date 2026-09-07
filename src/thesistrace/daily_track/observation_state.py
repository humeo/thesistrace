from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, localcontext

from pydantic import BaseModel, ConfigDict, model_validator

from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


class TrackingObservationState(BaseModel):
    """Tracking-only metric prefix, excluding the replaceable boundary observation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    boundary_session: str
    prefix_session: str | None
    peak_net_nav: str
    maximum_drawdown: str

    @model_validator(mode="after")
    def validate_prefix(self) -> "TrackingObservationState":
        date.fromisoformat(self.boundary_session)
        if self.prefix_session is not None:
            date.fromisoformat(self.prefix_session)
            if self.prefix_session >= self.boundary_session:
                raise ValueError("Tracking prefix must precede its boundary")
        peak = Decimal(self.peak_net_nav)
        loss = Decimal(self.maximum_drawdown)
        if not peak.is_finite() or peak <= 0 or not loss.is_finite() or not 0 <= loss < 1:
            raise ValueError("Tracking observation metric state is invalid")
        return self


def initial_tracking_observation_state(session: str, net_nav: str) -> TrackingObservationState:
    return TrackingObservationState(
        boundary_session=session, prefix_session=None,
        peak_net_nav=net_nav, maximum_drawdown="0",
    )


def advance_tracking_observation_state(
    prior: TrackingObservationState,
    observations: Sequence[Mapping[str, object]],
) -> TrackingObservationState:
    if not observations or str(observations[0]["session"]) != prior.boundary_session:
        raise ValueError("Tracking observations do not start at the prior boundary")
    with localcontext(ACCOUNTING_CONTEXT):
        peak = Decimal(prior.peak_net_nav)
        loss = Decimal(prior.maximum_drawdown)
        prefix = prior.prefix_session
        previous = None
        for index, row in enumerate(observations):
            session = str(row["session"])
            date.fromisoformat(session)
            nav = Decimal(str(row["net_nav"]))
            if not nav.is_finite() or nav <= 0 or (previous is not None and session <= previous):
                raise ValueError("Tracking observations have invalid values or ordering")
            previous = session
            if index < len(observations) - 1:
                peak = max(peak, nav)
                loss = max(loss, 1 - nav / peak)
                prefix = session
        return TrackingObservationState(
            boundary_session=previous, prefix_session=prefix,
            peak_net_nav=canonical_decimal(peak), maximum_drawdown=canonical_decimal(loss),
        )


def tracking_maximum_drawdown(state: TrackingObservationState, boundary_nav: str) -> Decimal:
    with localcontext(ACCOUNTING_CONTEXT):
        nav = Decimal(boundary_nav)
        if not nav.is_finite() or nav <= 0:
            raise ValueError("Tracking boundary NAV must be positive and finite")
        return max(Decimal(state.maximum_drawdown), 1 - nav / max(Decimal(state.peak_net_nav), nav))
