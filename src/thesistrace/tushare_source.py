import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import httpx

from thesistrace.fixture import decimal_string, field_catalog, liquidity_universes

SOURCE_CONTRACT_VERSION = "tushare-v1"


class TushareTransport(Protocol):
    def post(self, payload: Mapping[str, object]) -> dict[str, object]: ...


class HttpTushareTransport:
    def __init__(self, endpoint: str = "https://api.tushare.pro", timeout_seconds: float = 30):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def post(self, payload: Mapping[str, object]) -> dict[str, object]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.endpoint, json=dict(payload))
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise TushareSourceError("INVALID_RESPONSE", source_code=None)
        return result


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

    def collect_bootstrap_snapshot(self, as_of: date) -> dict[str, list[dict[str, object]]]:
        end_date = as_of.strftime("%Y%m%d")
        calendar_start = as_of.replace(year=as_of.year - 5).strftime("%Y%m%d")
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
        common = sorted(
            {str(row["cal_date"]) for row in sse_calendar if str(row["is_open"]) == "1"}
            & {str(row["cal_date"]) for row in szse_calendar if str(row["is_open"]) == "1"}
        )
        if len(common) < 756:
            raise TushareSourceError("INSUFFICIENT_CALENDAR_COVERAGE", source_code=0)
        sessions = common[-756:]
        start_date = sessions[0]

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

        return {
            "calendar_sse": sse_calendar,
            "calendar_szse": szse_calendar,
            "stock_basic": stock_basic,
            "daily": self.query_paginated(
                "daily",
                params={"start_date": start_date, "end_date": end_date},
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
                params={"start_date": start_date, "end_date": end_date},
                fields=("ts_code", "trade_date", "adj_factor"),
                primary_key=("trade_date", "ts_code"),
            ),
            "suspensions": self.query_paginated(
                "suspend_d",
                params={"start_date": start_date, "end_date": end_date},
                fields=("ts_code", "trade_date", "suspend_timing", "suspend_type"),
                primary_key=("trade_date", "ts_code", "suspend_type"),
            ),
            "st": self.query_paginated(
                "stock_st",
                params={"start_date": start_date, "end_date": end_date},
                fields=("ts_code", "name", "trade_date", "type", "type_name"),
                primary_key=("trade_date", "ts_code"),
            ),
            "price_limits": self.query_paginated(
                "stk_limit",
                params={"start_date": start_date, "end_date": end_date},
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
    session_keys = sorted(sse_open & szse_open)[-756:]
    if len(session_keys) != 756:
        raise TushareSourceError("INSUFFICIENT_CALENDAR_COVERAGE", source_code=0)
    sessions = [iso_date(value) for value in session_keys]
    session_set = set(session_keys)

    instruments = normalize_instruments(snapshot["stock_basic"])
    instrument_by_code = {str(row["ts_code"]): row for row in instruments}
    if len(instruments) < 30:
        raise TushareSourceError("INSUFFICIENT_INSTRUMENT_COVERAGE", source_code=0)

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
    suspensions = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot["suspensions"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    limit_by_position = {
        (str(row["trade_date"]), str(row["ts_code"])): row
        for row in snapshot["price_limits"]
        if str(row["trade_date"]) in session_set and str(row["ts_code"]) in instrument_by_code
    }
    anchor_by_code: dict[str, Decimal] = {}
    for code in instrument_by_code:
        factors = [
            factor
            for (trade_date, ts_code), factor in factor_by_position.items()
            if ts_code == code and trade_date in session_set
        ]
        if factors:
            anchor_by_code[code] = factors[-1]

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
            if source_row is None:
                if suspension is None:
                    raise TushareSourceError("UNEXPLAINED_DAILY_ABSENCE", source_code=0)
                trading_states.append(
                    {
                        "session": session,
                        "instrument_id": instrument_id,
                        "state": "full_session_suspension",
                    }
                )
                continue
            state = "normal" if suspension is None else "after_open_suspension"
            trading_states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            factor = factor_by_position.get((session_key, code))
            anchor = anchor_by_code.get(code)
            limit = limit_by_position.get((session_key, code))
            if factor is None or anchor is None or limit is None:
                raise TushareSourceError("INCOMPLETE_REQUIRED_MARKET_FACTS", source_code=0)
            scale = factor / anchor
            open_price = decimal(source_row["open"])
            high = decimal(source_row["high"])
            low = decimal(source_row["low"])
            close = decimal(source_row["close"])
            volume_lots = decimal(source_row["vol"])
            source_amount = decimal(source_row["amount"])
            canonical_prices.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "open_raw": decimal_string(open_price, 4),
                    "high_raw": decimal_string(high, 4),
                    "low_raw": decimal_string(low, 4),
                    "close_raw": decimal_string(close, 4),
                    "pre_close_raw": decimal_string(decimal(source_row["pre_close"]), 4),
                    "change_raw": decimal_string(decimal(source_row["change"]), 4),
                    "pct_change_raw": decimal_string(decimal(source_row["pct_chg"]), 6),
                    "volume_shares": decimal_string(volume_lots * 100, 0),
                    "turnover_cny": decimal_string(source_amount * 1000, 2),
                    "adjustment_factor": decimal_string(factor, 6),
                    "adjustment_anchor_factor": decimal_string(anchor, 6),
                    "open_adj": decimal_string(open_price * scale, 8),
                    "high_adj": decimal_string(high * scale, 8),
                    "low_adj": decimal_string(low * scale, 8),
                    "close_adj": decimal_string(close * scale, 8),
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
                "anchor_session": sessions[-1],
                "anchor_factor": decimal_string(anchor_by_code[str(instrument["ts_code"])], 6),
            }
            for instrument in instruments
            if str(instrument["ts_code"]) in anchor_by_code
        ],
        "base_pool": base_pool,
        "liquidity_universes": liquidity_universes(
            sessions, instruments, canonical_prices, trading_states
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
        return Decimal(str(value))
    except Exception as error:
        raise TushareSourceError("INVALID_DECIMAL", source_code=0) from error
