from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from thesistrace.adapters.tushare_benchmark import TushareBenchmarkSource
from thesistrace.data import DataSourceError
from thesistrace.data.source import RawSourceResponse


class RecordingProvider:
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
        self.requests.append((api_name, dict(params), tuple(fields)))
        return RawSourceResponse(fields=("ts_code", "trade_date", "open"), items=self.rows)


def test_source_uses_fixed_index_daily_open_contract_and_orders_rows() -> None:
    provider = RecordingProvider(
        (
            ("399300.SZ", "20100105", 3545.1900),
            ("399300.SZ", "20100104", 3592.4700),
        )
    )

    levels = TushareBenchmarkSource(provider).collect_open_levels(
        start_session="2010-01-04",
        end_session="2010-01-05",
    )

    assert [(level.session, level.open_level) for level in levels] == [
        ("2010-01-04", "3592.47"),
        ("2010-01-05", "3545.19"),
    ]
    assert provider.requests == [
        (
            "index_daily",
            {
                "ts_code": "399300.SZ",
                "start_date": "20100104",
                "end_date": "20100105",
                "limit": 5000,
                "offset": 0,
            },
            ("ts_code", "trade_date", "open"),
        )
    ]


@pytest.mark.parametrize(
    ("rows", "detail_code"),
    [
        (
            (
                ("399300.SZ", "20100104", 3592.47),
                ("399300.SZ", "20100104", 3592.48),
            ),
            "DUPLICATE_BENCHMARK_LEVEL",
        ),
        ((("000300.SH", "20100104", 3592.47),), "MALFORMED_BENCHMARK_PROVIDER_PAYLOAD"),
    ],
)
def test_source_rejects_duplicate_or_wrong_identity(
    rows: tuple[tuple[object, ...], ...],
    detail_code: str,
) -> None:
    with pytest.raises(DataSourceError) as failure:
        TushareBenchmarkSource(RecordingProvider(rows)).collect_open_levels(
            start_session="2010-01-04",
            end_session="2010-01-05",
        )

    assert failure.value.detail_code == detail_code
