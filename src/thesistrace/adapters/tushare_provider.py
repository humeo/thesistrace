"""Tushare transport, collection, and canonical normalization adapter."""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

import httpx

from thesistrace.data.canonical_mapping import (
    CanonicalMappingError,
    adjusted_price_string,
    bootstrap_research_calendar,
    decimal_string,
    field_catalog,
    liquidity_universes,
    research_sessions_after,
)

SOURCE_CONTRACT_VERSION = "tushare-v1"


class TushareTransport(Protocol):
    def post(self, payload: Mapping[str, object]) -> dict[str, object]: ...


class HttpTushareTransport:
    def __init__(self, endpoint: str = "https://api.tushare.pro", timeout_seconds: float = 30):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(timeout=timeout_seconds)

    def post(self, payload: Mapping[str, object]) -> dict[str, object]:
        response = self._client.post(self.endpoint, json=dict(payload))
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as error:
            raise TushareSourceError("INVALID_RESPONSE", source_code=None) from error
        if not isinstance(result, dict):
            raise TushareSourceError("INVALID_RESPONSE", source_code=None)
        return result

    def close(self) -> None:
        self._client.close()


class TushareSourceError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        source_code: int | None,
        contract: str | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.source_code = source_code
        self.contract = contract

    def diagnostic(self) -> dict[str, object]:
        diagnostic: dict[str, object] = {
            "reason_code": self.reason_code,
            "source_code": self.source_code,
        }
        if self.contract is not None:
            diagnostic["contract"] = self.contract
        return diagnostic


@dataclass(frozen=True)
class PermissionProbe:
    contract: str
    api_name: str
    params: dict[str, object]
    fields: tuple[str, ...]


def permission_probes(reference_date: date | None = None) -> tuple[PermissionProbe, ...]:
    current = reference_date or date.today()
    current_text = current.strftime("%Y%m%d")
    month_start = current.replace(day=1).strftime("%Y%m%d")
    return (
        PermissionProbe(
            "reference",
            "stock_basic",
            {"list_status": "L"},
            ("ts_code", "symbol", "name", "exchange", "market", "list_date"),
        ),
        PermissionProbe(
            "calendar_sse",
            "trade_cal",
            {"exchange": "SSE", "start_date": month_start, "end_date": current_text},
            ("exchange", "cal_date", "is_open", "pretrade_date"),
        ),
        PermissionProbe(
            "calendar_szse",
            "trade_cal",
            {"exchange": "SZSE", "start_date": month_start, "end_date": current_text},
            ("exchange", "cal_date", "is_open", "pretrade_date"),
        ),
        PermissionProbe(
            "daily",
            "daily",
            {"trade_date": current_text},
            (
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
            ),
        ),
        PermissionProbe(
            "adjustment",
            "adj_factor",
            {"trade_date": current_text},
            ("ts_code", "trade_date", "adj_factor"),
        ),
        PermissionProbe(
            "suspension",
            "suspend_d",
            {"trade_date": current_text},
            ("ts_code", "trade_date", "suspend_type"),
        ),
        PermissionProbe(
            "st",
            "stock_st",
            {"trade_date": current_text},
            ("ts_code", "name", "trade_date", "type", "type_name"),
        ),
        PermissionProbe(
            "price_limit",
            "stk_limit",
            {"trade_date": current_text},
            ("trade_date", "ts_code", "pre_close", "up_limit", "down_limit"),
        ),
        PermissionProbe(
            "sw2021_classification",
            "index_classify",
            {"level": "L1", "src": "SW2021"},
            ("index_code", "industry_name", "level", "src"),
        ),
        PermissionProbe(
            "sw2021_membership",
            "index_member_all",
            {"is_new": "Y"},
            ("l1_code", "l2_code", "l3_code", "ts_code", "in_date", "out_date"),
        ),
    )


