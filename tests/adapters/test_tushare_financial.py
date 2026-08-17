from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from thesistrace.adapters.tushare_financial import TushareFinancialSource
from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data.source import RawSourceResponse


class PagingProvider:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self.rows = rows
        self.requests: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def query_raw(
        self,
        api_name: str,
        *,
        params: Mapping[str, object],
        fields: Sequence[str],
    ) -> RawSourceResponse:
        copied_params = dict(params)
        copied_fields = tuple(fields)
        self.requests.append((api_name, copied_params, copied_fields))
        if api_name != "balancesheet":
            return RawSourceResponse(copied_fields, self.rows)
        offset = int(copied_params["offset"])
        limit = int(copied_params["limit"])
        return RawSourceResponse(copied_fields, self.rows[offset : offset + limit])


def test_balancesheet_complete_history_is_collected_through_bounded_pages() -> None:
    fields = ("ts_code", "row_id")
    rows = tuple(("000001.SZ", ordinal) for ordinal in range(162))
    provider = PagingProvider(rows)

    response = TushareFinancialSource(provider).query_raw(
        "balancesheet",
        params={"ts_code": "000001.SZ"},
        fields=fields,
    )

    assert response == RawSourceResponse(fields, rows)
    assert provider.requests == [
        (
            "balancesheet",
            {"ts_code": "000001.SZ", "limit": 100, "offset": 0},
            fields,
        ),
        (
            "balancesheet",
            {"ts_code": "000001.SZ", "limit": 100, "offset": 100},
            fields,
        ),
    ]


def test_non_truncated_financial_endpoints_remain_one_logical_request() -> None:
    fields = ("ts_code", "row_id")
    rows = (("000001.SZ", 1),)
    provider = PagingProvider(rows)

    response = TushareFinancialSource(provider).query_raw(
        "income",
        params={"ts_code": "000001.SZ"},
        fields=fields,
    )

    assert response == RawSourceResponse(fields, rows)
    assert provider.requests == [("income", {"ts_code": "000001.SZ"}, fields)]


def test_balancesheet_pagination_fails_closed_when_offset_is_ignored() -> None:
    fields = ("ts_code", "row_id")
    repeated_page = tuple(("000001.SZ", ordinal) for ordinal in range(100))

    class StalledProvider(PagingProvider):
        def query_raw(
            self,
            api_name: str,
            *,
            params: Mapping[str, object],
            fields: Sequence[str],
        ) -> RawSourceResponse:
            self.requests.append((api_name, dict(params), tuple(fields)))
            return RawSourceResponse(tuple(fields), repeated_page)

    with pytest.raises(TushareSourceError, match="PAGINATION_STALLED"):
        TushareFinancialSource(StalledProvider(repeated_page)).query_raw(
            "balancesheet",
            params={"ts_code": "000001.SZ"},
            fields=fields,
        )


def test_balancesheet_pagination_preserves_duplicate_rows_across_pages() -> None:
    fields = ("ts_code", "row_id")
    first_page = tuple(("000001.SZ", ordinal) for ordinal in range(100))
    rows = (*first_page, first_page[-1], ("000001.SZ", 100))
    provider = PagingProvider(rows)

    response = TushareFinancialSource(provider).query_raw(
        "balancesheet",
        params={"ts_code": "000001.SZ"},
        fields=fields,
    )

    assert response.items == rows
    assert response.items.count(first_page[-1]) == 2


def test_balancesheet_pagination_rejects_schema_drift_between_pages() -> None:
    fields = ("ts_code", "row_id")
    rows = tuple(("000001.SZ", ordinal) for ordinal in range(101))

    class DriftingProvider(PagingProvider):
        def query_raw(
            self,
            api_name: str,
            *,
            params: Mapping[str, object],
            fields: Sequence[str],
        ) -> RawSourceResponse:
            response = super().query_raw(api_name, params=params, fields=fields)
            if int(params["offset"]) == 100:
                return RawSourceResponse(("row_id", "ts_code"), response.items)
            return response

    with pytest.raises(TushareSourceError, match="INVALID_RESPONSE"):
        TushareFinancialSource(DriftingProvider(rows)).query_raw(
            "balancesheet",
            params={"ts_code": "000001.SZ"},
            fields=fields,
        )
