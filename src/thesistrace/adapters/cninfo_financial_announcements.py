from __future__ import annotations

import re
import time
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from importlib import import_module
from math import isfinite
from threading import RLock
from typing import Protocol, cast

from requests import Response
from requests.exceptions import (
    ChunkedEncodingError,
    HTTPError,
    JSONDecodeError,
    RequestException,
    SSLError,
    Timeout,
)
from requests.exceptions import ConnectionError as RequestConnectionError

from thesistrace.data.financial_announcements import (
    FINANCIAL_ANNOUNCEMENT_CATEGORIES,
    FinancialAnnouncement,
    FinancialAnnouncementDiscovery,
    FinancialDiscoveryGap,
    financial_announcement_id,
    financial_discovery_lineage_sha256,
)
from thesistrace.operational_events import (
    emit_operational_event_data,
    non_blocking_operational_event_sink,
)

_EXPECTED_COLUMNS = frozenset({"代码", "简称", "公告标题", "公告时间", "公告链接"})
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_RETRY_WAIT_SECONDS = 30
_emit_cninfo_event = non_blocking_operational_event_sink(
    emit_operational_event_data, component="data_operator"
)


class _Frame(Protocol):
    columns: object

    def to_dict(self, *, orient: str) -> list[dict[str, object]]: ...


class _AkshareClient(Protocol):
    def stock_zh_a_disclosure_report_cninfo(
        self,
        *,
        symbol: str,
        market: str,
        category: str,
        start_date: str,
        end_date: str,
    ) -> _Frame: ...


class _RequestsTransport(Protocol):
    def get(self, *args: object, **kwargs: object) -> Response: ...

    def post(self, *args: object, **kwargs: object) -> Response: ...