class TushareAdapter:
    def __init__(
        self,
        *,
        token: str,
        transport: TushareTransport,
        page_size: int = 5_000,
        throttle_seconds: float = 0.12,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token:
            raise TushareSourceError("TOKEN_MISSING", source_code=None)
        self._token = token
        self._transport = transport
        self._page_size = page_size
        self._throttle_seconds = throttle_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper

    def preflight(self) -> dict[str, object]:
        permissions: list[dict[str, str]] = []
        for probe in permission_probes():
            try:
                self.query(probe.api_name, params=probe.params, fields=probe.fields)
            except TushareSourceError as error:
                if error.reason_code == "MISSING_PERMISSION":
                    error.contract = probe.contract
                raise
            permissions.append({"contract": probe.contract, "status": "available"})
        return {
            "status": "available",
            "source": "tushare",
            "source_contract_version": SOURCE_CONTRACT_VERSION,
            "permissions": permissions,
        }

    def collect_bootstrap_snapshot(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        end_date = completed_through_date.strftime("%Y%m%d")
        calendar_start = start_date.strftime("%Y%m%d")
        sse_calendar = self.query_paginated(
            "trade_cal",
            params={"exchange": "SSE", "start_date": calendar_start, "end_date": end_date},
            fields=("exchange", "cal_date", "is_open", "pretrade_date"),
            primary_key=("exchange", "cal_date"),
        )
        szse_calendar = self.query_paginated(
            "trade_cal",
            params={"exchange": "SZSE", "start_date": calendar_start, "end_date": end_date},
            fields=("exchange", "cal_date", "is_open", "pretrade_date"),
            primary_key=("exchange", "cal_date"),
        )
        shared_open = sorted(
            {str(row["cal_date"]) for row in sse_calendar if str(row["is_open"]) == "1"}
            & {str(row["cal_date"]) for row in szse_calendar if str(row["is_open"]) == "1"}
        )
        if not shared_open:
            raise TushareSourceError("INSUFFICIENT_CALENDAR_COVERAGE", source_code=0)
        end_date = shared_open[-1]

        stock_basic: list[dict[str, object]] = []
        for list_status in ("L", "D", "P"):
            stock_basic.extend(
                self.query_paginated(
                    "stock_basic",
                    params={"list_status": list_status},
                    fields=(
                        "ts_code",
                        "symbol",
                        "name",
                        "market",
                        "exchange",
                        "list_status",
                        "list_date",
                        "delist_date",
                    ),
                    primary_key=("ts_code", "list_status"),
                )
            )
        stock_by_code = {str(row["ts_code"]): row for row in stock_basic}
        stock_basic = [stock_by_code[key] for key in sorted(stock_by_code)]
        anchor_daily, anchor_adjustments = self._collect_adjustment_anchors(
            stock_basic, date.fromisoformat(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}")
        )

        return {
            "calendar_sse": sse_calendar,
            "calendar_szse": szse_calendar,
            "stock_basic": stock_basic,
            "anchor_daily": anchor_daily,
            "anchor_adjustments": anchor_adjustments,
            "daily": self.query_paginated(
                "daily",
                params={"start_date": calendar_start, "end_date": end_date},
                fields=(
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "change",
                    "pct_chg",
                    "vol",
                    "amount",
                ),
                primary_key=("trade_date", "ts_code"),
            ),
            "adjustments": self.query_paginated(
                "adj_factor",
                params={"start_date": calendar_start, "end_date": end_date},
                fields=("ts_code", "trade_date", "adj_factor"),
                primary_key=("trade_date", "ts_code"),
            ),
            "suspensions": self.query_paginated(
                "suspend_d",
                params={"start_date": calendar_start, "end_date": end_date},
                fields=("ts_code", "trade_date", "suspend_timing", "suspend_type"),
                primary_key=("trade_date", "ts_code", "suspend_type"),
            ),
            "st": self.query_paginated(
                "stock_st",
                params={"start_date": calendar_start, "end_date": end_date},
                fields=("ts_code", "name", "trade_date", "type", "type_name"),
                primary_key=("trade_date", "ts_code"),
            ),
            "price_limits": self.query_paginated(
                "stk_limit",
                params={"start_date": calendar_start, "end_date": end_date},
                fields=("trade_date", "ts_code", "pre_close", "up_limit", "down_limit"),
                primary_key=("trade_date", "ts_code"),
            ),
            "industry_classification": self.query_paginated(
                "index_classify",
                params={"src": "SW2021"},
                fields=("index_code", "industry_name", "level", "src"),
                primary_key=("index_code",),
            ),
            "industry_membership": self.query_paginated(
                "index_member_all",
                params={},
                fields=("l1_code", "l2_code", "l3_code", "ts_code", "in_date", "out_date"),
                primary_key=("ts_code", "in_date", "l3_code"),
            ),
        }

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
        known_ts_codes: set[str],
        as_of: date,
    ) -> dict[str, list[dict[str, object]]]:
        start_date = last_session.replace("-", "")
        end_date = as_of.strftime("%Y%m%d")
        stock_basic: list[dict[str, object]] = []
        for list_status in ("L", "D", "P"):
            stock_basic.extend(
                self.query_paginated(
                    "stock_basic",
                    params={"list_status": list_status},
                    fields=(
                        "ts_code",
                        "symbol",
                        "name",
                        "market",
                        "exchange",
                        "list_status",
                        "list_date",
                        "delist_date",
                    ),
                    primary_key=("ts_code", "list_status"),
                )
            )
        stock_by_code = {str(row["ts_code"]): row for row in stock_basic}
        stock_basic = [stock_by_code[key] for key in sorted(stock_by_code)]
        new_stock_basic = [row for row in stock_basic if str(row["ts_code"]) not in known_ts_codes]
        anchor_daily, anchor_adjustments = self._collect_adjustment_anchors(
            new_stock_basic,
            as_of,
        )
        ranged = {"start_date": start_date, "end_date": end_date}
        return {
            "calendar_sse": self.query_paginated(
                "trade_cal",
                params={"exchange": "SSE", **ranged},
                fields=("exchange", "cal_date", "is_open", "pretrade_date"),
                primary_key=("exchange", "cal_date"),
            ),
            "calendar_szse": self.query_paginated(
                "trade_cal",
                params={"exchange": "SZSE", **ranged},
                fields=("exchange", "cal_date", "is_open", "pretrade_date"),
                primary_key=("exchange", "cal_date"),
            ),
            "stock_basic": stock_basic,
            "anchor_daily": anchor_daily,
            "anchor_adjustments": anchor_adjustments,
            "daily": self.query_paginated(
                "daily",
                params=ranged,
                fields=(
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "change",
                    "pct_chg",
                    "vol",
                    "amount",
                ),
                primary_key=("trade_date", "ts_code"),
            ),
            "adjustments": self.query_paginated(
                "adj_factor",
                params=ranged,
                fields=("ts_code", "trade_date", "adj_factor"),
                primary_key=("trade_date", "ts_code"),
            ),
            "suspensions": self.query_paginated(
                "suspend_d",
                params=ranged,
                fields=("ts_code", "trade_date", "suspend_timing", "suspend_type"),
                primary_key=("trade_date", "ts_code", "suspend_type"),
            ),
            "st": self.query_paginated(
                "stock_st",
                params=ranged,
                fields=("ts_code", "name", "trade_date", "type", "type_name"),
                primary_key=("trade_date", "ts_code"),
            ),
            "price_limits": self.query_paginated(
                "stk_limit",
                params=ranged,
                fields=("trade_date", "ts_code", "pre_close", "up_limit", "down_limit"),
                primary_key=("trade_date", "ts_code"),
            ),
            "industry_membership": self.query_paginated(
                "index_member_all",
                params={"is_new": "Y"},
                fields=("l1_code", "l2_code", "l3_code", "ts_code", "in_date", "out_date"),
                primary_key=("ts_code", "in_date", "l3_code"),
            ),
        }

    def _collect_adjustment_anchors(
        self,
        stock_basic: list[dict[str, object]],
        as_of: date,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        anchor_daily: list[dict[str, object]] = []
        anchor_adjustments: list[dict[str, object]] = []
        by_listing_date: dict[str, list[dict[str, str]]] = {}
        for instrument in normalize_instruments(stock_basic):
            if date.fromisoformat(instrument["listed_from"]) <= as_of:
                by_listing_date.setdefault(
                    instrument["listed_from"].replace("-", ""),
                    [],
                ).append(instrument)
        daily_fields = (
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        )
        unresolved: list[dict[str, str]] = []
        for listing_date, instruments in sorted(by_listing_date.items()):
            daily = self.query_paginated(
                "daily",
                params={"trade_date": listing_date},
                fields=daily_fields,
                primary_key=("trade_date", "ts_code"),
            )
            adjustments = self.query_paginated(
                "adj_factor",
                params={"trade_date": listing_date},
                fields=("ts_code", "trade_date", "adj_factor"),
                primary_key=("trade_date", "ts_code"),
            )
            daily_by_code = {str(row["ts_code"]): row for row in daily}
            adjustment_by_code = {str(row["ts_code"]): row for row in adjustments}
            for instrument in instruments:
                code = instrument["ts_code"]
                if code in daily_by_code and code in adjustment_by_code:
                    anchor_daily.append(daily_by_code[code])
                    anchor_adjustments.append(adjustment_by_code[code])
                else:
                    unresolved.append(instrument)
            if self._throttle_seconds:
                self._sleeper(self._throttle_seconds)

        for instrument in unresolved:
            daily, adjustment = self._search_adjustment_anchor(
                instrument,
                as_of,
                daily_fields,
            )
            anchor_daily.append(daily)
            anchor_adjustments.append(adjustment)
        return anchor_daily, anchor_adjustments

    def _search_adjustment_anchor(
        self,
        instrument: dict[str, str],
        as_of: date,
        daily_fields: tuple[str, ...],
    ) -> tuple[dict[str, object], dict[str, object]]:
        window_start = date.fromisoformat(instrument["listed_from"])
        while window_start <= as_of:
            end = min(window_start + timedelta(days=45), as_of)
            params = {
                "ts_code": instrument["ts_code"],
                "start_date": window_start.strftime("%Y%m%d"),
                "end_date": end.strftime("%Y%m%d"),
            }
            daily = self.query_paginated(
                "daily",
                params=params,
                fields=daily_fields,
                primary_key=("trade_date", "ts_code"),
            )
            adjustments = self.query_paginated(
                "adj_factor",
                params=params,
                fields=("ts_code", "trade_date", "adj_factor"),
                primary_key=("trade_date", "ts_code"),
            )
            daily_by_session = {str(row["trade_date"]): row for row in daily}
            adjustment_by_session = {str(row["trade_date"]): row for row in adjustments}
            qualifying = sorted(daily_by_session.keys() & adjustment_by_session.keys())
            if qualifying:
                anchor_session = qualifying[0]
                return (
                    daily_by_session[anchor_session],
                    adjustment_by_session[anchor_session],
                )
            window_start = end + timedelta(days=1)
            if self._throttle_seconds:
                self._sleeper(self._throttle_seconds)
        raise TushareSourceError(
            "INCOMPLETE_ADJUSTMENT_ANCHOR",
            source_code=0,
        )

    def query(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> list[dict[str, object]]:
        payload = {
            "api_name": api_name,
            "token": self._token,
            "params": dict(params),
            "fields": ",".join(fields),
        }
        result = self._request_with_retry(payload)
        data = result.get("data")
        if not isinstance(data, dict):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0)
        response_fields = data.get("fields")
        items = data.get("items")
        if not isinstance(response_fields, list) or not isinstance(items, list):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0)
        if any(not isinstance(field, str) for field in response_fields):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0)
        if not set(fields) <= set(response_fields):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0)
        if any(not isinstance(row, list) or len(row) != len(response_fields) for row in items):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0)
        return [dict(zip(response_fields, row, strict=True)) for row in items]

    def query_paginated(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
        primary_key: Sequence[str],
    ) -> list[dict[str, object]]:
        offset = 0
        rows_by_key: dict[tuple[object, ...], dict[str, object]] = {}
        while True:
            page_params = {**params, "limit": self._page_size, "offset": offset}
            page = self.query(api_name, params=page_params, fields=fields)
            for row in page:
                key = tuple(row.get(field) for field in primary_key)
                if any(value is None for value in key):
                    raise TushareSourceError("INVALID_PRIMARY_KEY", source_code=0)
                rows_by_key[key] = row
            if len(page) < self._page_size:
                break
            offset += self._page_size
            if self._throttle_seconds:
                self._sleeper(self._throttle_seconds)
        return [rows_by_key[key] for key in sorted(rows_by_key)]

    def _request_with_retry(self, payload: dict[str, object]) -> dict[str, object]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                result = self._transport.post(payload)
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                retryable = status_code == 429 or status_code >= 500
                if retryable and attempt < self._max_attempts:
                    self._sleeper(self._throttle_seconds * attempt)
                    continue
                reason_code = "UPSTREAM_UNAVAILABLE" if retryable else "UPSTREAM_REJECTED"
                raise TushareSourceError(
                    reason_code,
                    source_code=status_code,
                ) from error
            except (httpx.TransportError, OSError) as error:
                if attempt == self._max_attempts:
                    raise TushareSourceError("UPSTREAM_UNAVAILABLE", source_code=None) from error
                self._sleeper(self._throttle_seconds * attempt)
                continue
            code = result.get("code")
            if code == 0:
                return result
            if code == 2002:
                raise TushareSourceError("MISSING_PERMISSION", source_code=2002)
            if code in {429, 500, -2001} and attempt < self._max_attempts:
                self._sleeper(self._throttle_seconds * attempt)
                continue
            raise TushareSourceError(
                "UPSTREAM_REJECTED",
                source_code=int(code) if isinstance(code, int) else None,
            )
        raise AssertionError("retry loop exhausted")


