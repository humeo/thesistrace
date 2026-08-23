from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from thesistrace.research_series import (
    AlignedResearchData,
    ExecutionPrice,
    InstrumentProfile,
    NumericValue,
    PriceLimit,
)


class MarketSeriesError(ValueError):
    pass


_MARKET_FIELD_COLUMNS = {
    "open": "open_adj",
    "high": "high_adj",
    "low": "low_adj",
    "close": "close_adj",
    "volume": "volume_shares",
    "amount": "turnover_amount_cny",
}


def market_field_columns(field_bindings: Mapping[str, str]) -> frozenset[str]:
    return frozenset(market_field_column_bindings(field_bindings).values())


def market_field_column_bindings(field_bindings: Mapping[str, str]) -> dict[str, str]:
    unknown = set(field_bindings.values()) - set(_MARKET_FIELD_COLUMNS)
    if unknown:
        raise MarketSeriesError("Market Field binding is unsupported")
    return {
        field_id: _MARKET_FIELD_COLUMNS[alpha_identifier]
        for field_id, alpha_identifier in field_bindings.items()
    }


def align_market_research_data(
    *,
    sessions: list[str],
    instruments: list[dict[str, object]],
    eod_prices: list[dict[str, object]],
    universe_rows: list[dict[str, object]],
    trading_states: list[dict[str, object]],
    price_limits: list[dict[str, object]],
    industry_membership: list[dict[str, object]],
    field_bindings: Mapping[str, str],
    neutralization: str,
) -> AlignedResearchData:
    aligned_sessions = tuple(str(value) for value in sessions)
    ranked_universe_members = {
        str(row["session"]): tuple(str(value) for value in row["instrument_ids"])
        for row in universe_rows
    }
    if tuple(ranked_universe_members) != aligned_sessions:
        raise MarketSeriesError("Market Universe is incomplete")
    instrument_ids = {
        instrument_id for members in ranked_universe_members.values() for instrument_id in members
    }
    instruments = {
        str(row["instrument_id"]): InstrumentProfile(
            board=str(row["board"]),
            listed_to=str(row.get("listed_to", "")),
        )
        for row in instruments
        if str(row["instrument_id"]) in instrument_ids
    }
    if set(instruments) != instrument_ids:
        raise MarketSeriesError("Market Instrument profiles are incomplete")

    prices = {
        (str(row["session_date"]), str(row["instrument_id"])): row
        for row in eod_prices
        if str(row["session_date"]) in aligned_sessions
        and str(row["instrument_id"]) in instrument_ids
    }
    universe_members = {
        session: tuple(
            instrument_id
            for instrument_id in members
            if (
                (price := prices.get((session, instrument_id))) is not None
                and price.get("open_raw") is not None
                and price.get("open_adj") is not None
                and price.get("turnover_amount_cny") is not None
                and Decimal(str(price["turnover_amount_cny"])) > 0
            )
        )
        for session, members in ranked_universe_members.items()
    }
    fields: dict[str, dict[tuple[str, str], NumericValue]] = {}
    for field_id, evaluation_name in field_bindings.items():
        column = _MARKET_FIELD_COLUMNS.get(evaluation_name)
        if column is None:
            raise MarketSeriesError("Market Field binding is unsupported")
        fields[str(field_id)] = {
            coordinate: row[column] for coordinate, row in prices.items() if column in row
        }
    execution_prices = {
        coordinate: ExecutionPrice(
            raw_open=str(row["open_raw"]),
            adjusted_open=str(row["open_adj"]),
        )
        for coordinate, row in prices.items()
    }
    trading_states = {
        (str(row["session"]), str(row["instrument_id"])): str(row["state"])
        for row in trading_states
        if str(row["session"]) in aligned_sessions and str(row["instrument_id"]) in instrument_ids
    }
    price_limits = {
        (str(row["session"]), str(row["instrument_id"])): PriceLimit(
            upper=str(row["upper"]),
            lower=str(row["lower"]),
        )
        for row in price_limits
        if str(row["session"]) in aligned_sessions and str(row["instrument_id"]) in instrument_ids
    }
    industries: dict[tuple[str, str], str] = {}
    if neutralization == "industry":
        memberships: dict[str, list[dict[str, object]]] = {}
        for row in industry_membership:
            instrument_id = str(row["instrument_id"])
            if instrument_id in instrument_ids:
                memberships.setdefault(instrument_id, []).append(row)
        for session, members in universe_members.items():
            for instrument_id in members:
                visible = [
                    row
                    for row in memberships.get(instrument_id, [])
                    if str(row["active_from"]) <= session
                    and (not str(row.get("active_to", "")) or session < str(row["active_to"]))
                ]
                if visible:
                    industries[(session, instrument_id)] = str(visible[-1]["sw2021_l1"])
    return AlignedResearchData(
        sessions=aligned_sessions,
        instruments=instruments,
        fields=fields,
        universe_members=universe_members,
        industries=industries,
        execution_prices=execution_prices,
        trading_states=trading_states,
        price_limits=price_limits,
    )
