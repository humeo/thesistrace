from datetime import date, timedelta
from decimal import Decimal

from thesistrace.data.canonical_mapping import ALPHA_FIELDS as ALPHA_FIELDS
from thesistrace.data.canonical_mapping import DAILY_FIELDS as DAILY_FIELDS
from thesistrace.data.canonical_mapping import decimal_string, field_catalog, liquidity_universes


def build_minimal_canonical_fixture(*, price_offset: int = 0) -> dict[str, object]:
    """One valid session for storage/lifecycle tests that do not need market breadth."""
    session = "2026-08-07"
    instrument_id = "equity:000001.SZ"
    pre_close = Decimal(10 + price_offset)
    close = pre_close + Decimal("0.5")
    high = pre_close + Decimal(1)
    low = pre_close - Decimal(1)
    universe = {"session": session, "instrument_ids": [instrument_id], "status": "available"}
    return {
        "schema_version": "canonical-eod",
        "research_calendar": [session],
        "instruments": [
            {
                "instrument_id": instrument_id,
                "ts_code": "000001.SZ",
                "asset_type": "ordinary_a_share",
                "exchange": "SZSE",
                "board": "main",
                "listed_from": "1991-04-03",
                "listed_to": "",
            }
        ],
        "prices": [
            {
                "session": session,
                "instrument_id": instrument_id,
                "open_raw": decimal_string(pre_close, 4),
                "high_raw": decimal_string(high, 4),
                "low_raw": decimal_string(low, 4),
                "close_raw": decimal_string(close, 4),
                "pre_close_raw": decimal_string(pre_close, 4),
                "change_raw": "0.5000",
                "pct_change_raw": decimal_string(Decimal("50") / pre_close, 6),
                "volume_shares": "10000",
                "turnover_cny": decimal_string(pre_close * Decimal(10000), 2),
                "adjustment_factor": "1.000000",
                "open_adj": decimal_string(pre_close, 8),
                "high_adj": decimal_string(high, 8),
                "low_adj": decimal_string(low, 8),
                "close_adj": decimal_string(close, 8),
                "trading_state": "normal",
            }
        ],
        "trading_states": [{"session": session, "instrument_id": instrument_id, "state": "normal"}],
        "price_limits": [
            {
                "session": session,
                "instrument_id": instrument_id,
                "upper": decimal_string(high, 4),
                "lower": decimal_string(low, 4),
            }
        ],
        "base_pool": [{"session": session, "instrument_ids": [instrument_id]}],
        "liquidity_universes": {
            name: [dict(universe)] for name in ("top300", "top1000", "top2000", "top3000")
        },
        "industry_membership": [
            {
                "instrument_id": instrument_id,
                "active_from": "2021-01-01",
                "active_to": "",
                "sw2021_l1": "Bank",
                "sw2021_l2": "Bank",
                "sw2021_l3": "Bank",
            }
        ],
        "field_catalog": [
            next(
                row
                for row in field_catalog(session)
                if row["name"] == "close" and row["alpha_authorable"] is True
            )
        ],
    }


DEFAULT_FIXTURE_SESSION_COUNT = 64


def build_fixture(
    *,
    session_count: int = DEFAULT_FIXTURE_SESSION_COUNT,
) -> tuple[dict[str, object], dict[str, object]]:
    sessions = research_sessions(session_count=session_count)
    instruments = instrument_reference(sessions[0])
    source_daily: list[dict[str, str]] = []
    source_adjustments: list[dict[str, str]] = []
    canonical_prices: list[dict[str, str]] = []
    trading_states: list[dict[str, str]] = []
    price_limits: list[dict[str, str]] = []

    for session_index, session in enumerate(sessions):
        for instrument_index, instrument in enumerate(instruments):
            instrument_id = str(instrument["instrument_id"])
            state = trading_state(session_index, instrument_index)
            trading_states.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "state": state,
                }
            )
            factor = adjustment_factor(session_index)
            source_adjustments.append(
                {
                    "trade_date": session,
                    "ts_code": str(instrument["ts_code"]),
                    "adj_factor": decimal_string(factor, 6),
                }
            )
            if state == "full_session_suspension":
                continue
            source_row, canonical_row = price_rows(
                session=session,
                session_index=session_index,
                instrument=instrument,
                instrument_index=instrument_index,
                factor=factor,
                state=state,
            )
            source_daily.append(source_row)
            canonical_prices.append(canonical_row)
            price_limits.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "upper": decimal_string(Decimal(source_row["pre_close"]) * Decimal("1.10"), 4),
                    "lower": decimal_string(Decimal(source_row["pre_close"]) * Decimal("0.90"), 4),
                }
            )

    source = {
        "fixture": "v1",
        "source": "deterministic-fixture",
        "source_units": {
            "vol": "100 shares",
            "amount": "thousand CNY",
        },
        "sse_open_days": sessions,
        "szse_open_days": sessions,
        "instruments": instruments,
        "daily": source_daily,
        "adjustments": source_adjustments,
        "industry_membership": industry_membership(instruments, sessions),
    }
    base_pool = [
        {"session": session, "instrument_ids": [item["instrument_id"] for item in instruments]}
        for session in sessions
    ]
    canonical = {
        "schema_version": "canonical-eod",
        "research_calendar": sessions,
        "instruments": instruments,
        "prices": canonical_prices,
        "trading_states": trading_states,
        "price_limits": price_limits,
        "base_pool": base_pool,
        "liquidity_universes": liquidity_universes(
            sessions,
            base_pool,
            canonical_prices,
            trading_states,
        ),
        "industry_membership": industry_membership(instruments, sessions),
        "field_catalog": field_catalog(sessions[-1]),
    }
    return source, canonical


