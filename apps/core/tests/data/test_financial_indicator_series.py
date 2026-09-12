import pyarrow as pa
import pytest

from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver


def fact(period, session, **values):
    return {
        "instrument_id": "stock-1",
        "source_report_period": period,
        "source_published_date": "20200420",
        "state_effective_session": session,
        "availability_status": "available",
        "observation_event_at": session + "T00:00:00+00:00",
        "eps": None,
        "roe": None,
        **values,
    }


def resolver(rows):
    def read(columns, instruments, through):
        table = pa.Table.from_pylist(
            [
                row
                for row in rows
                if row["instrument_id"] in instruments and row["state_effective_session"] <= through
            ]
        )
        return table.select(sorted(columns))

    return FinancialIndicatorSeriesResolver("a" * 64, read)


def test_latest_report_null_and_conflict_hide_previous_values():
    rows = [
        fact("20191231", "2020-04-21", eps=2.0, roe=15.0),
        fact("20200331", "2020-04-30", eps=None, roe=3.0),
        fact(
            "20200331",
            "2020-05-04",
            eps=9.0,
            roe=8.0,
            availability_status="conflicting_observation",
        ),
        fact("20200331", "2020-05-05", eps=1.0, roe=4.0),
    ]
    result = (
        resolver(rows)
        .resolve_table(
            manifest_sha256="a" * 64,
            field_ids=("financial.indicator.eps", "financial.indicator.roe"),
            sessions=("2020-04-21", "2020-04-30", "2020-05-04", "2020-05-05"),
            instrument_ids=("stock-1",),
        )
        .to_pylist()
    )
    assert [r["financial.indicator.eps"] for r in result] == [2.0, None, None, 1.0]
    assert [r["financial.indicator.roe"] for r in result] == [0.15, 0.03, None, 0.04]


def test_old_report_revision_does_not_replace_newer_report():
    rows = [
        fact("20191231", "2020-04-21", eps=2.0),
        fact("20200331", "2020-04-30", eps=1.0),
        fact("20191231", "2020-05-04", eps=3.0),
    ]
    result = (
        resolver(rows)
        .resolve_table(
            manifest_sha256="a" * 64,
            field_ids=("financial.indicator.eps",),
            sessions=("2020-05-04",),
            instrument_ids=("stock-1",),
        )
        .to_pylist()
    )
    assert result[0]["financial.indicator.eps"] == 1.0


def test_reader_rejects_different_generation():
    with pytest.raises(ValueError):
        resolver([]).resolve_table(
            manifest_sha256="b" * 64,
            field_ids=("financial.indicator.eps",),
            sessions=("2020-05-04",),
            instrument_ids=("stock-1",),
        )


def test_requested_projection_preserves_sorted_coordinates_and_missing_values():
    rows = [
        fact("20200331", "2020-04-21", eps="2", roe="15"),
        fact("20200331", "2020-04-30", instrument_id="stock-2", eps="3", roe=None),
    ]

    def read(columns, instruments, through):
        assert columns == {
            "instrument_id", "source_report_period", "source_published_date",
            "state_effective_session", "availability_status", "observation_event_at",
            "eps", "roe",
        }
        assert instruments == frozenset({"stock-2", "stock-1", "stock-3"})
        assert through == "2020-04-30"
        return pa.Table.from_pylist(rows).select(sorted(columns))

    result = FinancialIndicatorSeriesResolver("a" * 64, read).resolve_table(
        manifest_sha256="a" * 64,
        field_ids=("financial.indicator.roe", "financial.indicator.eps"),
        sessions=("2020-04-20", "2020-04-21", "2020-04-30"),
        instrument_ids=("stock-2", "stock-1", "stock-3"),
    )
    assert result.column_names == [
        "session", "instrument_id", "financial.indicator.roe", "financial.indicator.eps",
    ]
    assert result["instrument_id"].to_pylist() == ["stock-1", "stock-2", "stock-3"] * 3
    assert result["financial.indicator.eps"].to_pylist() == [
        None, None, None, 2, None, None, 2, 3, None,
    ]
    assert result["financial.indicator.roe"].to_pylist() == [
        None, None, None, .15, None, None, .15, None, None,
    ]
