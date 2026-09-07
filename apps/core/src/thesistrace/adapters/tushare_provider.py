"""Tushare transport, collection, and canonical normalization adapter."""

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import httpx

from thesistrace.benchmark import (
    BENCHMARK_SOURCE_API_NAME,
    BENCHMARK_SOURCE_FIELDS,
    BENCHMARK_TS_CODE,
)
from thesistrace.data.canonical_mapping import (
    CanonicalMappingError,
    adjusted_price_string,
    bootstrap_research_calendar,
    decimal_string,
    field_catalog,
    liquidity_universes,
    research_sessions_after,
)
from thesistrace.data.generation_files import AddressedFileError, AddressedFileStore
from thesistrace.data.source import RawSourceError, RawSourceResponse


def tushare_source_error_category(reason_code: str) -> str:
    if reason_code in {"TOKEN_MISSING", "MISSING_PERMISSION"}:
        return "authorization"
    if reason_code in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_RATE_LIMITED"}:
        return "unavailable"
    return "invalid_source_data"


SOURCE_CONTRACT_VERSION = "tushare-market-v1"
_BOOTSTRAP_CHECKPOINT_FORMAT = "thesistrace-tushare-bootstrap-checkpoint"
_BOOTSTRAP_CHECKPOINT_MAX_BYTES = 128 * 1024 * 1024
_BOOTSTRAP_MARKET_SESSION_MAX_BYTES = 32 * 1024 * 1024
_DEFAULT_PAGE_SIZE = 5_000
_ENDPOINT_PAGE_SIZES = {
    "daily": 6_000,
    "stk_limit": 5_800,
    "index_member_all": 2_000,
}
_SOURCE_TIME_PATTERN = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")


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


class TushareSourceError(RawSourceError):
    def __init__(
        self,
        reason_code: str,
        *,
        source_code: int | None,
        contract: str | None = None,
        api_name: str | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.source_code = source_code
        self.contract = contract
        self.api_name = api_name

    def diagnostic(self) -> dict[str, object]:
        diagnostic: dict[str, object] = {
            "reason_code": self.reason_code,
            "source_code": self.source_code,
        }
        if self.contract is not None:
            diagnostic["contract"] = self.contract
        if self.api_name is not None:
            diagnostic["api_name"] = self.api_name
        return diagnostic


@dataclass(frozen=True)
class PermissionProbe:
    contract: str
    api_name: str
    params: dict[str, object]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class TushareBootstrapArchive:
    request_start: date
    request_end: date
    foundation: dict[str, list[dict[str, object]]]
    sessions: tuple[str, ...]
    source_lineage: dict[str, object]
    _load_session: Callable[[str], dict[str, list[dict[str, object]]]]

    def load_session(self, session: str) -> dict[str, list[dict[str, object]]]:
        if session not in self.sessions:
            raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
        return self._load_session(session)

    def materialize(self) -> dict[str, list[dict[str, object]]]:
        market_facts = {
            "daily": [],
            "adjustments": [],
            "suspensions": [],
            "price_limits": [],
        }
        for session in self.sessions:
            facts = self.load_session(session)
            for name in market_facts:
                market_facts[name].extend(facts[name])
        return {
            **self.foundation,
            **market_facts,
        }


class TushareSessionNormalizer:
    def __init__(self, instruments: Sequence[Mapping[str, object]]) -> None:
        self._instrument_by_code = {
            str(row["ts_code"]): dict(row) for row in instruments
        }
        self._prior_state_by_code: dict[str, str] = {}

    def normalize(
        self,
        session_key: str,
        market_facts: Mapping[str, list[dict[str, object]]],
    ) -> dict[str, object]:
        session = iso_date(session_key)
        daily = {
            str(row["ts_code"]): row
            for row in market_facts["daily"]
            if str(row["trade_date"]) == session_key
            and str(row["ts_code"]) in self._instrument_by_code
        }
        factors = {
            str(row["ts_code"]): decimal(row["adj_factor"])
            for row in market_facts["adjustments"]
            if str(row["trade_date"]) == session_key
            and str(row["ts_code"]) in self._instrument_by_code
        }
        suspensions: dict[str, list[dict[str, object]]] = {}
        for row in market_facts["suspensions"]:
            code = str(row["ts_code"])
            if str(row["trade_date"]) == session_key and code in self._instrument_by_code:
                suspensions.setdefault(code, []).append(row)
        limits = {
            str(row["ts_code"]): row
            for row in market_facts["price_limits"]
            if str(row["trade_date"]) == session_key
            and str(row["ts_code"]) in self._instrument_by_code
        }
        active_codes = sorted(
            code
            for code, instrument in self._instrument_by_code.items()
            if is_active(instrument, session_key)
        )
        prices: list[dict[str, str]] = []
        states: list[dict[str, str]] = []
        price_limits: list[dict[str, str]] = []
        for code in active_codes:
            instrument_id = str(self._instrument_by_code[code]["instrument_id"])
            source_row = daily.get(code)
            state = resolve_trading_state(
                source_row,
                suspensions.get(code),
                previous_state=self._prior_state_by_code.get(code),
            )
            factor = factors.get(code) if source_row is not None else None
            limit = limits.get(code) if source_row is not None else None
            if source_row is not None and (factor is None or limit is None):
                state = "data_unavailable"
            self._prior_state_by_code[code] = state
            states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            if source_row is None or factor is None:
                continue
            if factor <= 0:
                raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
            bar = validate_source_bar(source_row)
            prices.append(
                {
                    "session": session,
                    "instrument_id": instrument_id,
                    "open_raw": decimal_string(bar["open"], 4),
                    "high_raw": decimal_string(bar["high"], 4),
                    "low_raw": decimal_string(bar["low"], 4),
                    "close_raw": decimal_string(bar["close"], 4),
                    "pre_close_raw": decimal_string(bar["pre_close"], 4),
                    "change_raw": decimal_string(bar["change"], 4),
                    "pct_change_raw": decimal_string(bar["pct_chg"], 6),
                    "volume_shares": decimal_string(bar["vol"] * 100, 0),
                    "turnover_cny": decimal_string(bar["amount"] * 1000, 2),
                    "adjustment_factor": decimal_string(factor, 6),
                    "trading_state": state,
                }
            )
            if limit is not None:
                price_limits.append(
                    {
                        "session": session,
                        "instrument_id": instrument_id,
                        "upper": decimal_string(decimal(limit["up_limit"]), 4),
                        "lower": decimal_string(decimal(limit["down_limit"]), 4),
                    }
                )
        return {
            "prices": causal_adjusted_prices(prices),
            "trading_states": states,
            "price_limits": price_limits,
            "base_pool": [
                {
                    "session": session,
                    "instrument_ids": [
                        str(self._instrument_by_code[code]["instrument_id"])
                        for code in active_codes
                    ],
                }
            ],
        }


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
            {"trade_date": current_text, "suspend_type": "S"},
            ("ts_code", "trade_date", "suspend_type"),
        ),
        PermissionProbe(
            "price_limit",
            "stk_limit",
            {"trade_date": current_text},
            ("trade_date", "ts_code", "pre_close", "up_limit", "down_limit"),
        ),
        PermissionProbe(
            "benchmark_csi300_price_index_open",
            BENCHMARK_SOURCE_API_NAME,
            {
                "ts_code": BENCHMARK_TS_CODE,
                "start_date": current_text,
                "end_date": current_text,
            },
            BENCHMARK_SOURCE_FIELDS,
        ),
    )