def research_sessions(*, session_count: int = DEFAULT_FIXTURE_SESSION_COUNT) -> list[str]:
    if session_count < 1:
        raise ValueError("Fixture session count must be positive")
    current = date(2026, 7, 29)
    sessions: list[str] = []
    while len(sessions) < session_count:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current -= timedelta(days=1)
    return list(reversed(sessions))


def instrument_reference(listed_from: str) -> list[dict[str, str]]:
    instruments: list[dict[str, str]] = []
    for index in range(35):
        if index % 2 == 0:
            ts_code = f"{600000 + index:06d}.SH"
            board = "main"
            exchange = "SSE"
        else:
            ts_code = f"{index:06d}.SZ"
            board = "main" if index < 20 else "chinext"
            exchange = "SZSE"
        instruments.append(
            {
                "instrument_id": f"equity:{ts_code}",
                "ts_code": ts_code,
                "asset_type": "ordinary_a_share",
                "exchange": exchange,
                "board": board,
                "listed_from": listed_from,
                "listed_to": "",
            }
        )
    return instruments


def price_rows(
    *,
    session: str,
    session_index: int,
    instrument: dict[str, str],
    instrument_index: int,
    factor: Decimal,
    state: str,
) -> tuple[dict[str, str], dict[str, str]]:
    base = Decimal("8") + Decimal(instrument_index) / 5 + Decimal(session_index % 31) / 100
    open_price = base
    high = base + Decimal("0.10")
    low = base - Decimal("0.10")
    close = base + Decimal((session_index % 5) - 2) / 100
    pre_close = base - Decimal("0.02")
    change = close - pre_close
    pct_change = change / pre_close * 100
    volume_lots = Decimal(100_000 + instrument_index * 1_000 + session_index * 10)
    source_amount = close * volume_lots / 10
    source_row = {
        "ts_code": instrument["ts_code"],
        "trade_date": session,
        "open": decimal_string(open_price, 4),
        "high": decimal_string(high, 4),
        "low": decimal_string(low, 4),
        "close": decimal_string(close, 4),
        "pre_close": decimal_string(pre_close, 4),
        "change": decimal_string(change, 4),
        "pct_chg": decimal_string(pct_change, 6),
        "vol": decimal_string(volume_lots, 0),
        "amount": decimal_string(source_amount, 4),
    }
    canonical_row = {
        "session": session,
        "instrument_id": instrument["instrument_id"],
        "open_raw": source_row["open"],
        "high_raw": source_row["high"],
        "low_raw": source_row["low"],
        "close_raw": source_row["close"],
        "pre_close_raw": source_row["pre_close"],
        "change_raw": source_row["change"],
        "pct_change_raw": source_row["pct_chg"],
        "volume_shares": decimal_string(volume_lots * 100, 0),
        "turnover_cny": decimal_string(source_amount * 1000, 2),
        "adjustment_factor": decimal_string(factor, 6),
        "open_adj": decimal_string(open_price * factor, 8),
        "high_adj": decimal_string(high * factor, 8),
        "low_adj": decimal_string(low * factor, 8),
        "close_adj": decimal_string(close * factor, 8),
        "trading_state": state,
    }
    return source_row, canonical_row


def adjustment_factor(session_index: int) -> Decimal:
    return Decimal("1") + Decimal(session_index // 200) * Decimal("0.05")


def trading_state(session_index: int, instrument_index: int) -> str:
    if session_index == 100 and instrument_index == 0:
        return "full_session_suspension"
    if session_index == 101 and instrument_index == 1:
        return "partial_opening_suspension"
    if session_index == 102 and instrument_index == 2:
        return "after_open_suspension"
    return "normal"


def industry_membership(
    instruments: list[dict[str, str]], sessions: list[str]
) -> list[dict[str, str]]:
    return [
        {
            "instrument_id": instrument["instrument_id"],
            "active_from": sessions[0],
            "active_to": "",
            "sw2021_l1": f"L1-{index % 5 + 1}",
            "sw2021_l2": f"L2-{index % 10 + 1}",
            "sw2021_l3": f"L3-{index % 15 + 1}",
        }
        for index, instrument in enumerate(instruments)
    ]
