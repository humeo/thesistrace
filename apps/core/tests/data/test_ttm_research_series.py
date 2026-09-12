from __future__ import annotations

from dataclasses import replace

import pyarrow as pa

from thesistrace.data.columnar_series import ColumnarResearchData
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix,
    evaluate_columnar_alpha_matrix,
)
from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha
from thesistrace.research_series import (
    AlignedResearchData,
    InstrumentProfile,
    research_data_identity,
    slice_research_sessions,
    ttm_window_column,
)


def test_ttm_windows_survive_data_slices_and_control_alpha_missing_coverage() -> None:
    sessions = ("2010-04-21", "2010-08-02")
    instrument = "equity:000001.SZ"
    left = "financial.income.total_revenue.ttm"
    right = "financial.cashflow.operating_cash_flow.ttm"
    windows = {left: ["20100331", "20100630"], right: ["20100331", "20100331"]}
    coordinates = tuple((day, instrument) for day in sessions)
    members = {day: (instrument,) for day in sessions}
    row_data = AlignedResearchData(
        sessions=sessions, instruments={instrument: InstrumentProfile(board="main", listed_to="")},
        fields={left: dict.fromkeys(coordinates, "10"), right: dict.fromkeys(coordinates, "2")},
        universe_members=members, industries={}, execution_prices={}, trading_states={},
        price_limits={}, ttm_windows={key: dict(zip(coordinates, ends, strict=True))
                                     for key, ends in windows.items()},
    )
    axes = pa.table({"session": sessions, "instrument_id": [instrument] * 2})
    columnar = ColumnarResearchData(
        sessions=sessions,
        _instruments=pa.table({
            "instrument_id": [instrument], "board": ["main"], "listed_to": [""],
        }),
        _eod_prices=pa.table({"session_date": sessions, "instrument_id": [instrument] * 2,
                             "open_raw": [1.0, 1.0], "open_adj": [1.0, 1.0],
                             "turnover_amount_cny": [100.0, 100.0]}),
        _universes=pa.table({"session": sessions, "instrument_ids": [[instrument]] * 2}),
        _trading_states=axes, _price_limits=axes,
        _industries=pa.table({"instrument_id": pa.array([], type=pa.string())}),
        _family_values=axes.append_column(left, pa.array(["10", "10"]))
            .append_column(right, pa.array(["2", "2"]))
            .append_column(ttm_window_column(left), pa.array(windows[left]))
            .append_column(ttm_window_column(right), pa.array(windows[right])),
        _field_columns={left: left, right: right},
    )
    compiled = validate_normalized_alpha(
        {"kind": "binary", "operator": "divide",
         "left": {"kind": "field", "field_id": left},
         "right": {"kind": "field", "field_id": right}},
        field_bindings={left: "revenue_ttm", right: "operating_cash_flow_ttm"},
    )
    expected = [
        {"session": sessions[0], "values": [{"instrument_id": instrument, "value": 5.0}],
         "coverage_loss": {}},
        {"session": sessions[1], "values": [], "coverage_loss": {"missing_expression": 1}},
    ]
    for selected in (sessions, sessions[1:]):
        rows = slice_research_sessions(row_data, selected)
        columns = slice_research_sessions(columnar, selected)
        scalar_result = evaluate_alpha_matrix(rows, compiled_alpha=compiled, neutralization="none")
        columnar_result = evaluate_columnar_alpha_matrix(
            columns, compiled_alpha=compiled, neutralization="none",
            cancellation_check=lambda: None,
        )
        assert scalar_result == columnar_result
        assert scalar_result["sessions"] == (expected if selected == sessions else expected[1:])
    assert research_data_identity(row_data) != research_data_identity(
        replace(row_data, ttm_windows={}),
    )
