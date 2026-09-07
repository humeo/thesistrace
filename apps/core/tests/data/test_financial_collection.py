from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from thesistrace.adapters.tushare_provider import TushareSourceError
from thesistrace.data.financial_collection import (
    FINANCIAL_ENDPOINTS,
    FinancialCapabilityReport,
    FinancialCollectionContract,
    FinancialDateShard,
    probe_financial_capability,
)
from thesistrace.data.source import RawSourceResponse


class ProbeSource:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def query_raw(
        self,
        endpoint: str,
        *,
        params: dict[str, object],
        fields: tuple[str, ...],
    ) -> RawSourceResponse:
        self.requests.append((endpoint, params, fields))
        response_fields = ("ts_code", "ann_date", "end_date", "value")
        rows = (
            ("000001.SZ", "20110401", "20101231", None),
            ("000001.SZ", "20110401", "20101231", None),
            ("000001.SZ", "20260425", "20260331", 12),
        )
        if "start_date" in params:
            start = str(params["start_date"])
            end = str(params["end_date"])
            rows = tuple(row for row in rows if start <= str(row[1]) <= end)
        return RawSourceResponse(response_fields, rows)


def test_capability_probe_freezes_complete_history_statement_contract() -> None:
    source = ProbeSource()
    report = probe_financial_capability(
        source,
        reference_instrument="000001.SZ",
        comparison_shards=_annual_shards(),
        observed_rate_limit_events={"income": (2.0, 4.0)},
        clock=lambda: datetime(2026, 8, 13, 4, tzinfo=UTC),
    )

    assert tuple(endpoint.endpoint for endpoint in report.endpoints) == FINANCIAL_ENDPOINTS
    for endpoint in report.endpoints:
        assert endpoint.permission == "available"
        assert endpoint.returned_fields == ("ts_code", "ann_date", "end_date", "value")
        assert endpoint.null_value_count == 2
        assert endpoint.duplicate_row_count == 1
        assert endpoint.full_history_row_count == 3
        assert endpoint.source_date_extent == ("20110401", "20260425")
        assert endpoint.observed_response_row_counts[0] == 3
        assert sorted(endpoint.observed_response_row_counts[1:]) == [
            *([0] * 35),
            1,
            2,
        ]
        assert endpoint.suspected_truncation_row_count is None
        assert endpoint.full_history_proven is True
    assert report.endpoints[0].observed_rate_limit_events == 2
    assert report.endpoints[0].observed_rate_limit_retry_seconds == (2.0, 4.0)
    assert all(item.observed_rate_limit_events == 0 for item in report.endpoints[1:])
    assert "token" not in repr(report).lower()

    contract = FinancialCollectionContract.from_capability(report)
    assert contract.shards == (FinancialDateShard("complete-history"),)
    assert contract.endpoint_fields[0] == (
        "income",
        ("ts_code", "ann_date", "end_date", "value"),
    )
    assert len(source.requests) == 3 * (1 + len(_annual_shards()))
    assert FinancialCapabilityReport.from_descriptor(report.descriptor()) == report


def test_unproven_complete_history_fails_closed() -> None:
    class MismatchedSource(ProbeSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            response = super().query_raw(endpoint, params=params, fields=fields)
            if "start_date" in params:
                return RawSourceResponse(response.fields, response.items[:-1])
            return response

    source = MismatchedSource()
    fixed = _annual_shards()
    report = probe_financial_capability(
        source,
        reference_instrument="000001.SZ",
        comparison_shards=fixed,
        clock=lambda: datetime(2026, 8, 13, 4, tzinfo=UTC),
    )

    try:
        FinancialCollectionContract.from_capability(report)
    except ValueError as error:
        assert str(error) == "complete-history response is unproven"
    else:
        raise AssertionError("unproven complete history was accepted")


def test_collection_contract_rejects_executable_date_shards() -> None:
    required_fields = (
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "end_type",
        "update_flag",
    )
    bounded = FinancialCollectionContract(
        capability_sha256="a" * 64,
        endpoint_fields=tuple(
            (endpoint, required_fields) for endpoint in FINANCIAL_ENDPOINTS
        ),
        suspected_truncation_row_counts=tuple(
            (endpoint, None) for endpoint in FINANCIAL_ENDPOINTS
        ),
        shards=_annual_shards(),
    )

    with pytest.raises(ValueError, match="financial collection contract is invalid"):
        FinancialCollectionContract.from_descriptor(bounded.descriptor())


def test_capability_probe_reports_permission_failure_at_the_exact_shard() -> None:
    class DeniedSource(ProbeSource):
        def query_raw(
            self,
            endpoint: str,
            *,
            params: dict[str, object],
            fields: tuple[str, ...],
        ) -> RawSourceResponse:
            raise TushareSourceError("MISSING_PERMISSION", source_code=2002)

    report = probe_financial_capability(
        DeniedSource(),
        reference_instrument="000001.SZ",
        comparison_shards=_annual_shards(),
        clock=lambda: datetime(2026, 8, 13, 4, tzinfo=UTC),
    )

    assert tuple(endpoint.endpoint for endpoint in report.endpoints) == FINANCIAL_ENDPOINTS
    assert all(endpoint.permission == "unavailable" for endpoint in report.endpoints)
    assert all(endpoint.failure_code == "MISSING_PERMISSION" for endpoint in report.endpoints)
    assert len(report.endpoints) == 3
    with pytest.raises(ValueError, match="financial endpoint permission is unavailable"):
        FinancialCollectionContract.from_capability(report)


def test_capability_probe_rejects_a_comparison_shard_longer_than_one_year() -> None:
    source = ProbeSource()

    with pytest.raises(
        ValueError,
        match="financial capability comparison shards are invalid",
    ):
        probe_financial_capability(
            source,
            reference_instrument="000001.SZ",
            comparison_shards=(
                FinancialDateShard("too-wide", "19900101", "19910102"),
            ),
            clock=lambda: datetime(1991, 1, 2, 4, tzinfo=UTC),
        )

    assert source.requests == []


def _annual_shards() -> tuple[FinancialDateShard, ...]:
    return tuple(
        FinancialDateShard(
            str(year),
            date(year, 1, 1).strftime("%Y%m%d"),
            date(year, 12, 31).strftime("%Y%m%d"),
        )
        for year in range(1990, 2027)
    )
