from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from thesistrace.data.fields import AUTHORABLE_FIELDS

BOOTSTRAP_RESEARCH_SESSION_COUNT = 756
SOURCE_CORRECTABLE_PRICE_FIELDS = frozenset(
    {
        "open_raw",
        "high_raw",
        "low_raw",
        "close_raw",
        "pre_close_raw",
        "volume_shares",
        "turnover_cny",
    }
)

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

ALPHA_FIELDS = tuple(
    (field.evaluation_name, field.field_id, field.definition, field.unit)
    for field in AUTHORABLE_FIELDS
)


class CanonicalMappingError(RuntimeError):
    def __init__(self, detail_code: str) -> None:
        super().__init__(detail_code)
        self.detail_code = detail_code


def bootstrap_research_calendar(
    exchange_open_sessions: Sequence[Iterable[str]],
) -> list[str]:
    shared = _shared_open_sessions(exchange_open_sessions)
    if len(shared) < BOOTSTRAP_RESEARCH_SESSION_COUNT:
        raise CanonicalMappingError("INSUFFICIENT_CALENDAR_COVERAGE")
    return shared[-BOOTSTRAP_RESEARCH_SESSION_COUNT:]


def research_sessions_after(
    exchange_open_sessions: Sequence[Iterable[str]],
    after_session: str,
) -> list[str]:
    return [
        session
        for session in _shared_open_sessions(exchange_open_sessions)
        if session > after_session
    ]


def _shared_open_sessions(
    exchange_open_sessions: Sequence[Iterable[str]],
) -> list[str]:
    if len(exchange_open_sessions) < 2:
        raise CanonicalMappingError("INCOMPLETE_EXCHANGE_CALENDARS")
    shared = set(exchange_open_sessions[0])
    for sessions in exchange_open_sessions[1:]:
        shared.intersection_update(sessions)
    return sorted(shared)


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
    coverage_start = sessions[0] if sessions else ""
    ranked_by_session: list[list[str]] = []
    for session_index, _session in enumerate(sessions):
        window = sessions[max(0, session_index - 19) : session_index + 1]
        expanding_at_coverage_start = session_index < 19
        scored: list[tuple[Decimal, str]] = []
        for instrument in instruments:
            instrument_id = instrument["instrument_id"]
            if expanding_at_coverage_start and not _listed_on_session(instrument, coverage_start):
                continue
            values: list[Decimal] = []
            for window_session in window:
                if not _listed_on_session(instrument, window_session):
                    break
                state = trading_state_by_position.get((window_session, instrument_id))
                if state == "full_session_suspension":
                    values.append(Decimal(0))
                    continue
                value = turnover.get((window_session, instrument_id))
                if value is None:
                    break
                values.append(value)
            if len(values) == len(window):
                scored.append((sum(values, Decimal(0)) / Decimal(len(window)), instrument_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked_by_session.append([instrument_id for _, instrument_id in scored])

    universes: dict[str, list[dict[str, object]]] = {}
    for size in (300, 1000, 2000, 3000):
        universes[f"top{size}"] = [
            {
                "session": session,
                "instrument_ids": ranked_by_session[index][:size],
                "status": "available",
            }
            for index, session in enumerate(sessions)
        ]
    return universes


def _listed_on_session(instrument: Mapping[str, str], session: str) -> bool:
    listed_from = str(instrument.get("listed_from", ""))
    listed_to = str(instrument.get("listed_to", ""))
    return (not listed_from or listed_from <= session) and (not listed_to or session < listed_to)


def field_catalog(available_from: str) -> list[dict[str, object]]:
    catalog = [
        {
            "name": source_name,
            "field_id": field_id,
            "definition": definition,
            "unit": unit,
            "time_semantics": semantics,
            "alpha_authorable": False,
            "release_available_from": available_from,
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
            "release_available_from": available_from,
            "coverage": "canonical EOD price rows",
        }
        for name, field_id, definition, unit in ALPHA_FIELDS
    )
    return catalog


def decimal_string(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    return format(value.quantize(quantum, rounding=ROUND_HALF_EVEN), "f")
