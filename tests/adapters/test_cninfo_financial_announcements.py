from __future__ import annotations

import json
from datetime import UTC, datetime

import akshare
import pytest
from akshare.stock_feature import stock_disclosure_cninfo
from requests import Response
from requests.exceptions import ChunkedEncodingError, ConnectionError, ReadTimeout, SSLError

from thesistrace import operational_events
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

    discovery = AkshareCninfoFinancialAnnouncementSource(PartiallyUnavailableClient()).discover(
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
            return _json_response({})

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
            return _json_response({})

        def post(self, _url: str, **kwargs: object) -> object:
            observed_requests.append(("post", float(kwargs["timeout"])))
            return _json_response({})

    transport = RequestsTransport()

    def query(**_kwargs: object) -> _Frame:
        stock_disclosure_cninfo.requests.get("https://example.test/securities")
        stock_disclosure_cninfo.requests.post("https://example.test/announcements", data={})
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
    monkeypatch.setattr("time.sleep", lambda _delay: None)

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
    assert [gap.failure_code for gap in discovery.gaps] == ["CNINFO_DISCOVERY_UNAVAILABLE"] * len(
        FINANCIAL_ANNOUNCEMENT_CATEGORIES
    )
    assert stock_disclosure_cninfo.requests is transport


def _json_response(body: object, *, status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response.encoding = "utf-8"
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(body).encode()
    response._content_consumed = True
    return response


class _PagedCninfoTransport:
    """Deterministic remote fixture; run the real AKShare paging/formatting code."""

    def __init__(self, failures: list[Exception | Response]) -> None:
        self.failures = list(failures)
        self.pages: list[int] = []
        self.get_failures: list[Exception] = []
        self.get_attempts = 0

    def get(self, _url: str, **_kwargs: object) -> Response:
        self.get_attempts += 1
        if self.get_failures:
            raise self.get_failures.pop(0)
        return _json_response({"stockList": [{"code": "000001", "orgId": "org-1"}]})

    def post(self, _url: str, **kwargs: object) -> Response:
        payload = kwargs["data"]
        if payload["category"] != "category_bndbg_szsh":
            return _json_response({"totalAnnouncement": 0, "announcements": []})
        page = int(payload["pageNum"])
        self.pages.append(page)
        if page == 2 and self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        rows = [
            {
                "secCode": "000001",
                "secName": "平安银行",
                "orgId": "org-1",
                "announcementId": f"half-year-{number}",
                "announcementTitle": f"2026年半年度报告 {number}",
                "announcementTime": 1786982400000,
            }
            for number in range((page - 1) * 30, min(page * 30, 31))
        ]
        return _json_response({"totalAnnouncement": 31, "announcements": rows})


@pytest.fixture
def cninfo_pagination(monkeypatch: pytest.MonkeyPatch):
    stock_disclosure_cninfo.__get_stock_json.cache_clear()
    delays: list[float] = []
    monkeypatch.setattr("time.sleep", delays.append)

    def install(failures: list[Exception | Response]) -> _PagedCninfoTransport:
        transport = _PagedCninfoTransport(failures)
        monkeypatch.setattr(stock_disclosure_cninfo, "requests", transport)
        return transport

    yield install, delays
    stock_disclosure_cninfo.__get_stock_json.cache_clear()


def test_transient_page_failure_recovers_without_restarting_category(cninfo_pagination) -> None:
    install, delays = cninfo_pagination
    transport = install([ReadTimeout("temporary second-page read failure")])

    discovery = AkshareCninfoFinancialAnnouncementSource().discover(
        start_date="2026-08-12",
        end_date="2026-08-18",
        allowed_ts_codes={"000001.SZ"},
    )

    assert discovery.gaps == ()
    assert discovery.completed_categories == FINANCIAL_ANNOUNCEMENT_CATEGORIES
    assert len(discovery.announcements) == 31
    # First page is requested once for the count and once for its content by AKShare.
    assert transport.pages == [1, 1, 2, 2]
    assert delays == [1.0]
    assert stock_disclosure_cninfo.requests is transport


def _discover(**options: object):
    return AkshareCninfoFinancialAnnouncementSource(**options).discover(
        start_date="2026-08-12", end_date="2026-08-18", allowed_ts_codes={"000001.SZ"}
    )


@pytest.mark.parametrize(
    "failure", ["json", "connection", "truncated", 408, 429, 500, 502, 503, 504]
)
def test_transient_http_and_json_failures_retry_only_the_failed_page(
    cninfo_pagination,
    failure: str | int,
) -> None:
    install, delays = cninfo_pagination
    if failure == "connection":
        failed = ConnectionError("connection temporarily unavailable")
    elif failure == "truncated":
        failed = ChunkedEncodingError("response transfer interrupted")
    else:
        failed = _json_response({}, status=failure if isinstance(failure, int) else 200)
        if failure == "json":
            failed._content = b"<html>temporarily unavailable</html>"
    transport = install([failed])

    discovery = _discover()

    assert discovery.gaps == ()
    assert len(discovery.announcements) == 31
    assert transport.pages == [1, 1, 2, 2]
    assert delays == [1.0]


def test_third_attempt_can_recover(cninfo_pagination) -> None:
    install, delays = cninfo_pagination
    transport = install([ReadTimeout("first"), ReadTimeout("second")])

    discovery = _discover()

    assert discovery.gaps == ()
    assert len(discovery.announcements) == 31
    assert transport.pages == [1, 1, 2, 2, 2]
    assert delays == [1.0, 2.0]


@pytest.mark.parametrize("max_attempts", [1, 2, 3])
def test_retry_exhaustion_preserves_other_categories_and_discards_partial_category(
    cninfo_pagination,
    max_attempts: int,
) -> None:
    install, delays = cninfo_pagination
    transport = install([ReadTimeout("still unavailable") for _ in range(4)])

    discovery = _discover(max_attempts=max_attempts)

    assert discovery.completed_categories == ("年报", "一季报", "三季报", "补充更正")
    assert discovery.announcements == ()
    assert len(discovery.gaps) == 1
    assert discovery.gaps[0].failure_code == "CNINFO_DISCOVERY_UNAVAILABLE"
    assert discovery.gaps[0].category == "半年报"
    assert transport.pages == [1, 1] + [2] * max_attempts
    assert delays == [1.0, 2.0][: max_attempts - 1]
    assert stock_disclosure_cninfo.requests is transport


@pytest.mark.parametrize("failure", [400, 401, 403, 404, 501, "certificate", "shape"])
def test_deterministic_rejections_are_not_retried(cninfo_pagination, failure: str | int) -> None:
    install, delays = cninfo_pagination
    failed = (
        SSLError("certificate verification failed")
        if failure == "certificate"
        else _json_response([], status=failure if isinstance(failure, int) else 200)
    )
    transport = install([failed])

    discovery = _discover()

    assert len(discovery.gaps) == 1
    assert discovery.gaps[0].category == "半年报"
    assert transport.pages == [1, 1, 2]
    assert delays == []


@pytest.mark.parametrize("header,should_retry", [("5", True), ("31", False), ("bad", False)])
def test_retry_after_is_respected_without_unbounded_waits(
    cninfo_pagination,
    header: str,
    should_retry: bool,
) -> None:
    install, delays = cninfo_pagination
    failed = _json_response({}, status=429)
    failed.headers["Retry-After"] = header
    transport = install([failed])

    discovery = _discover()

    assert bool(discovery.gaps) is not should_retry
    assert transport.pages == ([1, 1, 2, 2] if should_retry else [1, 1, 2])
    assert delays == ([5.0] if should_retry else [])


def test_failed_response_is_closed_before_next_request(cninfo_pagination, monkeypatch) -> None:
    install, _delays = cninfo_pagination
    failed = _json_response({}, status=503)
    closed = []
    monkeypatch.setattr(failed, "close", lambda: closed.append(True))
    transport = install([failed])
    original_post = transport.post

    def post(url: str, **kwargs: object) -> Response:
        if transport.pages == [1, 1, 2]:
            assert closed == [True]
        return original_post(url, **kwargs)

    monkeypatch.setattr(transport, "post", post)

    assert _discover().gaps == ()
    assert closed == [True]


def test_prerequisite_metadata_get_uses_the_same_retry_budget(cninfo_pagination) -> None:
    install, delays = cninfo_pagination
    transport = install([])
    transport.get_failures = [ReadTimeout("metadata temporarily unavailable")]

    discovery = _discover()

    assert discovery.gaps == ()
    assert len(discovery.announcements) == 31
    assert transport.get_attempts == 2
    assert delays == [1.0]


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "3"])
def test_retry_budget_requires_a_positive_integer(value: object) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        AkshareCninfoFinancialAnnouncementSource(max_attempts=value)


