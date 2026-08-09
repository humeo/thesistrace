from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from thesistrace.adapters.tushare_provider import (
    SOURCE_CONTRACT_VERSION,
    TushareSourceError,
    normalize_tushare_increment,
    normalize_tushare_snapshot,
)
from thesistrace.data.canonical_mapping import (
    SOURCE_CORRECTABLE_PRICE_FIELDS,
    liquidity_universes,
)
from thesistrace.data.source import (
    BootstrapCollectionPlan,
    CanonicalSourceBatch,
    CollectionPlan,
    DataSourceError,
)


class TushareProvider(Protocol):
    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]: ...

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        known_ts_codes: set[str],
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]: ...


class TushareDataSource:
    def __init__(
        self,
        *,
        provider: TushareProvider,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._provider = provider
        self._clock = clock

    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch:
        try:
            if plan.kind not in {"incremental", "refresh"}:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="REFRESH_OR_INCREMENTAL_PLAN_REQUIRED",
                )
            previous = plan.previous_canonical
            if previous is None or plan.after_session is None:
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="PREVIOUS_CANONICAL_REQUIRED",
                )
            instruments = previous.get("instruments")
            if not isinstance(instruments, list):
                raise DataSourceError(
                    "invalid_source_data",
                    detail_code="INVALID_PREVIOUS_CANONICAL",
                )
            known_codes = {
                str(item["ts_code"])
                for item in instruments
                if isinstance(item, dict) and "ts_code" in item
            }
            request_start = (
                plan.overlap_start_session if plan.kind == "refresh" else plan.after_session
            )
            assert request_start is not None
            request_end = plan.completed_through_date or self._clock()
            snapshot = self._provider.collect_incremental_snapshot(
                last_session=request_start,
                known_ts_codes=known_codes,
                as_of=request_end,
            )
            if plan.kind == "refresh":
                _validate_new_calendar_evidence(snapshot, plan.after_session)
            normalization_previous = previous
            if plan.kind == "refresh":
                normalization_previous = _canonical_before_overlap(previous, request_start)
                snapshot = _preserve_ordinary_overlap_absence(
                    snapshot,
                    previous,
                    overlap_start_session=request_start,
                )
            try:
                lineage, delta = normalize_tushare_increment(snapshot, normalization_previous)
            except TushareSourceError as error:
                if error.reason_code != "NO_NEW_RESEARCH_SESSION":
                    raise
                lineage = {
                    "source": "tushare",
                    "source_contract_version": SOURCE_CONTRACT_VERSION,
                    "responses": {key: value for key, value in sorted(snapshot.items())},
                    "no_change": True,
                }
                canonical = copy.deepcopy(dict(previous))
            else:
                canonical = _materialize_increment(normalization_previous, delta)
                if plan.kind == "refresh":
                    _remove_synthetic_predecessor(canonical, request_start)
                    _recompute_liquidity_universes(canonical)
        except TushareSourceError as error:
            raise DataSourceError(
                _error_category(error.reason_code),
                detail_code=error.reason_code,
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_PROVIDER_PAYLOAD",
            ) from error

        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list) or not calendar:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MISSING_RESEARCH_CALENDAR",
            )
        return CanonicalSourceBatch(
            source_name="tushare",
            collection_kind=plan.kind,
            source_lineage=lineage,
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )

    def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch:
        try:
            snapshot = self._provider.collect_bootstrap_snapshot(
                start_date=plan.start_date,
                completed_through_date=plan.completed_through_date,
            )
            lineage, canonical = normalize_tushare_snapshot(snapshot)
        except TushareSourceError as error:
            raise DataSourceError(
                _error_category(error.reason_code),
                detail_code=error.reason_code,
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MALFORMED_PROVIDER_PAYLOAD",
            ) from error
        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list) or not calendar:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="MISSING_RESEARCH_CALENDAR",
            )
        if str(calendar[0]) < plan.start_date.isoformat() or str(calendar[-1]) > (
            plan.completed_through_date.isoformat()
        ):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="BOOTSTRAP_WINDOW_VIOLATION",
            )
        return CanonicalSourceBatch(
            source_name="tushare",
            collection_kind="bootstrap",
            source_lineage=lineage,
            canonical=canonical,
            covered_session_range=(str(calendar[0]), str(calendar[-1])),
        )


def _error_category(reason_code: str) -> str:
    if reason_code in {"TOKEN_MISSING", "MISSING_PERMISSION"}:
        return "authorization"
    if reason_code == "UPSTREAM_UNAVAILABLE":
        return "unavailable"
    return "invalid_source_data"