class TushareAdapter:
    def __init__(
        self,
        *,
        token: str,
        transport: TushareTransport,
        page_size: int | None = None,
        throttle_seconds: float = 60 / 180,
        rate_limit_backoff_seconds: float = 2.0,
        max_attempts: int = 6,
        sleeper: Callable[[float], None] = time.sleep,
        progress: Callable[[dict[str, object]], None] | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
        bootstrap_checkpoint: Path | None = None,
    ) -> None:
        if not token:
            raise TushareSourceError("TOKEN_MISSING", source_code=None)
        self._token = token
        self._transport = transport
        self._page_size_override = page_size
        self._throttle_seconds = throttle_seconds
        self._last_request_started_at: float | None = None
        self._rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._progress = progress or (lambda _event: None)
        self._monotonic = monotonic
        self._bootstrap_checkpoint = bootstrap_checkpoint

    def clear_bootstrap_checkpoint(self) -> None:
        if self._bootstrap_checkpoint is None:
            return
        try:
            self._bootstrap_checkpoint.unlink(missing_ok=True)
            shutil.rmtree(_bootstrap_market_root(self._bootstrap_checkpoint), ignore_errors=False)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise TushareSourceError(
                "BOOTSTRAP_CHECKPOINT_CLEANUP_FAILED",
                source_code=0,
            ) from error

    def preflight(self) -> dict[str, object]:
        permissions: list[dict[str, str]] = []
        for probe in permission_probes():
            try:
                self.query(probe.api_name, params=probe.params, fields=probe.fields)
            except TushareSourceError as error:
                error.contract = probe.contract
                error.api_name = probe.api_name
                raise
            permissions.append(
                {
                    "contract": probe.contract,
                    "api_name": probe.api_name,
                    "status": "available",
                }
            )
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
    ) -> TushareBootstrapArchive:
        checkpoint = _load_bootstrap_checkpoint(
            self._bootstrap_checkpoint,
            start_date=start_date,
            completed_through_date=completed_through_date,
        )
        if checkpoint is None:
            foundation = self._collect_bootstrap_foundation(
                start_date=start_date,
                completed_through_date=completed_through_date,
            )
            _save_bootstrap_checkpoint(
                self._bootstrap_checkpoint,
                start_date=start_date,
                completed_through_date=completed_through_date,
                foundation=foundation,
                market_sessions={},
            )
            market_sessions: dict[str, dict[str, object]] = {}
            if self._bootstrap_checkpoint is not None:
                self._progress(
                    {
                        "event": "collection_phase",
                        "phase": "bootstrap_checkpoint",
                        "status": "saved",
                        "request_start": start_date.isoformat(),
                        "request_end": completed_through_date.isoformat(),
                    }
                )
        else:
            foundation = checkpoint["foundation"]
            market_sessions = checkpoint["market_sessions"]
            self._progress(
                {
                    "event": "collection_phase",
                    "phase": "bootstrap_checkpoint",
                    "status": "restored",
                    "request_start": start_date.isoformat(),
                    "request_end": completed_through_date.isoformat(),
                }
            )

        sse_calendar = foundation["calendar_sse"]
        szse_calendar = foundation["calendar_szse"]
        stock_basic = foundation["stock_basic"]
        shared_open = sorted(
            {str(row["cal_date"]) for row in sse_calendar if str(row["is_open"]) == "1"}
            & {str(row["cal_date"]) for row in szse_calendar if str(row["is_open"]) == "1"}
        )
        if not shared_open:
            raise TushareSourceError("INSUFFICIENT_CALENDAR_COVERAGE", source_code=0)

        self._progress({"event": "collection_phase", "phase": "market_facts", "status": "started"})
        market_row_counts, in_memory_sessions = self._collect_market_facts(
            shared_open,
            checkpoint_path=self._bootstrap_checkpoint,
            start_date=start_date,
            completed_through_date=completed_through_date,
            foundation=foundation,
            market_sessions=market_sessions,
        )
        self._progress(
            {
                "event": "collection_phase",
                "phase": "market_facts",
                "status": "completed",
                "daily_rows": market_row_counts["daily"],
                "adjustment_rows": market_row_counts["adjustments"],
                "suspension_rows": market_row_counts["suspensions"],
                "price_limit_rows": market_row_counts["price_limits"],
            }
        )

        foundation = {
            "calendar_sse": sse_calendar,
            "calendar_szse": szse_calendar,
            "stock_basic": stock_basic,
        }

        def load_session(session: str) -> dict[str, list[dict[str, object]]]:
            if self._bootstrap_checkpoint is None:
                try:
                    return in_memory_sessions[session]
                except KeyError as error:
                    raise TushareSourceError(
                        "INVALID_BOOTSTRAP_CHECKPOINT", source_code=0
                    ) from error
            facts = _load_market_session_checkpoint(
                self._bootstrap_checkpoint,
                session=session,
                descriptor=market_sessions.get(session),
                start_date=start_date,
                completed_through_date=completed_through_date,
            )
            if facts is None:
                raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
            return facts

        return TushareBootstrapArchive(
            request_start=start_date,
            request_end=completed_through_date,
            foundation=foundation,
            sessions=tuple(shared_open),
            source_lineage={
                "source": "tushare",
                "source_contract_version": SOURCE_CONTRACT_VERSION,
                "request_start": start_date.isoformat(),
                "request_end": completed_through_date.isoformat(),
                "foundation_row_counts": {
                    name: len(rows) for name, rows in sorted(foundation.items())
                },
                "market_session_content": {
                    session: dict(descriptor)
                    for session, descriptor in sorted(market_sessions.items())
                },
                "market_row_counts": dict(market_row_counts),
            },
            _load_session=load_session,
        )

    def _collect_bootstrap_foundation(
        self,
        *,
        start_date: date,
        completed_through_date: date,
    ) -> dict[str, list[dict[str, object]]]:
        end_date = completed_through_date.strftime("%Y%m%d")
        calendar_start = start_date.strftime("%Y%m%d")
        self._progress(
            {
                "event": "collection_phase",
                "phase": "calendar",
                "status": "started",
                "request_start": start_date.isoformat(),
                "request_end": completed_through_date.isoformat(),
            }
        )
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
        latest_open_session = shared_open[-1]
        self._progress(
            {
                "event": "collection_phase",
                "phase": "calendar",
                "status": "completed",
                "research_session_count": len(shared_open),
                "latest_open_session": latest_open_session,
            }
        )

        self._progress(
            {"event": "collection_phase", "phase": "instrument_reference", "status": "started"}
        )
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
        self._progress(
            {
                "event": "collection_phase",
                "phase": "instrument_reference",
                "status": "completed",
                "instrument_count": len(stock_basic),
            }
        )
        return {
            "calendar_sse": sse_calendar,
            "calendar_szse": szse_calendar,
            "stock_basic": stock_basic,
        }

    def collect_incremental_snapshot(
        self,
        *,
        last_session: str,
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
        ranged = {"start_date": start_date, "end_date": end_date}
        calendar_sse = self.query_paginated(
            "trade_cal",
            params={"exchange": "SSE", **ranged},
            fields=("exchange", "cal_date", "is_open", "pretrade_date"),
            primary_key=("exchange", "cal_date"),
        )
        calendar_szse = self.query_paginated(
            "trade_cal",
            params={"exchange": "SZSE", **ranged},
            fields=("exchange", "cal_date", "is_open", "pretrade_date"),
            primary_key=("exchange", "cal_date"),
        )
        shared_open = sorted(
            {str(row["cal_date"]) for row in calendar_sse if str(row["is_open"]) == "1"}
            & {str(row["cal_date"]) for row in calendar_szse if str(row["is_open"]) == "1"}
        )
        _row_counts, market_sessions = self._collect_market_facts(shared_open)
        market_facts = {
            name: [
                row
                for session in shared_open
                for row in market_sessions[session][name]
            ]
            for name in ("daily", "adjustments", "suspensions", "price_limits")
        }
        return {
            "calendar_sse": calendar_sse,
            "calendar_szse": calendar_szse,
            "stock_basic": stock_basic,
            **market_facts,
        }

    def _collect_market_facts(
        self,
        sessions: Sequence[str],
        *,
        checkpoint_path: Path | None = None,
        start_date: date | None = None,
        completed_through_date: date | None = None,
        foundation: dict[str, list[dict[str, object]]] | None = None,
        market_sessions: dict[str, dict[str, object]] | None = None,
    ) -> tuple[dict[str, int], dict[str, dict[str, list[dict[str, object]]]]]:
        row_counts = {
            "daily": 0,
            "adjustments": 0,
            "suspensions": 0,
            "price_limits": 0,
        }
        in_memory_sessions: dict[str, dict[str, list[dict[str, object]]]] = {}
        for completed_sessions, session in enumerate(sessions, start=1):
            cached = _load_market_session_checkpoint(
                checkpoint_path,
                session=session,
                descriptor=(market_sessions or {}).get(session),
                start_date=start_date,
                completed_through_date=completed_through_date,
            )
            source = "checkpoint" if cached is not None else "upstream"
            if cached is None:
                session_params = {"trade_date": session}
                cached = {
                    "daily": self.query_paginated(
                    "daily",
                    params=session_params,
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
                    params=session_params,
                    fields=("ts_code", "trade_date", "adj_factor"),
                    primary_key=("trade_date", "ts_code"),
                    ),
                    "suspensions": self.query_paginated(
                    "suspend_d",
                    params={**session_params, "suspend_type": "S"},
                    fields=("ts_code", "trade_date", "suspend_timing", "suspend_type"),
                    primary_key=("trade_date", "ts_code", "suspend_type"),
                    ),
                    "price_limits": self.query_paginated(
                    "stk_limit",
                    params=session_params,
                    fields=("trade_date", "ts_code", "pre_close", "up_limit", "down_limit"),
                    primary_key=("trade_date", "ts_code"),
                    ),
                }
                if (
                    checkpoint_path is not None
                    and start_date is not None
                    and completed_through_date is not None
                    and foundation is not None
                    and market_sessions is not None
                ):
                    market_sessions[session] = _save_market_session_checkpoint(
                        checkpoint_path,
                        session=session,
                        start_date=start_date,
                        completed_through_date=completed_through_date,
                        market_facts=cached,
                    )
                    _save_bootstrap_checkpoint(
                        checkpoint_path,
                        start_date=start_date,
                        completed_through_date=completed_through_date,
                        foundation=foundation,
                        market_sessions=market_sessions,
                    )
            for name in row_counts:
                row_counts[name] += len(cached[name])
            if checkpoint_path is None:
                in_memory_sessions[session] = cached
            self._progress(
                {
                    "event": "collection_progress",
                    "phase": "market_facts",
                    "session": session,
                    "completed_sessions": completed_sessions,
                    "total_sessions": len(sessions),
                    "source": source,
                }
            )
        return row_counts, in_memory_sessions

    def query(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> list[dict[str, object]]:
        response = self.query_raw(api_name, params=params, fields=fields)
        return [dict(zip(response.fields, row, strict=True)) for row in response.items]

    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        payload = {
            "api_name": api_name,
            "token": self._token,
            "params": dict(params),
            "fields": ",".join(fields),
        }
        try:
            result = self._request_with_retry(payload)
        except TushareSourceError as error:
            error.api_name = api_name
            raise
        data = result.get("data")
        if not isinstance(data, dict):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0, api_name=api_name)
        response_fields = data.get("fields")
        items = data.get("items")
        if not isinstance(response_fields, list) or not isinstance(items, list):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0, api_name=api_name)
        if any(not isinstance(field, str) for field in response_fields):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0, api_name=api_name)
        if not set(fields) <= set(response_fields):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0, api_name=api_name)
        if any(not isinstance(row, list) or len(row) != len(response_fields) for row in items):
            raise TushareSourceError("INVALID_RESPONSE", source_code=0, api_name=api_name)
        return RawSourceResponse(
            fields=tuple(response_fields),
            items=tuple(tuple(row) for row in items),
        )

    def query_paginated(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
        primary_key: Sequence[str],
    ) -> list[dict[str, object]]:
        page_size = self._page_size_override or _ENDPOINT_PAGE_SIZES.get(
            api_name,
            _DEFAULT_PAGE_SIZE,
        )
        started_at = self._monotonic()
        offset = 0
        page_count = 0
        rows_by_key: dict[tuple[object, ...], dict[str, object]] = {}
        while True:
            page_params = {**params, "limit": page_size, "offset": offset}
            page = self.query(api_name, params=page_params, fields=fields)
            page_count += 1
            for row in page:
                key = tuple(row.get(field) for field in primary_key)
                if any(value is None for value in key):
                    raise TushareSourceError("INVALID_PRIMARY_KEY", source_code=0)
                rows_by_key[key] = row
            if len(page) < page_size:
                break
            offset += page_size
        rows = [rows_by_key[key] for key in sorted(rows_by_key)]
        event: dict[str, object] = {
            "event": "upstream_query",
            "api_name": api_name,
            "elapsed_seconds": round(self._monotonic() - started_at, 3),
            "page_count": page_count,
            "row_count": len(rows),
        }
        if "trade_date" in params:
            event["trade_date"] = str(params["trade_date"])
        self._progress(event)
        return rows

    def _request_with_retry(self, payload: dict[str, object]) -> dict[str, object]:
        for attempt in range(1, self._max_attempts + 1):
            if self._throttle_seconds:
                # Pace starts across all endpoints/pages/retries on this provider.
                # Time spent in HTTP, processing, or backoff already counts.
                now = self._monotonic()
                if self._last_request_started_at is not None:
                    remaining = self._throttle_seconds - (now - self._last_request_started_at)
                    if remaining > 0:
                        self._sleeper(remaining)
                self._last_request_started_at = self._monotonic()
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
                raise TushareSourceError("MISSING_PERMISSION", source_code=code)
            if code == 40203:
                if attempt < self._max_attempts:
                    retry_in_seconds = self._rate_limit_backoff_seconds * (2 ** (attempt - 1))
                    self._progress(
                        {
                            "event": "rate_limited",
                            "api_name": str(payload["api_name"]),
                            "attempt": attempt,
                            "retry_in_seconds": retry_in_seconds,
                        }
                    )
                    self._sleeper(retry_in_seconds)
                    continue
                raise TushareSourceError("UPSTREAM_RATE_LIMITED", source_code=code)
            if code == 50101:
                if attempt < self._max_attempts:
                    retry_in_seconds = self._rate_limit_backoff_seconds * (2 ** (attempt - 1))
                    self._progress(
                        {
                            "event": "upstream_retry",
                            "api_name": str(payload["api_name"]),
                            "source_code": code,
                            "attempt": attempt,
                            "retry_in_seconds": retry_in_seconds,
                        }
                    )
                    self._sleeper(retry_in_seconds)
                    continue
                raise TushareSourceError("UPSTREAM_UNAVAILABLE", source_code=code)
            if code in {429, 500, -2001} and attempt < self._max_attempts:
                self._sleeper(self._throttle_seconds * attempt)
                continue
            raise TushareSourceError(
                "UPSTREAM_REJECTED",
                source_code=int(code) if isinstance(code, int) else None,
            )
        raise AssertionError("retry loop exhausted")


