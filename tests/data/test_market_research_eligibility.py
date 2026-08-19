from __future__ import annotations

from decimal import Decimal

from thesistrace.data.market_series import align_market_research_data


def test_row_research_universe_uses_the_same_positive_turnover_eligibility() -> None:
    session = "2010-02-09"
    positive = "equity:000001.SZ"
    zero = "equity:000002.SZ"
    absent = "equity:000004.SZ"

    series = align_market_research_data(
        sessions=[session],
        instruments=[
            {"instrument_id": instrument_id, "board": "main", "listed_to": ""}
            for instrument_id in (positive, zero, absent)
        ],
        eod_prices=[
            {
                "session_date": session,
                "instrument_id": instrument_id,
                "open_raw": Decimal("10"),
                "open_adj": Decimal("10"),
                "close_adj": Decimal("10"),
                "turnover_amount_cny": turnover,
            }
            for instrument_id, turnover in (
                (positive, Decimal("1000")),
                (zero, Decimal("0")),
            )
        ],
        universe_rows=[
            {
                "session": session,
                "instrument_ids": [positive, zero, absent],
            }
        ],
        trading_states=[],
        price_limits=[],
        industry_membership=[],
        field_bindings={"price.close.adjusted": "close_adj"},
        neutralization="none",
    )

    assert series.universe_members[session] == (positive,)
