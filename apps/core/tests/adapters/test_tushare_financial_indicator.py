from datetime import date, timedelta

import pytest

from thesistrace.data.financial_indicator_source import (
    FINANCIAL_INDICATOR_SOURCE_FIELDS,
    FinancialIndicatorSource,
)
from thesistrace.data.source import DataSourceError, RawSourceResponse


def response(rows):
    return RawSourceResponse(
        fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
        items=tuple(
            tuple(row.get(field) for field in FINANCIAL_INDICATOR_SOURCE_FIELDS) for row in rows
        ),
    )


class CappedProvider:
    def __init__(self, rows):
        self.rows = rows

    def query_raw(self, api_name, *, params, fields):
        assert api_name == "fina_indicator"
        assert set(params) == {"ts_code", "start_date", "end_date"}
        assert len(fields) == len(set(fields)) == 167
        return response(
            [
                row
                for row in self.rows
                if params["start_date"] <= row["end_date"] <= params["end_date"]
            ][:100]
        )


def test_split_preserves_every_report_and_ambiguous_response_evidence():
    rows = [
        {
            "ts_code": "000001.SZ",
            "end_date": (date(2020, 1, 1) + timedelta(days=n)).strftime("%Y%m%d"),
            "ann_date": None,
            "eps": n,
        }
        for n in range(101)
    ]
    shards = list(
        FinancialIndicatorSource(CappedProvider(rows)).collect_report_range(
            ts_code="000001.SZ",
            start_date="20200101",
            end_date="20200410",
        )
    )
    assert any(not shard.complete and len(shard.response.items) == 100 for shard in shards)
    period_index = FINANCIAL_INDICATOR_SOURCE_FIELDS.index("end_date")
    periods = [
        row[period_index] for shard in shards if shard.complete for row in shard.response.items
    ]
    assert sorted(periods) == [row["end_date"] for row in rows]


def test_single_report_date_at_cap_is_not_complete():
    rows = [{"ts_code": "000001.SZ", "end_date": "20201231", "eps": n} for n in range(100)]
    iterator = FinancialIndicatorSource(CappedProvider(rows)).collect_report_range(
        ts_code="000001.SZ",
        start_date="20201231",
        end_date="20201231",
    )
    assert not next(iterator).complete
    with pytest.raises(DataSourceError) as error:
        next(iterator)
    assert error.value.detail_code == "FINANCIAL_INDICATOR_TRUNCATED"


@pytest.mark.parametrize(
    "fault", ["missing_column", "wrong_identity", "outside_range", "short_row"]
)
def test_invalid_response_cannot_be_marked_complete(fault):
    class InvalidProvider:
        def query_raw(self, *args, **kwargs):
            raw = response(
                [
                    {
                        "ts_code": "other" if fault == "wrong_identity" else "000001.SZ",
                        "end_date": "20210101" if fault == "outside_range" else "20201231",
                    }
                ]
            )
            if fault == "missing_column":
                return RawSourceResponse(fields=raw.fields[:-1], items=(raw.items[0][:-1],))
            if fault == "short_row":
                return RawSourceResponse(fields=raw.fields, items=(raw.items[0][:-1],))
            return raw

    with pytest.raises(DataSourceError) as error:
        list(
            FinancialIndicatorSource(InvalidProvider()).collect_report_range(
                ts_code="000001.SZ",
                start_date="20201231",
                end_date="20201231",
            )
        )
    assert error.value.detail_code == "MALFORMED_FINANCIAL_INDICATOR_PAYLOAD"


@pytest.mark.parametrize(
    "reason", ["UPSTREAM_UNAVAILABLE", "MISSING_PERMISSION", "UPSTREAM_RATE_LIMITED"]
)
def test_vendor_failure_is_normalized_at_indicator_adapter(reason):
    from thesistrace.adapters.tushare_financial_indicator import TushareFinancialIndicatorProvider
    from thesistrace.adapters.tushare_provider import TushareSourceError

    class FailingProvider:
        def query_raw(self, *args, **kwargs):
            raise TushareSourceError(reason, source_code=None)

    source = FinancialIndicatorSource(TushareFinancialIndicatorProvider(FailingProvider()))
    with pytest.raises(DataSourceError) as error:
        list(source.collect_report_range(
            ts_code="000001.SZ", start_date="20200101", end_date="20201231",
        ))
    assert error.value.detail_code == reason