def _load_bootstrap_checkpoint(
    path: Path | None,
    *,
    start_date: date,
    completed_through_date: date,
) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    try:
        metadata = path.stat()
        if not path.is_file() or metadata.st_size > _BOOTSTRAP_CHECKPOINT_MAX_BYTES:
            raise ValueError("Bootstrap checkpoint is not a bounded regular file")
        payload = json.loads(path.read_text())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0) from error
    if not isinstance(payload, dict):
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
    if (
        set(payload)
        != {
            "format",
            "source_contract_version",
            "request_start",
            "request_end",
            "foundation",
            "market_sessions",
        }
        or payload.get("format") != _BOOTSTRAP_CHECKPOINT_FORMAT
        or payload.get("source_contract_version") != SOURCE_CONTRACT_VERSION
        or payload.get("request_start") != start_date.isoformat()
        or payload.get("request_end") != completed_through_date.isoformat()
    ):
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
    foundation = payload.get("foundation")
    market_sessions = payload.get("market_sessions")
    expected_tables = {
        "calendar_sse",
        "calendar_szse",
        "stock_basic",
    }
    if (
        not isinstance(foundation, dict)
        or set(foundation) != expected_tables
        or any(not isinstance(foundation[name], list) for name in expected_tables)
        or any(not isinstance(row, dict) for name in expected_tables for row in foundation[name])
        or not isinstance(market_sessions, dict)
        or any(not isinstance(session, str) for session in market_sessions)
        or any(not _valid_market_session_descriptor(value) for value in market_sessions.values())
    ):
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
    return {"foundation": foundation, "market_sessions": market_sessions}