class _RequestsWithRetry:
    def __init__(
        self, transport: _RequestsTransport, timeout_seconds: float, max_attempts: int
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    def get(self, *args: object, **kwargs: object) -> Response:
        return self._request("GET", args, kwargs)

    def post(self, *args: object, **kwargs: object) -> Response:
        return self._request("POST", args, kwargs)

    def _request(
        self, method: str, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> Response:
        kwargs.setdefault("timeout", self._timeout_seconds)
        request = self._transport.get if method == "GET" else self._transport.post
        for attempt in range(1, self._max_attempts + 1):
            response = None
            try:
                response = request(*args, **kwargs)
                response.raise_for_status()
                # AKShare decodes outside its request call. Validate here so a truncated
                # or non-JSON response retries this page, not the entire category.
                response.json()
                return response
            except RequestException as error:
                status_code = response.status_code if response is not None else None
                delay = _retry_delay(response, attempt)
                retry = (
                    attempt < self._max_attempts
                    and _request_is_retryable(error, status_code)
                    and delay is not None
                )
                if response is not None:
                    response.close()
                _emit_cninfo_event(
                    {
                        "event": "cninfo_request_retry" if retry else "cninfo_request_failed",
                        "level": "WARNING" if retry else "ERROR",
                        "phase": "discovery",
                        "outcome": "retry_scheduled" if retry else "failed",
                        "attempt_number": attempt,
                        "exception_type": type(error).__name__,
                        "status_code": status_code,
                        "method": method,
                    }
                )
                if not retry:
                    raise
                assert delay is not None
                time.sleep(delay)
        raise AssertionError("CNINFO retry loop exhausted")


def _request_is_retryable(error: RequestException, status_code: int | None) -> bool:
    if isinstance(error, SSLError):
        return False
    if isinstance(error, HTTPError):
        return status_code in _RETRYABLE_STATUS_CODES
    return isinstance(
        error, (RequestConnectionError, Timeout, JSONDecodeError, ChunkedEncodingError)
    )


def _retry_delay(response: Response | None, attempt: int) -> float | None:
    delay = float(min(2 ** min(attempt - 1, 5), _MAX_RETRY_WAIT_SECONDS))
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after is not None:
        try:
            if retry_after.isascii() and retry_after.isdigit():
                requested = float(retry_after)
            else:
                until = parsedate_to_datetime(retry_after)
                if until.tzinfo is None:
                    return None
                requested = max(0.0, (until - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
        if not isfinite(requested) or requested > _MAX_RETRY_WAIT_SECONDS:
            return None
        delay = max(delay, requested)
    return delay


_AKSHARE_TRANSPORT_LOCK = RLock()


class _BoundedAkshareClient:
    def __init__(self, client: _AkshareClient, timeout_seconds: float, max_attempts: int) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    def stock_zh_a_disclosure_report_cninfo(
        self,
        *,
        symbol: str,
        market: str,
        category: str,
        start_date: str,
        end_date: str,
    ) -> _Frame:
        module = import_module("akshare.stock_feature.stock_disclosure_cninfo")
        with _AKSHARE_TRANSPORT_LOCK:
            transport = cast(_RequestsTransport, module.requests)
            module.requests = _RequestsWithRetry(  # type: ignore[attr-defined]
                transport,
                self._timeout_seconds,
                self._max_attempts,
            )
            try:
                return self._client.stock_zh_a_disclosure_report_cninfo(
                    symbol=symbol,
                    market=market,
                    category=category,
                    start_date=start_date,
                    end_date=end_date,
                )
            finally:
                module.requests = transport  # type: ignore[attr-defined]


class AkshareCninfoFinancialAnnouncementSource:
    def __init__(
        self,
        client: _AkshareClient | None = None,
        *,
        timeout_seconds: float = 30,
        max_attempts: int = 3,
    ) -> None:
        timeout = float(timeout_seconds)
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("CNINFO request timeout must be positive and finite")
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("CNINFO max_attempts must be a positive integer")
        if client is None:
            import akshare

            client = _BoundedAkshareClient(akshare, timeout, max_attempts)
        self._client = client

    def discover(
        self,
        *,
        start_date: str,
        end_date: str,
        allowed_ts_codes: set[str] | frozenset[str],
    ) -> FinancialAnnouncementDiscovery:
        start = _iso_date(start_date)
        end = _iso_date(end_date)
        if start > end:
            raise ValueError("financial discovery window is invalid")
        allowed = {value.split(".", 1)[0]: value for value in sorted(allowed_ts_codes)}
        announcements: dict[str, FinancialAnnouncement] = {}
        completed_categories: list[str] = []
        gaps: list[FinancialDiscoveryGap] = []
        for category in FINANCIAL_ANNOUNCEMENT_CATEGORIES:
            category_announcements: dict[str, FinancialAnnouncement] = {}
            try:
                frame = self._client.stock_zh_a_disclosure_report_cninfo(
                    symbol="",
                    market="沪深京",
                    category=category,
                    start_date=start.replace("-", ""),
                    end_date=end.replace("-", ""),
                )
                columns = set(frame.columns)
                if not _EXPECTED_COLUMNS.issubset(columns):
                    raise ValueError("CNINFO_FINANCIAL_ANNOUNCEMENT_SCHEMA_INVALID")
                for raw in frame.to_dict(orient="records"):
                    code = str(raw["代码"]).strip().zfill(6)
                    ts_code = allowed.get(code)
                    if ts_code is None:
                        continue
                    title = str(raw["公告标题"]).strip()
                    published = _source_date(raw["公告时间"])
                    name = str(raw["简称"]).strip()
                    url = str(raw["公告链接"]).strip()
                    announcement_id = financial_announcement_id(
                        category=category,
                        ts_code=ts_code,
                        name=name,
                        title=title,
                        source_published_date=published,
                        url=url,
                    )
                    category_announcements.setdefault(
                        announcement_id,
                        FinancialAnnouncement(
                            announcement_id=announcement_id,
                            category=category,
                            ts_code=ts_code,
                            name=name,
                            title=title,
                            source_published_date=published,
                            report_period=_report_period(category, title),
                            url=url,
                        ),
                    )
            except Exception as error:
                gaps.append(
                    FinancialDiscoveryGap(
                        category=category,
                        start_date=start,
                        end_date=end,
                        failure_code=_discovery_failure_code(error),
                    )
                )
                continue
            completed_categories.append(category)
            announcements.update(category_announcements)
        ordered = tuple(
            sorted(
                announcements.values(),
                key=lambda item: (
                    item.ts_code,
                    item.source_published_date,
                    item.category,
                    item.announcement_id,
                ),
            )
        )
        lineage = financial_discovery_lineage_sha256(
            start_date=start,
            end_date=end,
            completed_categories=tuple(completed_categories),
            announcement_ids=tuple(item.announcement_id for item in ordered),
            gaps=tuple(gaps),
        )
        return FinancialAnnouncementDiscovery(
            start_date=start,
            end_date=end,
            completed_categories=tuple(completed_categories),
            announcements=ordered,
            gaps=tuple(gaps),
            source_lineage_sha256=lineage,
        )


def _iso_date(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _source_date(value: object) -> str:
    candidate = str(value).strip()[:10]
    return date.fromisoformat(candidate).isoformat()


def _report_period(category: str, title: str) -> str | None:
    year = re.search(r"(?<!\d)(20\d{2})(?!\d)\s*年?", title)
    if year is None:
        return None
    suffix = {
        "年报": "12-31",
        "半年报": "06-30",
        "一季报": "03-31",
        "三季报": "09-30",
    }.get(category)
    if suffix is None:
        if "半年度" in title:
            suffix = "06-30"
        elif "第一季度" in title or "一季度" in title:
            suffix = "03-31"
        elif "第三季度" in title or "三季度" in title:
            suffix = "09-30"
        elif "年度" in title or "年报" in title:
            suffix = "12-31"
    return None if suffix is None else f"{year.group(1)}-{suffix}"


def _discovery_failure_code(error: Exception) -> str:
    if isinstance(error, (TimeoutError, ConnectionError)) or type(error).__module__.startswith(
        ("requests.", "urllib3.")
    ):
        return "CNINFO_DISCOVERY_UNAVAILABLE"
    return "CNINFO_DISCOVERY_INVALID"


__all__ = ("AkshareCninfoFinancialAnnouncementSource",)
