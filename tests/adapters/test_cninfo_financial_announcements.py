from __future__ import annotations

import akshare
from akshare.stock_feature import stock_disclosure_cninfo
from requests.exceptions import ReadTimeout

from thesistrace.adapters.cninfo_financial_announcements import (
    AkshareCninfoFinancialAnnouncementSource,
)
from thesistrace.data.financial_announcements import (
    FINANCIAL_ANNOUNCEMENT_CATEGORIES,
    FinancialDiscoveryGap,
)


class _Frame:
    columns = ("代码", "简称", "公告标题", "公告时间", "公告链接")

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._rows


class _AkshareClient:
    def stock_zh_a_disclosure_report_cninfo(
        self,
        *,
        symbol: str,
        market: str,
        category: str,
        start_date: str,
        end_date: str,
    ) -> _Frame:
        assert symbol == ""
        assert market == "沪深京"
        assert start_date == "20260812"
        assert end_date == "20260818"
        if category != "半年报":
            return _Frame([])
        return _Frame(
            [
                {
                    "代码": "000001",
                    "简称": "平安银行",
                    "公告标题": "平安银行股份有限公司2026年半年度报告",
                    "公告时间": "2026-08-18 00:00:00",
                    "公告链接": "https://example.test/announcement/one",
                },
                {
                    "代码": "000001",
                    "简称": "平安银行",
                    "公告标题": "平安银行股份有限公司2026年半年度报告",
                    "公告时间": "2026-08-18 00:00:00",
                    "公告链接": "https://example.test/announcement/one",
                },
                {
                    "代码": "920001",
                    "简称": "范围外股票",
                    "公告标题": "范围外股票2026年半年度报告",
                    "公告时间": "2026-08-18 00:00:00",
                    "公告链接": "https://example.test/announcement/two",
                },
            ]
        )


def test_discovery_returns_deduplicated_current_instrument_triggers() -> None:
    discovery = AkshareCninfoFinancialAnnouncementSource(_AkshareClient()).discover(
        start_date="2026-08-12",
        end_date="2026-08-18",
        allowed_ts_codes={"000001.SZ"},
    )

    assert discovery.completed_categories == FINANCIAL_ANNOUNCEMENT_CATEGORIES
    assert discovery.gaps == ()
    assert len(discovery.announcements) == 1
    assert discovery.announcements[0].ts_code == "000001.SZ"
    assert discovery.announcements[0].source_published_date == "2026-08-18"
    assert discovery.announcements[0].report_period == "2026-06-30"
    assert len(discovery.announcements[0].announcement_id) == 64
    assert len(discovery.source_lineage_sha256) == 64


def test_discovery_parses_half_year_report_period_with_or_without_year_marker() -> None:
    class ReportTitleClient(_AkshareClient):
        def stock_zh_a_disclosure_report_cninfo(
            self,
            *,
            symbol: str,
            market: str,
            category: str,
            start_date: str,
            end_date: str,
        ) -> _Frame:
            if category != "半年报":
                return _Frame([])
            return _Frame(
                [
                    {
                        "代码": "000001",
                        "简称": "甲公司",
                        "公告标题": "甲公司2026半年度报告",
                        "公告时间": "2026-08-18 00:00:00",
                        "公告链接": "https://example.test/announcement/no-year-marker",
                    },
                    {
                        "代码": "000002",
                        "简称": "乙公司",
                        "公告标题": "乙公司2026半年度报告摘要",
                        "公告时间": "2026-08-18 00:00:00",
                        "公告链接": "https://example.test/announcement/summary",
                    },
                    {
                        "代码": "000003",
                        "简称": "丙公司",
                        "公告标题": "丙公司2026年半年度报告摘要",
                        "公告时间": "2026-08-18 00:00:00",
                        "公告链接": "https://example.test/announcement/with-year-marker",
                    },
                ]
            )

    discovery = AkshareCninfoFinancialAnnouncementSource(ReportTitleClient()).discover(
        start_date="2026-08-12",
        end_date="2026-08-18",
        allowed_ts_codes={"000001.SZ", "000002.SZ", "000003.SZ"},
    )

    assert [item.report_period for item in discovery.announcements] == [
        "2026-06-30",
        "2026-06-30",
        "2026-06-30",
    ]