def _save_bootstrap_checkpoint(
    path: Path | None,
    *,
    start_date: date,
    completed_through_date: date,
    foundation: dict[str, list[dict[str, object]]],
    market_sessions: Mapping[str, Mapping[str, object]],
) -> None:
    if path is None:
        return
    payload = {
        "format": _BOOTSTRAP_CHECKPOINT_FORMAT,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "request_start": start_date.isoformat(),
        "request_end": completed_through_date.isoformat(),
        "foundation": foundation,
        "market_sessions": market_sessions,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode()) > _BOOTSTRAP_CHECKPOINT_MAX_BYTES:
        raise TushareSourceError("BOOTSTRAP_CHECKPOINT_TOO_LARGE", source_code=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(serialized)
        os.replace(temporary, path)
    except OSError as error:
        raise TushareSourceError("BOOTSTRAP_CHECKPOINT_WRITE_FAILED", source_code=0) from error
    finally:
        temporary.unlink(missing_ok=True)


def _bootstrap_market_root(path: Path) -> Path:
    return path.with_name(f"{path.name}.market")


def _market_session_blob_path(path: Path, sha256: str) -> Path:
    root = _bootstrap_market_root(path)
    return root / "sha256" / sha256[:2] / f"{sha256}.json"


def _valid_market_session_descriptor(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"sha256", "byte_count"}:
        return False
    sha256 = value.get("sha256")
    byte_count = value.get("byte_count")
    return (
        isinstance(sha256, str)
        and len(sha256) == 64
        and all(character in "0123456789abcdef" for character in sha256)
        and isinstance(byte_count, int)
        and 0 < byte_count <= _BOOTSTRAP_MARKET_SESSION_MAX_BYTES
    )


def _load_market_session_checkpoint(
    path: Path | None,
    *,
    session: str,
    descriptor: object,
    start_date: date | None,
    completed_through_date: date | None,
) -> dict[str, list[dict[str, object]]] | None:
    if path is None or descriptor is None:
        return None
    if start_date is None or completed_through_date is None or not _valid_market_session_descriptor(
        descriptor
    ):
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
    assert isinstance(descriptor, dict)
    sha256 = descriptor["sha256"]
    byte_count = descriptor["byte_count"]
    assert isinstance(sha256, str)
    assert isinstance(byte_count, int)
    try:
        content = AddressedFileStore(_bootstrap_market_root(path)).read(
            _market_session_blob_path(path, sha256),
            sha256,
            expected_byte_count=byte_count,
            max_byte_count=_BOOTSTRAP_MARKET_SESSION_MAX_BYTES,
        )
        payload = json.loads(content)
    except (AddressedFileError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0) from error
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "format",
            "source_contract_version",
            "request_start",
            "request_end",
            "session",
            "market_facts",
        }
        or payload.get("format") != _BOOTSTRAP_CHECKPOINT_FORMAT
        or payload.get("source_contract_version") != SOURCE_CONTRACT_VERSION
        or payload.get("request_start") != start_date.isoformat()
        or payload.get("request_end") != completed_through_date.isoformat()
        or payload.get("session") != session
        or not _valid_market_facts(payload.get("market_facts"))
    ):
        raise TushareSourceError("INVALID_BOOTSTRAP_CHECKPOINT", source_code=0)
    market_facts = payload["market_facts"]
    assert isinstance(market_facts, dict)
    return market_facts


