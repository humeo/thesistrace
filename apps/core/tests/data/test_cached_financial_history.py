from itertools import product

import pyarrow as pa
import pytest
import test_financial_candidate as candidate_fixture
from test_financial_candidate import SESSIONS, _materialized_candidate
from test_financial_indicator_series import fact

from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver
from thesistrace.data.financial_series import FinancialSeriesResolver
from thesistrace.data.history_projection import HistoryProjectionCache
from thesistrace.data.io_metrics import measure_data_io


@pytest.mark.parametrize("field", [
    "financial.cashflow.operating_cash_flow.ttm",
    "financial.cashflow.operating_cash_flow.latest_fy",
])
def test_statement_history_reuses_sparse_states_across_dates_securities_and_reader_instances(
    tmp_path, monkeypatch, field,
):
    monkeypatch.setattr(candidate_fixture, "FIELDS", tuple(
        "n_cashflow_act" if name == "revenue" else name for name in candidate_fixture.FIELDS
    ))
    store, candidate, _, _ = _materialized_candidate(tmp_path, quarterly_cash_seed=True)
    cache = HistoryProjectionCache()
    reference = FinancialSeriesResolver(store)

    def cached():
        return FinancialSeriesResolver(
            store, projection_cache=cache,
            history_sessions=tuple(day for day in SESSIONS if day >= candidate.coverage_start),
        )

    requests = [dict(
        manifest_sha256=candidate.manifest_sha256, field_ids=(field,),
        sessions=sessions, instrument_ids=instruments,
    ) for sessions, instruments in product(
        (SESSIONS[-2:], SESSIONS[2:5], SESSIONS[2:3]),
        (("equity:000001.SZ",), ("equity:000001.SZ", "equity:000002.SZ")),
    )]
    for request in requests:
        expected = reference.resolve_table(**request)
        assert cached().resolve_table(**request).equals(expected)
    with measure_data_io() as warm:
        for request in requests:
            cached().resolve_table(**request)
    assert warm.parquet_object_opens == 0
    assert 0 < cache.retained_bytes <= 32 * 1024**2


def test_statement_cached_values_belong_to_the_frozen_family(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate_fixture, "FIELDS", tuple(
        "n_cashflow_act" if name == "revenue" else name for name in candidate_fixture.FIELDS
    ))
    cache = HistoryProjectionCache()
    versions = []
    for amount in ("930", "940"):
        store, candidate, _, _ = _materialized_candidate(
            tmp_path / amount, second_cashflow_items=[
                ["000002.SZ", "20090425", "", "20081231", "1", "1", "4", amount, "0"],
            ],
        )
        versions.append((FinancialSeriesResolver(
            store, projection_cache=cache,
            history_sessions=tuple(day for day in SESSIONS if day >= candidate.coverage_start),
        ), candidate.manifest_sha256, amount))
    for reader, digest, expected in [*versions, versions[0]]:
        field = "financial.cashflow.operating_cash_flow.ttm"
        actual = reader.resolve_table(
            manifest_sha256=digest, field_ids=(field,), sessions=SESSIONS[-1:],
            instrument_ids=("equity:000002.SZ",),
        )
        assert actual[field].to_pylist() == [expected]


@pytest.mark.parametrize("budget", [1, 9000, 32 * 1024**2])
def test_indicator_sparse_cache_keeps_asof_null_conflict_units_and_axes(budget):
    rows = [
        fact("20191231", "2020-04-21", eps=2, roe=15),
        fact("20200331", "2020-04-30", eps=None, roe=3),
        fact("20200331", "2020-05-04", eps=9, roe=8,
             availability_status="conflicting_observation"),
        fact("20200331", "2020-05-05", eps=1, roe=4),
        fact("20191231", "2020-04-21", instrument_id="stock-2", eps=5, roe=20),
    ]
    reads = []

    def read(columns, instruments, through):
        reads.append((instruments, through))
        return pa.Table.from_pylist([
            row for row in rows if row["instrument_id"] in instruments
            and row["state_effective_session"] <= through
        ]).select(sorted(columns))

    cache = HistoryProjectionCache(budget_bytes=budget)

    def resolver(cached):
        return FinancialIndicatorSeriesResolver("a" * 64, read, **({
            "projection_cache": cache, "history_end": "2020-05-05",
        } if cached else {}))

    requests = [dict(manifest_sha256="a" * 64, field_ids=fields,
                     sessions=sessions, instrument_ids=instruments)
                for fields, sessions, instruments in product(
                    (("financial.indicator.eps",), ("financial.indicator.roe",),
                     ("financial.indicator.roe", "financial.indicator.eps")),
                    (("2020-04-21", "2020-04-30", "2020-05-04", "2020-05-05"),
                     ("2020-04-21",), ("2020-04-30", "2020-05-04")),
                    (("stock-1",), ("stock-2", "stock-1")),
                )]
    for request in requests:
        actual = resolver(True).resolve_table(**request)
        assert actual.equals(resolver(False).resolve_table(**request))
    reads.clear()
    for request in reversed(requests):
        resolver(True).resolve_table(**request)
    if budget == 32 * 1024**2:
        assert reads == []
    assert cache.retained_bytes <= budget
