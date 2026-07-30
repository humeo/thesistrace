from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

DAILY_FIELDS = (
    ("ts_code", "source.ts_code", "Tushare instrument code", "text", "instrument"),
    ("trade_date", "source.trade_date", "market session", "date", "session"),
    ("open", "price.open.raw", "first traded price", "CNY/share", "post-close"),
    ("high", "price.high.raw", "highest traded price", "CNY/share", "post-close"),
    ("low", "price.low.raw", "lowest traded price", "CNY/share", "post-close"),
    ("close", "price.close.raw", "last traded price", "CNY/share", "post-close"),
    ("pre_close", "price.pre_close.raw", "previous close", "CNY/share", "post-close"),
    ("change", "price.change.raw", "close change", "CNY/share", "post-close"),
    ("pct_chg", "price.pct_change.raw", "close change rate", "percent", "post-close"),
    ("vol", "market.volume.source", "source volume", "100 shares", "post-close"),
    ("amount", "market.turnover.source", "source turnover", "thousand CNY", "post-close"),
)

ALPHA_FIELDS = (
    ("open_adj", "price.open.adjusted", "fixed-anchor adjusted open", "CNY/share"),
    ("high_adj", "price.high.adjusted", "fixed-anchor adjusted high", "CNY/share"),
    ("low_adj", "price.low.adjusted", "fixed-anchor adjusted low", "CNY/share"),
    ("close_adj", "price.close.adjusted", "fixed-anchor adjusted close", "CNY/share"),
    ("volume_shares", "market.volume.shares", "traded share volume", "shares"),
    ("turnover_amount_cny", "market.turnover.cny", "turnover amount", "CNY"),
)


def build_fixture() -> tuple[dict[str, object], dict[str, object]]:
    sessions = research_sessions()
    instruments = instrument_reference()
    anchor_factors = {
        instrument["instrument_id"]: adjustment_factor(len(sessions) - 1)
        for instrument in instruments
    }
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
                anchor_factor=anchor_factors[instrument_id],
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
        "st_designations": [],
    }
    canonical = {
        "schema_version": "canonical-eod-v1",
        "research_calendar": sessions,
        "instruments": instruments,
        "prices": canonical_prices,
        "trading_states": trading_states,
        "price_limits": price_limits,
        "adjustment_anchors": [
            {
                "instrument_id": instrument_id,
                "anchor_session": sessions[-1],
                "anchor_factor": decimal_string(anchor_factor, 6),
            }
            for instrument_id, anchor_factor in anchor_factors.items()
        ],
        "base_pool": [
            {"session": session, "instrument_ids": [item["instrument_id"] for item in instruments]}
            for session in sessions
        ],
        "liquidity_universes": liquidity_universes(
            sessions,
            instruments,
            canonical_prices,
            trading_states,
        ),
        "industry_membership": industry_membership(instruments, sessions),
        "field_catalog": field_catalog(sessions[-1]),
    }
    return source, canonical


def research_sessions() -> list[str]:
    current = date(2026, 7, 29)
    sessions: list[str] = []
    while len(sessions) < 756:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current -= timedelta(days=1)
    return list(reversed(sessions))


def instrument_reference() -> list[dict[str, str]]:
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
                "listed_from": "2010-01-01",
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
    anchor_factor: Decimal,
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
    scale = factor / anchor_factor
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
        "adjustment_anchor_factor": decimal_string(anchor_factor, 6),
        "open_adj": decimal_string(open_price * scale, 8),
        "high_adj": decimal_string(high * scale, 8),
        "low_adj": decimal_string(low * scale, 8),
        "close_adj": decimal_string(close * scale, 8),
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


def liquidity_universes(
    sessions: list[str],
    instruments: list[dict[str, str]],
    prices: list[dict[str, str]],
    states: list[dict[str, str]],
) -> dict[str, list[dict[str, object]]]:
    turnover = {
        (row["session"], row["instrument_id"]): Decimal(row["turnover_cny"]) for row in prices
    }
    trading_state_by_position = {
        (row["session"], row["instrument_id"]): row["state"] for row in states
    }
    ranked_by_session: list[list[str]] = []
    for session_index, _session in enumerate(sessions):
        if session_index < 19:
            ranked_by_session.append([])
            continue
        window = sessions[session_index - 19 : session_index + 1]
        scored: list[tuple[Decimal, str]] = []
        for instrument in instruments:
            instrument_id = instrument["instrument_id"]
            values: list[Decimal] = []
            for window_session in window:
                value = turnover.get((window_session, instrument_id))
                if value is not None:
                    values.append(value)
                elif (
                    trading_state_by_position.get((window_session, instrument_id))
                    == "full_session_suspension"
                ):
                    values.append(Decimal(0))
            if len(values) == 20:
                scored.append((sum(values, Decimal(0)) / 20, instrument_id))
        scored.sort(key=lambda item: item[1])
        scored.sort(key=lambda item: item[0], reverse=True)
        ranked_by_session.append([instrument_id for _, instrument_id in scored])

    universes: dict[str, list[dict[str, object]]] = {}
    for size in (300, 1000, 2000, 3000):
        universes[f"top{size}"] = [
            {
                "session": session,
                "instrument_ids": ranked_by_session[index][:size],
                "status": "available" if index >= 19 else "insufficient_history",
            }
            for index, session in enumerate(sessions)
        ]
    return universes


def field_catalog(release_available_from: str) -> list[dict[str, object]]:
    catalog = [
        {
            "name": source_name,
            "field_id": field_id,
            "definition": definition,
            "unit": unit,
            "time_semantics": semantics,
            "alpha_authorable": False,
            "release_available_from": release_available_from,
            "coverage": "canonical EOD price rows",
        }
        for source_name, field_id, definition, unit, semantics in DAILY_FIELDS
    ]
    catalog.extend(
        {
            "name": name,
            "field_id": field_id,
            "definition": definition,
            "unit": unit,
            "time_semantics": "post-close",
            "alpha_authorable": True,
            "release_available_from": release_available_from,
            "coverage": "canonical EOD price rows",
        }
        for name, field_id, definition, unit in ALPHA_FIELDS
    )
    return catalog


def decimal_string(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    return format(value.quantize(quantum, rounding=ROUND_HALF_EVEN), "f")