def _materialize_increment(
    previous: Mapping[str, object],
    delta: Mapping[str, object],
) -> dict[str, object]:
    canonical = copy.deepcopy(dict(previous))
    append_fields = {
        "research_calendar_append": "research_calendar",
        "prices_append": "prices",
        "trading_states_append": "trading_states",
        "price_limits_append": "price_limits",
        "base_pool_append": "base_pool",
        "adjustment_anchors_append": "adjustment_anchors",
        "st_designations_append": "st_designations",
    }
    for delta_name, canonical_name in append_fields.items():
        appended = delta.get(delta_name, [])
        current = canonical.get(canonical_name)
        if current is None and canonical_name == "st_designations":
            canonical[canonical_name] = []
            current = canonical[canonical_name]
        if not isinstance(appended, list) or not isinstance(current, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        current.extend(copy.deepcopy(appended))

    replacement_fields = {
        "instruments_replace": "instruments",
        "industry_membership_replace": "industry_membership",
    }
    for delta_name, canonical_name in replacement_fields.items():
        replacement = delta.get(delta_name)
        if not isinstance(replacement, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        canonical[canonical_name] = copy.deepcopy(replacement)

    universes = canonical.get("liquidity_universes")
    appended_universes = delta.get("liquidity_universes_append", {})
    replacement_universes = delta.get("liquidity_universes_replace", {})
    if not all(
        isinstance(value, dict) for value in (universes, appended_universes, replacement_universes)
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    assert isinstance(universes, dict)
    assert isinstance(appended_universes, dict)
    assert isinstance(replacement_universes, dict)
    for name, rows in appended_universes.items():
        current = universes.get(name)
        if not isinstance(current, list) or not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        current.extend(copy.deepcopy(rows))
    for name, rows in replacement_universes.items():
        current = universes.get(name)
        if not isinstance(current, list) or not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        replacement_by_session = {
            str(row["session"]): copy.deepcopy(row)
            for row in rows
            if isinstance(row, dict) and "session" in row
        }
        current[:] = [
            replacement_by_session.get(str(row.get("session")), row)
            if isinstance(row, dict)
            else row
            for row in current
        ]

    corrections = delta.get("price_corrections", [])
    prices = canonical.get("prices")
    if not isinstance(corrections, list) or not isinstance(prices, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    price_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in prices
        if isinstance(row, dict) and "session" in row and "instrument_id" in row
    }
    for correction in corrections:
        if not isinstance(correction, dict):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        required = {"session", "instrument_id", "field", "value"}
        if not required <= correction.keys():
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        field = str(correction["field"])
        if field not in SOURCE_CORRECTABLE_PRICE_FIELDS:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        position = (
            str(correction["session"]),
            str(correction["instrument_id"]),
        )
        target = price_by_position.get(position)
        if target is None:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        target[field] = str(correction["value"])
    return canonical


def _canonical_before_overlap(
    previous: Mapping[str, object],
    overlap_start_session: str,
) -> dict[str, object]:
    calendar = previous.get("research_calendar")
    if not isinstance(calendar, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    prefix_sessions = [str(value) for value in calendar if str(value) < overlap_start_session]
    if not prefix_sessions:
        cursor = date.fromisoformat(overlap_start_session) - timedelta(days=1)
        while cursor.weekday() >= 5:
            cursor -= timedelta(days=1)
        prefix_sessions = [cursor.isoformat()]
    prefix = copy.deepcopy(dict(previous))
    prefix["research_calendar"] = prefix_sessions
    for table in ("prices", "trading_states", "price_limits", "base_pool"):
        rows = prefix.get(table)
        if not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_PREVIOUS_CANONICAL",
            )
        prefix[table] = [row for row in rows if str(row.get("session", "")) < overlap_start_session]
    designations = prefix.get("st_designations", [])
    if not isinstance(designations, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    prefix["st_designations"] = [
        row for row in designations if str(row.get("trade_date", "")) < overlap_start_session
    ]
    universes = prefix.get("liquidity_universes")
    if not isinstance(universes, dict):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    prefix["liquidity_universes"] = {
        name: [row for row in rows if str(row.get("session", "")) < overlap_start_session]
        for name, rows in universes.items()
        if isinstance(rows, list)
    }
    return prefix


def _remove_synthetic_predecessor(
    canonical: dict[str, object],
    overlap_start_session: str,
) -> None:
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or not calendar:
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    first = str(calendar[0])
    if first >= overlap_start_session:
        return
    if len(calendar) < 2 or str(calendar[1]) != overlap_start_session:
        return
    for table in ("prices", "trading_states", "price_limits", "base_pool"):
        rows = canonical.get(table)
        if not isinstance(rows, list):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_CANONICAL_INCREMENT",
            )
        if any(isinstance(row, dict) and str(row.get("session", "")) == first for row in rows):
            return
    canonical["research_calendar"] = calendar[1:]


def _recompute_liquidity_universes(canonical: dict[str, object]) -> None:
    calendar = canonical.get("research_calendar")
    base_pool = canonical.get("base_pool")
    prices = canonical.get("prices")
    states = canonical.get("trading_states")
    if not all(isinstance(value, list) for value in (calendar, base_pool, prices, states)):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_CANONICAL_INCREMENT",
        )
    assert isinstance(calendar, list)
    assert isinstance(base_pool, list)
    assert isinstance(prices, list)
    assert isinstance(states, list)
    canonical["liquidity_universes"] = liquidity_universes(
        [str(value) for value in calendar],
        base_pool,
        prices,
        states,
    )


def _preserve_ordinary_overlap_absence(
    snapshot: Mapping[str, list[dict[str, object]]],
    previous: Mapping[str, object],
    *,
    overlap_start_session: str,
) -> dict[str, list[dict[str, object]]]:
    supplemented = {name: copy.deepcopy(rows) for name, rows in snapshot.items()}
    calendar_sse = supplemented.get("calendar_sse", [])
    calendar_szse = supplemented.get("calendar_szse", [])
    stock_basic = supplemented.get("stock_basic", [])
    daily = supplemented.get("daily", [])
    adjustments = supplemented.get("adjustments", [])
    suspensions = supplemented.get("suspensions", [])
    limits = supplemented.get("price_limits", [])
    st_rows = supplemented.get("st", [])
    if not all(
        isinstance(rows, list)
        for rows in (
            calendar_sse,
            calendar_szse,
            stock_basic,
            daily,
            adjustments,
            suspensions,
            limits,
            st_rows,
        )
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="MALFORMED_PROVIDER_PAYLOAD",
        )
    previous_calendar = previous.get("research_calendar")
    previous_instruments = previous.get("instruments")
    if not isinstance(previous_calendar, list) or not isinstance(previous_instruments, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    for exchange, rows in (("SSE", calendar_sse), ("SZSE", calendar_szse)):
        returned_dates = {str(row["cal_date"]) for row in rows}
        for session in previous_calendar:
            session_text = str(session)
            if session_text < overlap_start_session:
                continue
            source_date = session_text.replace("-", "")
            if source_date not in returned_dates:
                rows.append(
                    {
                        "exchange": exchange,
                        "cal_date": source_date,
                        "is_open": "1",
                    }
                )
                returned_dates.add(source_date)
    returned_codes = {str(row["ts_code"]) for row in stock_basic}
    for instrument in previous_instruments:
        if not isinstance(instrument, dict):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_PREVIOUS_CANONICAL",
            )
        code = str(instrument["ts_code"])
        if code not in returned_codes:
            stock_basic.append(_source_instrument(instrument))
            returned_codes.add(code)
    daily_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in daily}
    suspension_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in suspensions}
    adjustment_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in adjustments}
    limit_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in limits}
    st_positions = {(str(row["trade_date"]), str(row["ts_code"])) for row in st_rows}
    instruments = previous.get("instruments")
    prices = previous.get("prices")
    states = previous.get("trading_states")
    previous_limits = previous.get("price_limits")
    previous_st = previous.get("st_designations", [])
    if not all(
        isinstance(rows, list)
        for rows in (instruments, prices, states, previous_limits, previous_st)
    ):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        )
    assert isinstance(instruments, list)
    assert isinstance(prices, list)
    assert isinstance(states, list)
    assert isinstance(previous_limits, list)
    assert isinstance(previous_st, list)
    code_by_instrument = {
        str(row["instrument_id"]): str(row["ts_code"])
        for row in instruments
        if isinstance(row, dict)
    }
    price_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in prices
        if isinstance(row, dict)
    }
    limit_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in previous_limits
        if isinstance(row, dict)
    }
    for designation in previous_st:
        if not isinstance(designation, dict):
            continue
        trade_date = str(designation.get("trade_date", ""))
        if trade_date < overlap_start_session:
            continue
        instrument_id = str(designation.get("instrument_id", ""))
        code = code_by_instrument.get(instrument_id)
        if code is None:
            continue
        source_position = (trade_date.replace("-", ""), code)
        if source_position in st_positions:
            continue
        st_rows.append(
            {
                "ts_code": code,
                "trade_date": source_position[0],
                "name": designation.get("name", "ST"),
                "type": designation.get("type", "preserved"),
                "type_name": designation.get("type_name", "preserved"),
            }
        )
        st_positions.add(source_position)
    for state in states:
        if not isinstance(state, dict):
            continue
        session = str(state["session"])
        if session < overlap_start_session:
            continue
        instrument_id = str(state["instrument_id"])
        code = code_by_instrument[instrument_id]
        source_position = (session.replace("-", ""), code)
        price = price_by_position.get((session, instrument_id))
        prior_limit = limit_by_position.get((session, instrument_id))
        if source_position in daily_positions:
            if price is not None and source_position not in adjustment_positions:
                adjustments.append(
                    {
                        "ts_code": code,
                        "trade_date": source_position[0],
                        "adj_factor": price["adjustment_factor"],
                    }
                )
                adjustment_positions.add(source_position)
            if prior_limit is not None and source_position not in limit_positions:
                limits.append(
                    {
                        "ts_code": code,
                        "trade_date": source_position[0],
                        "pre_close": (None if price is None else price["pre_close_raw"]),
                        "up_limit": prior_limit["upper"],
                        "down_limit": prior_limit["lower"],
                    }
                )
                limit_positions.add(source_position)
            continue
        if source_position in suspension_positions:
            continue
        if state["state"] == "full_session_suspension":
            suspensions.append(
                {
                    "ts_code": code,
                    "trade_date": source_position[0],
                    "suspend_timing": "全天",
                    "suspend_type": "preserved",
                }
            )
            suspension_positions.add(source_position)
            continue
        if price is None or prior_limit is None:
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INVALID_PREVIOUS_CANONICAL",
            )
        daily.append(_source_daily(code, session, price))
        daily_positions.add(source_position)
        if source_position not in adjustment_positions:
            adjustments.append(
                {
                    "ts_code": code,
                    "trade_date": source_position[0],
                    "adj_factor": price["adjustment_factor"],
                }
            )
        if source_position not in limit_positions:
            limits.append(
                {
                    "ts_code": code,
                    "trade_date": source_position[0],
                    "pre_close": price["pre_close_raw"],
                    "up_limit": prior_limit["upper"],
                    "down_limit": prior_limit["lower"],
                }
            )
    return supplemented


