from datetime import date, timedelta
from decimal import Decimal

import pytest

from thesistrace.daily_track.models import DailyTrackOriginAccount
from thesistrace.daily_track.observation import project_daily_observation


def account(
    *,
    session: str = "2026-08-17",
    nav: str = "1000",
    count: int = 11,
    cost: str = "10",
    pending: bool = True,
) -> DailyTrackOriginAccount:
    return DailyTrackOriginAccount.model_validate(
        {
            "session": session,
            "gross_cash": str(Decimal(nav) - 900 + Decimal(cost)),
            "net_cash": str(Decimal(nav) - 900),
            "gross_nav": str(Decimal(nav) + Decimal(cost)),
            "net_nav": nav,
            "cumulative_transaction_cost": cost,
            "positions": [
                {
                    "instrument_id": "000001.SZ",
                    "execution_shares": 100,
                    "adjusted_units": "200",
                    "last_adjusted_price": "4.5",
                }
            ],
            "rebalance_phase": {
                "origin_session": "2026-08-03",
                "report_session_count": count,
                "rebalance_interval": 5,
                "completed_intervals": count - 1,
            },
            "pending_signal": {"signal_session": session, "execution": "next_research_session_open"}
            if pending
            else None,
        }
    )


def test_observation_starts_at_zero_without_reusing_the_seed_backtest_return() -> None:
    origin = account()
    result = project_daily_observation(
        origin=origin,
        current=origin,
        observations=[
            {"session": "2026-08-14", "net_nav": "2000"},
            {"session": "2026-08-17", "net_nav": "1000"},
        ],
    )
    assert result.net_return == 0
    assert result.maximum_drawdown == 0
    assert Decimal(result.net_change_cny) == 0
    assert result.transaction_cost_cny == "0"
    assert result.session_count == 0
    assert [point.model_dump() for point in result.returns] == [
        {"session": "2026-08-17", "net_return": 0.0},
    ]
    assert result.pending_signal_session == "2026-08-17"
    assert result.sessions_until_next_signal == 0


def test_observation_uses_published_holdings_and_adjusted_valuation_coordinates() -> None:
    result = project_daily_observation(
        origin=account(),
        current=account(session="2026-08-18", nav="1100", count=12, cost="12.75", pending=False),
        observations=[{"session": "2026-08-18", "net_nav": "1100"}],
    )
    assert result.net_return == 0.1
    assert result.maximum_drawdown == 0
    assert Decimal(result.net_change_cny) == 100
    assert Decimal(result.transaction_cost_cny) == Decimal("2.75")
    assert result.session_count == 1
    assert result.holdings[0].shares == 100
    assert Decimal(result.holdings[0].market_value_cny) == 900
    assert result.holdings[0].weight == pytest.approx(9 / 11)
    assert result.pending_signal_session is None
    assert result.sessions_until_next_signal == 4


def test_chart_window_keeps_the_original_denominator_and_account_boundary() -> None:
    origin_date = date(2024, 1, 1)
    sessions = [(origin_date + timedelta(days=offset)).isoformat() for offset in range(507)]
    result = project_daily_observation(
        origin=account(session=sessions[0]),
        current=account(session=sessions[-2], nav="900", count=516, cost="15"),
        observations=[{"session": session, "net_nav": "900"} for session in sessions],
    )
    assert result.net_return == -0.1
    assert Decimal(result.net_change_cny) == -100
    assert result.session_count == 505
    assert len(result.returns) == 504
    assert result.returns[0].session == sessions[2]
    assert result.returns[0].net_return == -0.1
    assert result.returns[-1].session == sessions[-2]


def test_invalid_account_boundary_is_rejected() -> None:
    with pytest.raises(ValueError, match="precedes"):
        project_daily_observation(
            origin=account(), current=account(session="2026-08-14"), observations=[]
        )


def test_maximum_drawdown_uses_tracking_peaks_and_keeps_recovered_losses() -> None:
    result = project_daily_observation(
        origin=account(),
        current=account(session="2026-08-21", nav="1300", count=15, pending=False),
        observations=[
            {"session": "2026-08-14", "net_nav": "2000"},
            {"session": "2026-08-17", "net_nav": "1000"},
            {"session": "2026-08-18", "net_nav": "1200"},
            {"session": "2026-08-19", "net_nav": "900"},
            {"session": "2026-08-21", "net_nav": "1300"},
            {"session": "2026-08-24", "net_nav": "500"},
        ],
    )
    # The 1200 -> 900 decline is 25%, despite a later new high.
    # Seed history and observations beyond the published boundary are excluded.
    assert result.maximum_drawdown == 0.25


def test_maximum_drawdown_retains_losses_before_the_chart_window() -> None:
    sessions = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(507)]
    result = project_daily_observation(
        origin=account(session=sessions[0]),
        current=account(session=sessions[-1], nav="1000", count=517),
        observations=[
            {"session": session, "net_nav": "900" if index == 1 else "1000"}
            for index, session in enumerate(sessions)
        ],
    )
    assert result.maximum_drawdown == 0.1
    assert len(result.returns) == 504
    assert all(point.net_return == 0 for point in result.returns)
