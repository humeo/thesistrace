"""Read-only daily observation projection from a published account boundary."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext

from thesistrace.daily_track.models import DailyTrackObservation, DailyTrackOriginAccount
from thesistrace.research_kernel.numeric import ACCOUNTING_CONTEXT, canonical_decimal


def project_daily_observation(
    *,
    origin: DailyTrackOriginAccount,
    current: DailyTrackOriginAccount,
    observations: Sequence[Mapping[str, object]],
) -> DailyTrackObservation:
    """Keep the inception denominator even when the chart's retained window rolls."""
    with localcontext(ACCOUNTING_CONTEXT):
        origin_nav = Decimal(origin.net_nav)
        current_nav = Decimal(current.net_nav)
        if origin_nav <= 0 or current_nav <= 0:
            raise ValueError("Daily observation requires positive account values")
        if current.session < origin.session:
            raise ValueError("Daily observation precedes its Tracking Origin")
        points = []
        peak_nav = origin_nav
        maximum_drawdown = Decimal(0)
        for row in observations:
            session = str(row["session"])
            if not origin.session <= session <= current.session:
                continue
            nav = Decimal(str(row["net_nav"]))
            peak_nav = max(peak_nav, nav)
            maximum_drawdown = max(maximum_drawdown, 1 - nav / peak_nav)
            points.append({"session": session, "net_return": float(nav / origin_nav - 1)})
        holdings = []
        for position in current.positions:
            # Execution shares and adjusted units are different coordinates.
            market_value = Decimal(position.adjusted_units) * Decimal(position.last_adjusted_price)
            holdings.append(
                {
                    "instrument_id": position.instrument_id,
                    "shares": position.execution_shares,
                    "market_value_cny": canonical_decimal(market_value),
                    "weight": float(market_value / current_nav),
                }
            )
        phase = current.rebalance_phase
        signal_offset = (phase.report_session_count - 1) % phase.rebalance_interval
        return DailyTrackObservation.model_validate(
            {
                "session": current.session,
                "net_asset_value_cny": current.net_nav,
                "cash_cny": current.net_cash,
                "net_change_cny": canonical_decimal(current_nav - origin_nav),
                "net_return": float(current_nav / origin_nav - 1),
                "maximum_drawdown": float(maximum_drawdown),
                "transaction_cost_cny": canonical_decimal(
                    Decimal(current.cumulative_transaction_cost)
                    - Decimal(origin.cumulative_transaction_cost)
                ),
                "session_count": phase.report_session_count
                - origin.rebalance_phase.report_session_count,
                "holdings": sorted(
                    holdings, key=lambda row: (-row["weight"], row["instrument_id"])
                ),
                "rebalance_interval": phase.rebalance_interval,
                "pending_signal_session": (
                    current.pending_signal.signal_session if current.pending_signal else None
                ),
                "sessions_until_next_signal": (
                    phase.rebalance_interval - signal_offset if signal_offset else 0
                ),
                "returns": points[-504:],
            }
        )