def _validate_new_calendar_evidence(
    snapshot: Mapping[str, list[dict[str, object]]],
    current_data_through: str,
) -> None:
    sse = snapshot.get("calendar_sse")
    szse = snapshot.get("calendar_szse")
    if not isinstance(sse, list) or not isinstance(szse, list):
        raise DataSourceError(
            "invalid_source_data",
            detail_code="MALFORMED_PROVIDER_PAYLOAD",
        )
    frontier = current_data_through.replace("-", "")
    by_exchange = (
        {str(row["cal_date"]): str(row["is_open"]) for row in sse},
        {str(row["cal_date"]): str(row["is_open"]) for row in szse},
    )
    for calendar, counterpart in (by_exchange, tuple(reversed(by_exchange))):
        if any(
            session > frontier and is_open == "1" and session not in counterpart
            for session, is_open in calendar.items()
        ):
            raise DataSourceError(
                "invalid_source_data",
                detail_code="INCOMPLETE_NEW_SESSION_CALENDAR",
            )


def _source_instrument(instrument: Mapping[str, object]) -> dict[str, object]:
    market_by_board = {"main": "主板", "chinext": "创业板", "star": "科创板"}
    board = str(instrument["board"])
    try:
        market = market_by_board[board]
    except KeyError as error:
        raise DataSourceError(
            "invalid_source_data",
            detail_code="INVALID_PREVIOUS_CANONICAL",
        ) from error
    listed_to = str(instrument.get("listed_to", ""))
    return {
        "ts_code": str(instrument["ts_code"]),
        "exchange": str(instrument["exchange"]),
        "market": market,
        "list_status": "D" if listed_to else "L",
        "list_date": str(instrument["listed_from"]).replace("-", ""),
        "delist_date": listed_to.replace("-", ""),
    }


def _source_daily(
    code: str,
    session: str,
    price: Mapping[str, object],
) -> dict[str, object]:
    return {
        "ts_code": code,
        "trade_date": session.replace("-", ""),
        "open": price["open_raw"],
        "high": price["high_raw"],
        "low": price["low_raw"],
        "close": price["close_raw"],
        "pre_close": price["pre_close_raw"],
        "change": price["change_raw"],
        "pct_chg": price["pct_change_raw"],
        "vol": str(Decimal(str(price["volume_shares"])) / Decimal(100)),
        "amount": str(Decimal(str(price["turnover_cny"])) / Decimal(1000)),
    }