def _save_market_session_checkpoint(
    path: Path,
    *,
    session: str,
    start_date: date,
    completed_through_date: date,
    market_facts: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    payload = {
        "format": _BOOTSTRAP_CHECKPOINT_FORMAT,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "request_start": start_date.isoformat(),
        "request_end": completed_through_date.isoformat(),
        "session": session,
        "market_facts": market_facts,
    }
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(content) > _BOOTSTRAP_MARKET_SESSION_MAX_BYTES:
        raise TushareSourceError("BOOTSTRAP_CHECKPOINT_TOO_LARGE", source_code=0)
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        AddressedFileStore(_bootstrap_market_root(path)).store(
            _market_session_blob_path(path, sha256),
            sha256,
            content,
        )
    except AddressedFileError as error:
        raise TushareSourceError("BOOTSTRAP_CHECKPOINT_WRITE_FAILED", source_code=0) from error
    return {"sha256": sha256, "byte_count": len(content)}


def _valid_market_facts(value: object) -> bool:
    expected_tables = {"daily", "adjustments", "suspensions", "price_limits"}
    return (
        isinstance(value, dict)
        and set(value) == expected_tables
        and all(isinstance(value[name], list) for name in expected_tables)
        and all(isinstance(row, dict) for name in expected_tables for row in value[name])
    )


def causal_adjusted_prices(
    prices: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    """Derive a future-invariant adjusted coordinate from same-session facts."""
    normalized: list[dict[str, str]] = []
    for row in prices:
        factor = decimal(row["adjustment_factor"])
        if factor <= 0:
            raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
        normalized_row = dict(row)
        for field in ("open", "high", "low", "close"):
            normalized_row[f"{field}_adj"] = adjusted_price_string(
                decimal(row[f"{field}_raw"]),
                factor,
            )
        normalized.append(normalized_row)
    return normalized


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
    canonical_prices: list[dict[str, str]] = []
    trading_states: list[dict[str, str]] = []
    price_limits: list[dict[str, str]] = []
    base_pool: list[dict[str, object]] = []
    prior_state_by_code: dict[str, str] = {}
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
            state = resolve_trading_state(
                source_row,
                suspension,
                previous_state=prior_state_by_code.get(code),
            )
            factor = (
                factor_by_position.get((session_key, code))
                if source_row is not None
                else None
            )
            limit = (
                limit_by_position.get((session_key, code))
                if source_row is not None
                else None
            )
            if source_row is not None and (factor is None or limit is None):
                state = "data_unavailable"
            prior_state_by_code[code] = state
            trading_states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            if source_row is None or factor is None:
                continue
            if factor <= 0:
                raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
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
                    "trading_state": state,
                }
            )
            if limit is not None:
                price_limits.append(
                    {
                        "session": session,
                        "instrument_id": instrument_id,
                        "upper": decimal_string(decimal(limit["up_limit"]), 4),
                        "lower": decimal_string(decimal(limit["down_limit"]), 4),
                    }
                )

    canonical_prices = causal_adjusted_prices(canonical_prices)
    canonical = {
        "schema_version": "canonical-eod",
        "research_calendar": sessions,
        "instruments": instruments,
        "prices": canonical_prices,
        "trading_states": trading_states,
        "price_limits": price_limits,
        "base_pool": base_pool,
        "liquidity_universes": liquidity_universes(
            sessions, base_pool, canonical_prices, trading_states
        ),
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
    prior_base_pool = prior.get("base_pool")
    if prior.get("schema_version") != "canonical-eod" or not all(
        isinstance(value, list)
        for value in (
            prior_calendar,
            prior_instruments,
            prior_prices,
            prior_states,
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
    canonical_prices: list[dict[str, str]] = []
    trading_states: list[dict[str, str]] = []
    price_limits: list[dict[str, str]] = []
    base_pool: list[dict[str, object]] = []
    code_by_instrument_id = {
        str(row["instrument_id"]): str(row["ts_code"])
        for row in prior_instruments
        if isinstance(row, dict)
    }
    prior_state_by_code = {
        code_by_instrument_id[str(row["instrument_id"])]: str(row["state"])
        for row in prior_states
        if isinstance(row, dict) and str(row.get("instrument_id")) in code_by_instrument_id
    }
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
            state = resolve_trading_state(
                source_row,
                suspension,
                previous_state=prior_state_by_code.get(code),
            )
            factor = (
                factor_by_position.get((session_key, code))
                if source_row is not None
                else None
            )
            limit = (
                limit_by_position.get((session_key, code))
                if source_row is not None
                else None
            )
            if source_row is not None and (factor is None or limit is None):
                state = "data_unavailable"
            prior_state_by_code[code] = state
            trading_states.append(
                {"session": session, "instrument_id": instrument_id, "state": state}
            )
            if source_row is None or factor is None:
                continue
            if factor <= 0:
                raise TushareSourceError("INVALID_ADJUSTMENT_FACTOR", source_code=0)
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
                    "trading_state": state,
                }
            )
            if limit is not None:
                price_limits.append(
                    {
                        "session": session,
                        "instrument_id": instrument_id,
                        "upper": decimal_string(decimal(limit["up_limit"]), 4),
                        "lower": decimal_string(decimal(limit["down_limit"]), 4),
                    }
                )

    all_sessions = [*prior_calendar, *sessions]
    all_prices = causal_adjusted_prices([*prior_prices, *canonical_prices])
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
    canonical_delta = {
        "research_calendar_append": sessions,
        "instruments_replace": instruments,
        "prices_replace": all_prices,
        "trading_states_append": trading_states,
        "price_limits_append": price_limits,
        "base_pool_append": base_pool,
        "liquidity_universes_append": {
            name: rows[-len(sessions) :] for name, rows in universes.items()
        },
        "liquidity_universes_replace": {},
        "price_corrections": [],
    }
    return source, canonical_delta


def resolve_trading_state(
    daily_row: Mapping[str, object] | None,
    suspensions: Sequence[Mapping[str, object]] | None,
    *,
    previous_state: str | None = None,
) -> str:
    if not suspensions:
        if daily_row is None:
            if previous_state == "full_session_suspension":
                return "full_session_suspension"
            return "data_unavailable"
        return "normal"
    resolved: set[str] = set()
    for suspension in suspensions:
        timing_value = suspension.get("suspend_timing")
        timing = "" if timing_value is None else str(timing_value).strip()
        suspension_type = str(suspension.get("suspend_type", "")).strip().upper()
        full_session = timing in {"全天", "全日", "全天停牌", "全日停牌"} or (
            suspension_type == "S"
            and (not timing or _is_market_open_sentinel(timing))
        )
        if daily_row is None:
            if not full_session:
                raise TushareSourceError(
                    "AMBIGUOUS_SUSPENSION_EVIDENCE",
                    source_code=0,
                )
            resolved.add("full_session_suspension")
            continue
        if suspension_type == "S" and not timing:
            resolved.add("data_unavailable")
            continue
        if full_session:
            raise TushareSourceError(
                "CONTRADICTORY_SUSPENSION_EVIDENCE",
                source_code=0,
            )
        if any(marker in timing for marker in ("开盘", "盘前")):
            resolved.add("partial_opening_suspension")
        elif any(marker in timing for marker in ("盘中", "午间", "尾盘")):
            resolved.add("after_open_suspension")
        else:
            timed_state = _timed_suspension_state(timing)
            if timed_state is None:
                raise TushareSourceError(
                    "AMBIGUOUS_SUSPENSION_EVIDENCE",
                    source_code=0,
                )
            resolved.add(timed_state)
    if len(resolved) != 1:
        raise TushareSourceError("AMBIGUOUS_SUSPENSION_EVIDENCE", source_code=0)
    return resolved.pop()


def _is_market_open_sentinel(timing: str) -> bool:
    points = [
        (int(hour_text), int(minute_text))
        for hour_text, minute_text in _SOURCE_TIME_PATTERN.findall(timing)
    ]
    return points == [(9, 30), (9, 30)]


def _timed_suspension_state(timing: str) -> str | None:
    points: list[tuple[int, int]] = []
    for hour_text, minute_text in _SOURCE_TIME_PATTERN.findall(timing):
        hour = int(hour_text)
        minute = int(minute_text)
        if hour > 23 or minute > 59:
            return None
        points.append((hour, minute))
    if not points:
        return None
    market_open = (9, 30)
    if market_open in points:
        return "partial_opening_suspension"
    ranges = tuple(zip(points[::2], points[1::2], strict=False))
    if any(
        start <= market_open <= end
        or (end < start and (market_open >= start or market_open <= end))
        for start, end in ranges
    ):
        return "partial_opening_suspension"
    if any(point > market_open for point in points):
        return "after_open_suspension"
    return None


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
        if interval["active_from"] <= last_session and existing is not None:
            if any(
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


def normalize_industries(
    rows: list[dict[str, object]],
    *,
    allowed_codes: set[str],
) -> list[dict[str, str]]:
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
        if row.get("ts_code") and str(row["ts_code"]) in allowed_codes and row.get("in_date")
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