def test_retry_logs_safe_diagnostics_without_exception_secrets(
    cninfo_pagination, monkeypatch
) -> None:
    install, _delays = cninfo_pagination
    install([ConnectionError("https://user:secret@example.test?token=secret")])
    events = []
    monkeypatch.setattr(operational_events, "emit_operational_event", events.append)

    assert _discover().gaps == ()

    assert [event.event for event in events] == ["cninfo_request_retry"]
    assert events[0].context["attempt_number"] == 1
    assert events[0].context["exception_type"] == "ConnectionError"
    assert "secret" not in str(events)
    assert "example.test" not in str(events)


@pytest.mark.parametrize(
    "retry_after,expected_delay",
    [
        ("Fri, 04 Sep 2026 07:00:05 GMT", 5.0),
        ("Fri, 04 Sep 2026 06:59:59 GMT", 1.0),
        ("Fri, 04 Sep 2026 07:01:00 GMT", None),
    ],
)
def test_http_date_retry_after_uses_a_bounded_utc_deadline(
    cninfo_pagination,
    monkeypatch,
    retry_after: str,
    expected_delay: float | None,
) -> None:
    class FrozenClock:
        @staticmethod
        def now(_tz):
            return datetime(2026, 9, 4, 7, 0, 0, tzinfo=UTC)

    monkeypatch.setattr("thesistrace.adapters.cninfo_financial_announcements.datetime", FrozenClock)
    install, delays = cninfo_pagination
    failed = _json_response({}, status=503)
    failed.headers["Retry-After"] = retry_after
    install([failed])

    discovery = _discover()

    assert bool(discovery.gaps) == (expected_delay is None)
    assert delays == ([] if expected_delay is None else [expected_delay])


