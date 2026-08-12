from collections.abc import Mapping

from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.market_series import align_market_research_data
from thesistrace.research_series import AlignedResearchData


def open_complete_refresh_basis(
    store: MountedGenerationStore,
    manifest_sha256: str,
) -> dict[str, object]:
    """Open complete data only for refresh/reference tests, never Kernel input."""
    return store.open_refresh_base(
        manifest_sha256,
        overlap_session_count=100_000,
        universe_lookback_session_count=99_999,
    ).canonical


def align_canonical_market_data(
    canonical: Mapping[str, object],
    *,
    field_bindings: Mapping[str, str],
    universe: str,
    neutralization: str,
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
