"""Network-free checks of the adapter installed in the final production image."""

from __future__ import annotations

import inspect
import json
import time

from akshare.stock_feature import stock_disclosure_cninfo as cninfo
from requests import Response
from requests.exceptions import ReadTimeout

from thesistrace.adapters.cninfo_financial_announcements import (
    AkshareCninfoFinancialAnnouncementSource,
)


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.encoding = "utf-8"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    result._content_consumed = True
    return result


class Remote:
    def __init__(self, failures: list[Exception | Response]) -> None:
        self.failures = list(failures)
        self.pages: list[int] = []

    def get(self, _url: str, **kwargs: object) -> Response:
        assert kwargs["timeout"] == 30
        return response({"stockList": [{"code": "000001", "orgId": "company-1"}]})

    def post(self, _url: str, **kwargs: object) -> Response:
        assert kwargs["timeout"] == 30
        payload = kwargs["data"]
        if payload["category"] != "category_bndbg_szsh":
            return response({"totalAnnouncement": 0, "announcements": []})
        page = int(payload["pageNum"])
        self.pages.append(page)
        if page == 2 and self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        return response(
            {
                "totalAnnouncement": 31,
                "announcements": [
                    {
                        "secCode": "000001",
                        "secName": "Fixture",
                        "orgId": "company-1",
                        "announcementId": f"report-{number}",
                        "announcementTitle": f"2026年半年度报告 {number}",
                        "announcementTime": 1786982400000,
                    }
                    for number in range((page - 1) * 30, min(page * 30, 31))
                ],
            }
        )


def run_case(name, failures, expected_pages, expected_delays, succeeds):
    remote = Remote(failures)
    original_requests, original_sleep = cninfo.requests, time.sleep
    cninfo.__get_stock_json.cache_clear()
    delays = []
    try:
        cninfo.requests, time.sleep = remote, delays.append
        discovery = AkshareCninfoFinancialAnnouncementSource().discover(
            start_date="2026-08-08",
            end_date="2026-08-17",
            allowed_ts_codes={"000001.SZ"},
        )
        assert remote.pages == expected_pages, remote.pages
        assert delays == expected_delays, delays
        assert cninfo.requests is remote
        if succeeds:
            assert discovery.gaps == ()
            assert len(discovery.announcements) == 31
        else:
            assert discovery.announcements == ()
            assert len(discovery.gaps) == 1
            assert discovery.gaps[0].category == "半年报"
            assert discovery.completed_categories == ("年报", "一季报", "三季报", "补充更正")
        print(
            json.dumps({"case": name, "passed": True, "pages": remote.pages, "delays": delays}),
            flush=True,
        )
        return discovery
    finally:
        cninfo.requests, time.sleep = original_requests, original_sleep
        cninfo.__get_stock_json.cache_clear()


assert (
    inspect.signature(AkshareCninfoFinancialAnnouncementSource).parameters["max_attempts"].default
    == 3
)
baseline = run_case("uninterrupted", [], [1, 1, 2], [], True)
recovered = run_case("page_timeout_recovers", [ReadTimeout("fixture")], [1, 1, 2, 2], [1], True)
assert recovered == baseline
run_case(
    "third_attempt_recovers",
    [ReadTimeout("fixture") for _ in range(2)],
    [1, 1, 2, 2, 2],
    [1, 2],
    True,
)
run_case(
    "exhausted_stops_at_three",
    [ReadTimeout("fixture") for _ in range(4)],
    [1, 1, 2, 2, 2],
    [1, 2],
    False,
)
broken_json = response({})
broken_json._content = b"<html>temporary invalid response</html>"
run_case("json_error_recovers", [broken_json], [1, 1, 2, 2], [1], True)
run_case("http_503_recovers", [response({}, 503)], [1, 1, 2, 2], [1], True)
run_case("http_403_is_terminal", [response({}, 403)], [1, 1, 2], [], False)
limited = response({}, 429)
limited.headers["Retry-After"] = "5"
run_case("retry_after_respected", [limited], [1, 1, 2, 2], [5], True)
print(json.dumps({"result": "passed", "cases": 8, "network": "disabled"}), flush=True)