def normalize_tushare_snapshot(
    snapshot: Mapping[str, list[dict[str, object]]],
) -> tuple[dict[str, object], dict[str, object]]:
    sse_open = {
        str(row["cal_date"]) for row in snapshot["calendar_sse"] if str(row["is_open"]) == "1"
    }
    szse_open = {
        str(row["cal_date"]) for row in snapshot["calendar_szse"] if str(row["is_open"]) == "1"
    }
    try:
        session_keys = bootstrap_research_calendar((sse_open, szse_open))
    except CanonicalMappingError as error:
        raise TushareSourceError(error.detail_code, source_code=0) from error
    sessions = [iso_date(value) for value in session_keys]
    session_set = set(session_keys)

    instruments = normalize_instruments(snapshot["stock_basic"])
    instrument_by_code = {str(row["ts_code"]): row for row in instruments}

    daily_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot["daily"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    factor_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): decimal(row["adj_factor"])
        for row in snapshot["adjustments"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    suspensions: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in snapshot["suspensions"]:
        position = (str(row["trade_date"]), str(row["ts_code"]))
        if position[0] in session_set and position[1] in instrument_by_code:
            suspensions.setdefault(position, []).append(row)
    limit_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot["price_limits"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    anchor_daily_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot.get("anchor_daily", [])
        if str(row["ts_code"]) in instrument_by_code
    }
    anchor_factor_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): decimal(row["adj_factor"])
        for row in snapshot.get("anchor_adjustments", [])
        if str(row["ts_code"]) in instrument_by_code
    }
    anchor_by_code: dict[str, tuple[str, Decimal]] = {}
    for code, instrument in instrument_by_code.items():
        listed_from = str(instrument["listed_from"]).replace("-", "")
        qualifying = sorted(
            trade_date
            for trade_date, ts_code in anchor_daily_by_position
            if ts_code == code
            and trade_date >= listed_from
            and (trade_date, code) in anchor_factor_by_position
        )
        if not qualifying:
            raise TushareSourceError("INCOMPLETE_ADJUSTMENT_ANCHOR", source_code=0)
        anchor_session = qualifying[0]
        anchor_daily = anchor_daily_by_position[(anchor_session, code)]
        validate_source_bar(anchor_daily)
        anchor_factor = anchor_factor_by_position[(anchor_session, code)]
        if anchor_factor <= 0:
            raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
        anchor_by_code[code] = (
            anchor_session,
            anchor_factor,
        )

    canonical_prices: list[dict[str, str]] = []
    trading_states: list[dict[str, str]] = []
    price_limits: list[dict[str, str]] = []
    base_pool: list[dict[str, object]] = []
    for session_key, session in zip(session_keys, sessions, strict=True):
        active_codes = [
            code
            for code, instrument in instrument_by_code.items()
            if is_active(instrument, session_key)
        ]
        base_pool.append(
            {
                "session": session,
                "instrument_ids": [
                    str(instrument_by_code[code]["instrument_id"]) for code in active_codes
                ],
            }
        )
        for code in active_codes:
            instrument_id = str(instrument_by_code[code]["instrument_id"])
            source_row = daily_by_position.get((session_key, code))
            suspension = suspensions.get((session_key, code))
            state = resolve_trading_state(source_row, suspension)
            trading_states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            if source_row is None:
                continue
            factor = factor_by_position.get((session_key, code))
            anchor_record = anchor_by_code.get(code)
            limit = limit_by_position.get((session_key, code))
            if factor is None or anchor_record is None or limit is None:
                raise TushareSourceError("INCOMPLETE_REQUIRED_MARKET_FACTS", source_code=0)
            if factor <= 0:
                raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
            _, anchor = anchor_record
            bar = validate_source_bar(source_row)
            open_price = bar["open"]
            high = bar["high"]
            low = bar["low"]
            close = bar["close"]
            volume_lots = bar["vol"]
            source_amount = bar["amount"]
            canonical_prices.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "open_raw": decimal_string(open_price, 4),
                    "high_raw": decimal_string(high, 4),
                    "low_raw": decimal_string(low, 4),
                    "close_raw": decimal_string(close, 4),
                    "pre_close_raw": decimal_string(bar["pre_close"], 4),
                    "change_raw": decimal_string(bar["change"], 4),
                    "pct_change_raw": decimal_string(bar["pct_chg"], 6),
                    "volume_shares": decimal_string(volume_lots * 100, 0),
                    "turnover_cny": decimal_string(source_amount * 1000, 2),
                    "adjustment_factor": decimal_string(factor, 6),
                    "adjustment_anchor_factor": decimal_string(anchor, 6),
                    "open_adj": adjusted_price_string(open_price, factor, anchor),
                    "high_adj": adjusted_price_string(high, factor, anchor),
                    "low_adj": adjusted_price_string(low, factor, anchor),
                    "close_adj": adjusted_price_string(close, factor, anchor),
                    "trading_state": state,
                }
            )
            price_limits.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "upper": decimal_string(decimal(limit["up_limit"]), 4),
                    "lower": decimal_string(decimal(limit["down_limit"]), 4),
                }
            )

    industries = normalize_industries(snapshot["industry_membership"])
    canonical = {
        "schema_version": "canonical-eod-v1",
        "research_calendar": sessions,
        "instruments": instruments,
        "prices": canonical_prices,
        "trading_states": trading_states,
        "price_limits": price_limits,
        "adjustment_anchors": [
            {
                "instrument_id": instrument["instrument_id"],
                "anchor_session": iso_date(anchor_by_code[str(instrument["ts_code"])][0]),
                "anchor_factor": decimal_string(
                    anchor_by_code[str(instrument["ts_code"])][1],
                    6,
                ),
            }
            for instrument in instruments
            if str(instrument["ts_code"]) in anchor_by_code
        ],
        "base_pool": base_pool,
        "liquidity_universes": liquidity_universes(
            sessions, base_pool, canonical_prices, trading_states
        ),
        "industry_membership": industries,
        "st_designations": [
            {
                **row,
                "trade_date": iso_date(str(row["trade_date"])),
                "instrument_id": f"equity:{row['ts_code']}",
            }
            for row in snapshot["st"]
            if str(row["trade_date"]) in session_set
        ],
        "field_catalog": field_catalog(sessions[-1]),
    }
    source = {
        "source": "tushare",
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "responses": {key: value for key, value in sorted(snapshot.items())},
    }
    return source, canonical


