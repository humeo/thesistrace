from __future__ import annotations

import re
from datetime import date
from importlib import import_module
from math import isfinite
from threading import RLock
from typing import Protocol, cast

from thesistrace.data.financial_announcements import (
    FINANCIAL_ANNOUNCEMENT_CATEGORIES,
    FinancialAnnouncement,
    FinancialAnnouncementDiscovery,
    FinancialDiscoveryGap,
    financial_announcement_id,
    financial_discovery_lineage_sha256,
)

_EXPECTED_COLUMNS = frozenset({"代码", "简称", "公告标题", "公告时间", "公告链接"})


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
    def get(self, *args: object, **kwargs: object) -> object: ...

    def post(self, *args: object, **kwargs: object) -> object: ...


class _RequestsWithTimeout:
    def __init__(self, transport: _RequestsTransport, timeout_seconds: float) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def get(self, *args: object, **kwargs: object) -> object:
        kwargs.setdefault("timeout", self._timeout_seconds)
        return self._transport.get(*args, **kwargs)

    def post(self, *args: object, **kwargs: object) -> object:
        kwargs.setdefault("timeout", self._timeout_seconds)
        return self._transport.post(*args, **kwargs)


_AKSHARE_TRANSPORT_LOCK = RLock()


class _BoundedAkshareClient:
    def __init__(self, client: _AkshareClient, timeout_seconds: float) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

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
            module.requests = _RequestsWithTimeout(  # type: ignore[attr-defined]
                transport,
                self._timeout_seconds,
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
    ) -> None:
        timeout = float(timeout_seconds)
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("CNINFO request timeout must be positive and finite")
        if client is None:
            import akshare

            client = _BoundedAkshareClient(akshare, timeout)
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
    year = re.search(r"(?<!\d)(20\d{2})\s*年", title)
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


__all__ = (
    "AkshareCninfoFinancialAnnouncementSource",
)
