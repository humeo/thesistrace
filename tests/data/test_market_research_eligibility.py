from __future__ import annotations

from decimal import Decimal

import pytest

from thesistrace.data.market_series import (
    MarketSeriesError,
    align_market_research_data,
    market_field_column_bindings,
    market_field_columns,
)


def test_market_alpha_names_resolve_to_the_existing_physical_columns() -> None:
    bindings = {
        "price.open.adjusted": "open",
        "price.high.adjusted": "high",
        "price.low.adjusted": "low",
        "price.close.adjusted": "close",
        "market.volume.shares": "volume",
        "market.turnover.cny": "amount",
    }

    assert market_field_columns(bindings) == frozenset(
        {
            "open_adj",
            "high_adj",
            "low_adj",
            "close_adj",
            "volume_shares",
            "turnover_amount_cny",
        }
    )
    assert market_field_column_bindings(bindings) == {
        "price.open.adjusted": "open_adj",
        "price.high.adjusted": "high_adj",
        "price.low.adjusted": "low_adj",
        "price.close.adjusted": "close_adj",
        "market.volume.shares": "volume_shares",
        "market.turnover.cny": "turnover_amount_cny",
    }
    with pytest.raises(MarketSeriesError, match="unsupported"):
        market_field_columns({"price.close.adjusted": "close_adj"})


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
        field_bindings={"price.close.adjusted": "close"},
        neutralization="none",
    )

    assert series.universe_members[session] == (positive,)