def normalize_tushare_increment(
    snapshot: Mapping[str, list[dict[str, object]]],
    prior: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    prior_calendar = prior.get("research_calendar")
    prior_instruments = prior.get("instruments")
    prior_prices = prior.get("prices")
    prior_states = prior.get("trading_states")
    prior_anchors = prior.get("adjustment_anchors")
    prior_base_pool = prior.get("base_pool")
    if not all(
        isinstance(value, list)
        for value in (
            prior_calendar,
            prior_instruments,
            prior_prices,
            prior_states,
            prior_anchors,
            prior_base_pool,
        )
    ):
        raise TushareSourceError("INVALID_PREDECESSOR_CANONICAL", source_code=0)
    last_session_key = str(prior_calendar[-1]).replace("-", "")
    sse_open = {
        str(row["cal_date"]) for row in snapshot["calendar_sse"] if str(row["is_open"]) == "1"
    }
    szse_open = {
        str(row["cal_date"]) for row in snapshot["calendar_szse"] if str(row["is_open"]) == "1"
    }
    try:
        session_keys = research_sessions_after(
            (sse_open, szse_open),
            last_session_key,
        )
    except CanonicalMappingError as error:
        raise TushareSourceError(error.detail_code, source_code=0) from error
    if not session_keys:
        raise TushareSourceError("NO_NEW_RESEARCH_SESSION", source_code=0)
    sessions = [iso_date(value) for value in session_keys]
    session_set = set(session_keys)

    instruments = normalize_instruments(snapshot["stock_basic"])
    instrument_by_code = {str(row["ts_code"]): row for row in instruments}
    prior_codes = {str(row["ts_code"]) for row in prior_instruments if isinstance(row, dict)}
    if not prior_codes <= instrument_by_code.keys():
        raise TushareSourceError("INCOMPLETE_INSTRUMENT_REFERENCE", source_code=0)
    validate_incremental_instrument_reference(
        prior_instruments,
        instruments,
        str(prior_calendar[-1]),
    )

    daily_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot["daily"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    factor_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): decimal(row["adj_factor"])
        for row in snapshot["adjustments"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    suspensions: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in snapshot["suspensions"]:
        position = (str(row["trade_date"]), str(row["ts_code"]))
        if position[0] in session_set and position[1] in instrument_by_code:
            suspensions.setdefault(position, []).append(row)
    limit_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot["price_limits"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    anchor_by_code = {
        str(item["instrument_id"]).removeprefix("equity:"): (
            str(item["anchor_session"]),
            decimal(item["anchor_factor"]),
        )
        for item in prior_anchors
        if isinstance(item, dict)
    }
    anchor_daily = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot.get("anchor_daily", [])
    }
    anchor_factors = {
        (str(row["trade_date"]), str(row["ts_code"])): decimal(row["adj_factor"])
        for row in snapshot.get("anchor_adjustments", [])
    }
    new_anchor_records: list[dict[str, str]] = []
    for code, instrument in instrument_by_code.items():
        if code in anchor_by_code:
            continue
        listed_from = str(instrument["listed_from"]).replace("-", "")
        qualifying = sorted(
            session
            for session, candidate_code in anchor_daily
            if candidate_code == code
            and session >= listed_from
            and (session, code) in anchor_factors
        )
        if not qualifying:
            raise TushareSourceError("INCOMPLETE_ADJUSTMENT_ANCHOR", source_code=0)
        anchor_session = qualifying[0]
        anchor_daily_row = anchor_daily[(anchor_session, code)]
        validate_source_bar(anchor_daily_row)
        anchor = anchor_factors[(anchor_session, code)]
        if anchor <= 0:
            raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
        anchor_by_code[code] = (iso_date(anchor_session), anchor)
        new_anchor_records.append(
            {
                "instrument_id": str(instrument["instrument_id"]),
                "anchor_session": iso_date(anchor_session),
                "anchor_factor": decimal_string(anchor, 6),
            }
        )

    canonical_prices: list[dict[str, str]] = []
    trading_states: list[dict[str, str]] = []
    price_limits: list[dict[str, str]] = []
    base_pool: list[dict[str, object]] = []
    for session_key, session in zip(session_keys, sessions, strict=True):
        active_codes = sorted(
            code
            for code, instrument in instrument_by_code.items()
            if is_active(instrument, session_key)
        )
        base_pool.append(
            {
                "session": session,
                "instrument_ids": [
                    str(instrument_by_code[code]["instrument_id"]) for code in active_codes
                ],
            }
        )
        for code in active_codes:
            instrument_id = str(instrument_by_code[code]["instrument_id"])
            source_row = daily_by_position.get((session_key, code))
            suspension = suspensions.get((session_key, code))
            state = resolve_trading_state(source_row, suspension)
            trading_states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            if source_row is None:
                continue
            factor = factor_by_position.get((session_key, code))
            anchor_record = anchor_by_code.get(code)
            limit = limit_by_position.get((session_key, code))
            if factor is None or anchor_record is None or limit is None:
                raise TushareSourceError("INCOMPLETE_REQUIRED_MARKET_FACTS", source_code=0)
            if factor <= 0:
                raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
            anchor = anchor_record[1]
            bar = validate_source_bar(source_row)
            open_price = bar["open"]
            high = bar["high"]
            low = bar["low"]
            close = bar["close"]
            volume_lots = bar["vol"]
            source_amount = bar["amount"]
            canonical_prices.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "open_raw": decimal_string(open_price, 4),
                    "high_raw": decimal_string(high, 4),
                    "low_raw": decimal_string(low, 4),
                    "close_raw": decimal_string(close, 4),
                    "pre_close_raw": decimal_string(bar["pre_close"], 4),
                    "change_raw": decimal_string(bar["change"], 4),
                    "pct_change_raw": decimal_string(bar["pct_chg"], 6),
                    "volume_shares": decimal_string(volume_lots * 100, 0),
                    "turnover_cny": decimal_string(source_amount * 1000, 2),
                    "adjustment_factor": decimal_string(factor, 6),
                    "adjustment_anchor_factor": decimal_string(anchor, 6),
                    "open_adj": adjusted_price_string(open_price, factor, anchor),
                    "high_adj": adjusted_price_string(high, factor, anchor),
                    "low_adj": adjusted_price_string(low, factor, anchor),
                    "close_adj": adjusted_price_string(close, factor, anchor),
                    "trading_state": state,
                }
            )
            price_limits.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "upper": decimal_string(decimal(limit["up_limit"]), 4),
                    "lower": decimal_string(decimal(limit["down_limit"]), 4),
                }
            )

    all_sessions = [*prior_calendar, *sessions]
    all_prices = [*prior_prices, *canonical_prices]
    all_states = [*prior_states, *trading_states]
    all_base_pool = [*prior_base_pool, *base_pool]
    universes = liquidity_universes(
        all_sessions,
        all_base_pool,
        all_prices,
        all_states,
    )
    source = {
        "source": "tushare",
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "responses": {key: value for key, value in sorted(snapshot.items())},
        "corrections": [],
    }
    current_industries = normalize_industries(snapshot["industry_membership"])
    prior_industries = prior.get("industry_membership")
    if not isinstance(prior_industries, list):
        raise TushareSourceError("INVALID_PREDECESSOR_CANONICAL", source_code=0)
    industries = merge_incremental_industries(
        prior_industries,
        current_industries,
        str(prior_calendar[-1]),
    )
    canonical_delta = {
        "research_calendar_append": sessions,
        "instruments_replace": instruments,
        "prices_append": canonical_prices,
        "trading_states_append": trading_states,
        "price_limits_append": price_limits,
        "base_pool_append": base_pool,
        "adjustment_anchors_append": new_anchor_records,
        "st_designations_append": [
            {
                **row,
                "trade_date": iso_date(str(row["trade_date"])),
                "instrument_id": f"equity:{row['ts_code']}",
            }
            for row in snapshot["st"]
            if str(row["trade_date"]) in session_set
        ],
        "liquidity_universes_append": {
            name: rows[-len(sessions) :] for name, rows in universes.items()
        },
        "liquidity_universes_replace": {},
        "industry_membership_replace": industries,
        "price_corrections": [],
    }
    return source, canonical_delta