def test_exhaustion_logs_the_actual_http_status_and_attempt(cninfo_pagination, monkeypatch) -> None:
    install, _delays = cninfo_pagination
    install([_json_response({}, status=503) for _ in range(3)])
    events = []
    monkeypatch.setattr(operational_events, "emit_operational_event", events.append)

    assert len(_discover().gaps) == 1

    assert [event.event for event in events] == [
        "cninfo_request_retry",
        "cninfo_request_retry",
        "cninfo_request_failed",
    ]
    assert [event.context["attempt_number"] for event in events] == [1, 2, 3]
    assert all(event.context["status_code"] == 503 for event in events)
    assert all(event.context["exception_type"] == "HTTPError" for event in events)


def test_logging_failure_does_not_break_retry_recovery(cninfo_pagination, monkeypatch) -> None:
    install, _delays = cninfo_pagination
    install([ReadTimeout("transient")])

    def broken_sink(_event):
        raise OSError("log sink unavailable")

    monkeypatch.setattr(operational_events, "emit_operational_event", broken_sink)

    assert _discover().gaps == ()


def test_recovered_discovery_is_identical_to_uninterrupted_discovery(cninfo_pagination) -> None:
    install, _delays = cninfo_pagination
    install([])
    uninterrupted = _discover()
    install([ReadTimeout("transient")])

    assert _discover() == uninterrupted