def test_discovery_preserves_successful_categories_and_reports_failed_category_gap() -> None:
    class PartiallyUnavailableClient(_AkshareClient):
        def stock_zh_a_disclosure_report_cninfo(
            self,
            *,
            symbol: str,
            market: str,
            category: str,
            start_date: str,
            end_date: str,
        ) -> _Frame:
            if category == "半年报":
                raise TimeoutError("remote page timed out")
            if category != "年报":
                return _Frame([])
            return _Frame(
                [
                    {
                        "代码": "000001",
                        "简称": "平安银行",
                        "公告标题": "平安银行股份有限公司2025年年度报告",
                        "公告时间": "2026-04-20 00:00:00",
                        "公告链接": "https://example.test/announcement/annual",
                    }
                ]
            )

    discovery = AkshareCninfoFinancialAnnouncementSource(
        PartiallyUnavailableClient()
    ).discover(
        start_date="2026-04-14",
        end_date="2026-04-20",
        allowed_ts_codes={"000001.SZ"},
    )

    assert discovery.completed_categories == (
        "年报",
        "一季报",
        "三季报",
        "补充更正",
    )
    assert [item.report_period for item in discovery.announcements] == ["2025-12-31"]
    assert discovery.gaps == (
        FinancialDiscoveryGap(
            category="半年报",
            start_date="2026-04-14",
            end_date="2026-04-20",
            failure_code="CNINFO_DISCOVERY_UNAVAILABLE",
        ),
    )


def test_default_akshare_transport_applies_a_bounded_request_timeout(
    monkeypatch,
) -> None:
    observed_timeouts: list[float] = []

    class RequestsTransport:
        def post(self, _url: str, **kwargs: object) -> object:
            observed_timeouts.append(float(kwargs["timeout"]))
            return object()

    transport = RequestsTransport()

    def query(**_kwargs: object) -> _Frame:
        stock_disclosure_cninfo.requests.post("https://example.test", data={})
        return _Frame([])

    monkeypatch.setattr(stock_disclosure_cninfo, "requests", transport)
    monkeypatch.setattr(akshare, "stock_zh_a_disclosure_report_cninfo", query)

    discovery = AkshareCninfoFinancialAnnouncementSource(timeout_seconds=2).discover(
        start_date="2026-08-12",
        end_date="2026-08-18",
        allowed_ts_codes={"000001.SZ"},
    )

    assert discovery.completed_categories == FINANCIAL_ANNOUNCEMENT_CATEGORIES
    assert discovery.gaps == ()
    assert observed_timeouts == [2.0] * len(FINANCIAL_ANNOUNCEMENT_CATEGORIES)
    assert stock_disclosure_cninfo.requests is transport


def test_default_akshare_transport_bounds_prerequisite_get_and_query_post(
    monkeypatch,
) -> None:
    observed_requests: list[tuple[str, float]] = []

    class RequestsTransport:
        def get(self, _url: str, **kwargs: object) -> object:
            observed_requests.append(("get", float(kwargs["timeout"])))
            return object()

        def post(self, _url: str, **kwargs: object) -> object:
            observed_requests.append(("post", float(kwargs["timeout"])))
            return object()

    transport = RequestsTransport()

    def query(**_kwargs: object) -> _Frame:
        stock_disclosure_cninfo.requests.get("https://example.test/securities")
        stock_disclosure_cninfo.requests.post(
            "https://example.test/announcements", data={}
        )
        return _Frame([])

    monkeypatch.setattr(stock_disclosure_cninfo, "requests", transport)
    monkeypatch.setattr(akshare, "stock_zh_a_disclosure_report_cninfo", query)

    discovery = AkshareCninfoFinancialAnnouncementSource(timeout_seconds=2).discover(
        start_date="2026-08-12",
        end_date="2026-08-18",
        allowed_ts_codes={"000001.SZ"},
    )

    assert discovery.completed_categories == FINANCIAL_ANNOUNCEMENT_CATEGORIES
    assert discovery.gaps == ()
    assert observed_requests == [
        request
        for _category in FINANCIAL_ANNOUNCEMENT_CATEGORIES
        for request in (("get", 2.0), ("post", 2.0))
    ]
    assert stock_disclosure_cninfo.requests is transport


def test_default_akshare_timeout_is_published_as_an_unavailable_gap(
    monkeypatch,
) -> None:
    class TimedOutTransport:
        def post(self, _url: str, **_kwargs: object) -> object:
            raise ReadTimeout("CNINFO request exceeded the adapter deadline")

    transport = TimedOutTransport()

    def query(**_kwargs: object) -> _Frame:
        stock_disclosure_cninfo.requests.post("https://example.test", data={})
        return _Frame([])

    monkeypatch.setattr(stock_disclosure_cninfo, "requests", transport)
    monkeypatch.setattr(akshare, "stock_zh_a_disclosure_report_cninfo", query)

    discovery = AkshareCninfoFinancialAnnouncementSource(timeout_seconds=2).discover(
        start_date="2026-08-12",
        end_date="2026-08-18",
        allowed_ts_codes={"000001.SZ"},
    )

    assert discovery.completed_categories == ()
    assert [gap.failure_code for gap in discovery.gaps] == [
        "CNINFO_DISCOVERY_UNAVAILABLE"
    ] * len(FINANCIAL_ANNOUNCEMENT_CATEGORIES)
    assert stock_disclosure_cninfo.requests is transport
