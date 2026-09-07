from collections.abc import Mapping

from contracts import FIELD_BINDINGS

from thesistrace.data.market_series import align_market_research_data
from thesistrace.research_series import AlignedResearchData


def aligned_market_data(
    canonical: Mapping[str, object],
    *,
    universe: str = "top300",
    neutralization: str = "none",
    field_bindings: Mapping[str, str] = FIELD_BINDINGS,
) -> AlignedResearchData:
    universe_tables = canonical["liquidity_universes"]
    assert isinstance(universe_tables, Mapping)
    universe_rows = universe_tables[universe]
    assert isinstance(universe_rows, list)
    prices = canonical["prices"]
    assert isinstance(prices, list)
    return align_market_research_data(
        sessions=[str(value) for value in canonical["research_calendar"]],
        instruments=list(canonical["instruments"]),
        eod_prices=[
            {
                "session_date": row["session"],
                "instrument_id": row["instrument_id"],
                "open_raw": row["open_raw"],
                "open_adj": row["open_adj"],
                **{
                    physical: row[source]
                    for physical, source in (
                        ("high_adj", "high_adj"),
                        ("low_adj", "low_adj"),
                        ("close_adj", "close_adj"),
                        ("volume_shares", "volume_shares"),
                        ("turnover_amount_cny", "turnover_cny"),
                    )
                    if source in row
                },
            }
            for row in prices
        ],
        universe_rows=list(universe_rows),
        trading_states=list(canonical["trading_states"]),
        price_limits=list(canonical["price_limits"]),
        industry_membership=list(canonical["industry_membership"]),
        field_bindings=field_bindings,
        neutralization=neutralization,
    )