def resolve_trading_state(
    daily_row: Mapping[str, object] | None,
    suspensions: Sequence[Mapping[str, object]] | None,
) -> str:
    if not suspensions:
        if daily_row is None:
            raise TushareSourceError("UNEXPLAINED_DAILY_ABSENCE", source_code=0)
        return "normal"
    resolved: set[str] = set()
    for suspension in suspensions:
        timing = str(suspension.get("suspend_timing", "")).strip()
        full_session = timing in {"全天", "全日", "全天停牌", "全日停牌"}
        if daily_row is None:
            if not full_session:
                raise TushareSourceError(
                    "AMBIGUOUS_SUSPENSION_EVIDENCE",
                    source_code=0,
                )
            resolved.add("full_session_suspension")
            continue
        if full_session:
            raise TushareSourceError(
                "CONTRADICTORY_SUSPENSION_EVIDENCE",
                source_code=0,
            )
        if any(marker in timing for marker in ("开盘", "盘前", "09:30", "9:30")):
            resolved.add("partial_opening_suspension")
        elif any(marker in timing for marker in ("盘中", "午间", "尾盘")):
            resolved.add("after_open_suspension")
        elif timing[:2].isdigit() and ":" in timing:
            resolved.add("after_open_suspension")
        else:
            raise TushareSourceError(
                "AMBIGUOUS_SUSPENSION_EVIDENCE",
                source_code=0,
            )
    if len(resolved) != 1:
        raise TushareSourceError("AMBIGUOUS_SUSPENSION_EVIDENCE", source_code=0)
    return resolved.pop()


def industry_history_projection(
    rows: list[object],
    through_session: str,
) -> tuple[tuple[str, ...], ...]:
    projected: list[tuple[str, ...]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TushareSourceError("INVALID_INDUSTRY_MEMBERSHIP", source_code=0)
        active_from = str(row.get("active_from", ""))
        if not active_from or active_from > through_session:
            continue
        active_to = str(row.get("active_to", ""))
        projected.append(
            (
                str(row.get("instrument_id", "")),
                active_from,
                active_to if active_to and active_to <= through_session else "",
                str(row.get("sw2021_l1", "")),
                str(row.get("sw2021_l2", "")),
                str(row.get("sw2021_l3", "")),
            )
        )
    return tuple(sorted(projected))


def merge_incremental_industries(
    prior: list[object],
    current: list[dict[str, str]],
    last_session: str,
) -> list[dict[str, str]]:
    merged = [
        {str(key): str(value) for key, value in row.items()}
        for row in prior
        if isinstance(row, dict)
    ]
    if len(merged) != len(prior):
        raise TushareSourceError("INVALID_INDUSTRY_MEMBERSHIP", source_code=0)
    by_start = {(row["instrument_id"], row["active_from"]): row for row in merged}
    for interval in current:
        key = (interval["instrument_id"], interval["active_from"])
        existing = by_start.get(key)
        if interval["active_from"] <= last_session:
            if existing is None or any(
                existing[field] != interval[field]
                for field in ("sw2021_l1", "sw2021_l2", "sw2021_l3")
            ):
                raise TushareSourceError(
                    "HISTORICAL_INDUSTRY_CORRECTION_REQUIRES_REVIEW",
                    source_code=0,
                )
            current_end = interval["active_to"]
            if current_end and current_end <= last_session:
                if existing["active_to"] != current_end:
                    raise TushareSourceError(
                        "HISTORICAL_INDUSTRY_CORRECTION_REQUIRES_REVIEW",
                        source_code=0,
                    )
            elif current_end:
                existing["active_to"] = current_end
            continue
        if existing is not None:
            continue
        candidates = [
            row
            for row in merged
            if row["instrument_id"] == interval["instrument_id"]
            and row["active_from"] < interval["active_from"]
        ]
        if candidates:
            predecessor = max(candidates, key=lambda row: row["active_from"])
            if not predecessor["active_to"] or predecessor["active_to"] > interval["active_from"]:
                predecessor["active_to"] = interval["active_from"]
        copied = dict(interval)
        merged.append(copied)
        by_start[key] = copied
    merged.sort(key=lambda row: (row["instrument_id"], row["active_from"]))
    if industry_history_projection(prior, last_session) != industry_history_projection(
        merged,
        last_session,
    ):
        raise TushareSourceError(
            "HISTORICAL_INDUSTRY_CORRECTION_REQUIRES_REVIEW",
            source_code=0,
        )
    previous_end: dict[str, str] = {}
    for interval in merged:
        prior_end = previous_end.get(interval["instrument_id"])
        if prior_end and interval["active_from"] < prior_end:
            raise TushareSourceError("OVERLAPPING_INDUSTRY_MEMBERSHIP", source_code=0)
        previous_end[interval["instrument_id"]] = interval["active_to"] or "9999-12-31"
    return merged


def validate_incremental_instrument_reference(
    prior: list[object],
    current: list[dict[str, str]],
    last_session: str,
) -> None:
    prior_by_code = {str(row["ts_code"]): row for row in prior if isinstance(row, dict)}
    if len(prior_by_code) != len(prior):
        raise TushareSourceError("INVALID_PREDECESSOR_CANONICAL", source_code=0)
    for instrument in current:
        code = instrument["ts_code"]
        predecessor = prior_by_code.get(code)
        if predecessor is None:
            if instrument["listed_from"] <= last_session:
                raise TushareSourceError(
                    "HISTORICAL_INSTRUMENT_CORRECTION_REQUIRES_REVIEW",
                    source_code=0,
                )
            continue
        if any(
            str(predecessor.get(field, "")) != instrument[field]
            for field in (
                "instrument_id",
                "asset_type",
                "exchange",
                "board",
                "listed_from",
            )
        ):
            raise TushareSourceError(
                "HISTORICAL_INSTRUMENT_CORRECTION_REQUIRES_REVIEW",
                source_code=0,
            )
        prior_end = str(predecessor.get("listed_to", ""))
        current_end = instrument["listed_to"]
        if prior_end != current_end and (
            (prior_end and prior_end <= last_session)
            or (current_end and current_end <= last_session)
        ):
            raise TushareSourceError(
                "HISTORICAL_INSTRUMENT_CORRECTION_REQUIRES_REVIEW",
                source_code=0,
            )


def normalize_instruments(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    accepted_markets = {"主板", "创业板", "科创板"}
    normalized: list[dict[str, str]] = []
    for row in rows:
        code = str(row["ts_code"])
        exchange = str(row["exchange"])
        market = str(row["market"])
        if exchange not in {"SSE", "SZSE"} or market not in accepted_markets:
            continue
        normalized.append(
            {
                "instrument_id": f"equity:{code}",
                "ts_code": code,
                "asset_type": "ordinary_a_share",
                "exchange": exchange,
                "board": normalize_board(market),
                "listed_from": iso_date(str(row["list_date"])),
                "listed_to": iso_date(str(row.get("delist_date", "")))
                if row.get("delist_date")
                else "",
            }
        )
    return sorted(normalized, key=lambda item: item["instrument_id"])


def normalize_board(market: str) -> str:
    return {"主板": "main", "创业板": "chinext", "科创板": "star"}[market]


def normalize_industries(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    intervals = [
        {
            "instrument_id": f"equity:{row['ts_code']}",
            "active_from": iso_date(str(row["in_date"])),
            "active_to": iso_date(str(row.get("out_date", ""))) if row.get("out_date") else "",
            "sw2021_l1": str(row.get("l1_code", "")),
            "sw2021_l2": str(row.get("l2_code", "")),
            "sw2021_l3": str(row.get("l3_code", "")),
        }
        for row in rows
        if row.get("ts_code") and row.get("in_date")
    ]
    intervals.sort(key=lambda item: (item["instrument_id"], item["active_from"]))
    previous: dict[str, str] = {}
    for interval in intervals:
        prior_end = previous.get(interval["instrument_id"])
        if prior_end and interval["active_from"] < prior_end:
            raise TushareSourceError("OVERLAPPING_INDUSTRY_MEMBERSHIP", source_code=0)
        previous[interval["instrument_id"]] = interval["active_to"] or "9999-12-31"
    return intervals


def is_active(instrument: Mapping[str, object], session_key: str) -> bool:
    listed_from = str(instrument["listed_from"]).replace("-", "")
    listed_to = str(instrument["listed_to"]).replace("-", "")
    return listed_from <= session_key and (not listed_to or session_key < listed_to)


def iso_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise TushareSourceError("INVALID_DATE", source_code=0)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as error:
        raise TushareSourceError("INVALID_DECIMAL", source_code=0) from error
    if not result.is_finite():
        raise TushareSourceError("INVALID_DECIMAL", source_code=0)
    return result


def validate_source_bar(row: Mapping[str, object]) -> dict[str, Decimal]:
    values = {
        field: decimal(row[field])
        for field in (
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        )
    }
    if (
        min(
            values["open"],
            values["high"],
            values["low"],
            values["close"],
            values["pre_close"],
        )
        <= 0
        or values["low"] > values["high"]
        or values["open"] < values["low"]
        or values["open"] > values["high"]
        or values["close"] < values["low"]
        or values["close"] > values["high"]
        or values["vol"] < 0
        or values["amount"] < 0
    ):
        raise TushareSourceError("INVALID_DAILY_BAR", source_code=0)
    return values
