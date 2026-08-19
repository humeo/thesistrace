from __future__ import annotations

from time import perf_counter

import pyarrow as pa

from thesistrace.alpha_language import alpha_language
from thesistrace.data.columnar_series import ColumnarResearchData
from thesistrace.publication.serialization import canonical_json_bytes
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix,
    evaluate_columnar_alpha_matrix,
    evaluate_columnar_alpha_sessions,
)
from thesistrace.research_series import AlignedResearchData, InstrumentProfile


def _empty_table() -> pa.Table:
    return pa.table({"instrument_id": pa.array([], type=pa.string())})


def _industry_series(
    *,
    sessions: tuple[str, ...],
    instrument_count: int,
) -> ColumnarResearchData:
    instruments = tuple(f"equity:{index:06d}.SZ" for index in range(instrument_count))
    coordinates = tuple(
        (session, instrument_id) for session in sessions for instrument_id in instruments
    )
    return ColumnarResearchData(
        sessions=sessions,
        _instruments=pa.table(
            {
                "instrument_id": instruments,
                "board": ["main"] * instrument_count,
                "listed_to": [""] * instrument_count,
            }
        ),
        _eod_prices=pa.table(
            {
                "session_date": [session for session, _instrument_id in coordinates],
                "instrument_id": [instrument_id for _session, instrument_id in coordinates],
                "open_raw": [1.0] * len(coordinates),
                "open_adj": [1.0] * len(coordinates),
                "turnover_amount_cny": [1.0] * len(coordinates),
                "close_adj": [
                    float(index % instrument_count + session_index + 1)
                    for session_index, _session in enumerate(sessions)
                    for index in range(instrument_count)
                ],
            }
        ),
        _universes=pa.table(
            {
                "session": sessions,
                "instrument_ids": [list(instruments) for _session in sessions],
            }
        ),
        _trading_states=_empty_table(),
        _price_limits=_empty_table(),
        _industries=pa.table(
            {
                "instrument_id": [
                    instrument_id for instrument_id in instruments for _interval in range(2)
                ],
                "active_from": [
                    value
                    for _instrument_id in instruments
                    for value in ("2010-01-01", "2024-01-05")
                ],
                "active_to": [
                    value for _instrument_id in instruments for value in ("2024-01-05", "")
                ],
                "sw2021_l1": [
                    f"industry:{(index + interval) % 31:02d}"
                    for index in range(instrument_count)
                    for interval in range(2)
                ],
            }
        ),
        _financial_values=None,
        _field_columns={"price.close.adjusted": "close_adj"},
    )


def test_industry_membership_preserves_point_in_time_interval_boundaries() -> None:
    series = _industry_series(
        sessions=("2024-01-04", "2024-01-05"),
        instrument_count=2,
    )

    assert series.industries[("2024-01-04", "equity:000000.SZ")] == "industry:00"
    assert series.industries[("2024-01-05", "equity:000000.SZ")] == "industry:01"
    assert series.industries[("2024-01-04", "equity:000001.SZ")] == "industry:01"
    assert series.industries[("2024-01-05", "equity:000001.SZ")] == "industry:02"


def test_columnar_industry_neutralization_matches_the_row_reference() -> None:
    sessions = tuple(f"2024-01-{day:02d}" for day in range(2, 10))
    instrument_count = 62
    instruments = tuple(f"equity:{index:06d}.SZ" for index in range(instrument_count))
    series = _industry_series(sessions=sessions, instrument_count=instrument_count)
    aligned = AlignedResearchData(
        sessions=sessions,
        instruments={
            instrument_id: InstrumentProfile(board="main", listed_to="")
            for instrument_id in instruments
        },
        fields={
            "price.close.adjusted": {
                (session, instrument_id): float(index + session_index + 1)
                for session_index, session in enumerate(sessions)
                for index, instrument_id in enumerate(instruments)
            }
        },
        universe_members={session: instruments for session in sessions},
        industries={
            (session, instrument_id): series.industries[(session, instrument_id)]
            for session in sessions
            for instrument_id in instruments
        },
        execution_prices={},
        trading_states={},
        price_limits={},
    )
    compiled = alpha_language.compile("cs_rank(pct_change(close_adj, 1))")

    expected = evaluate_alpha_matrix(
        aligned,
        compiled_alpha=compiled,
        neutralization="industry",
    )
    actual = evaluate_columnar_alpha_matrix(
        series,
        compiled_alpha=compiled,
        neutralization="industry",
        cancellation_check=lambda: None,
    )

    assert canonical_json_bytes(actual) == canonical_json_bytes(expected)


def test_top3000_industry_neutralization_has_an_executable_performance_gate() -> None:
    sessions = tuple(f"2024-01-{day:02d}" for day in range(2, 10))
    series = _industry_series(sessions=sessions, instrument_count=3_000)
    compiled = alpha_language.compile("cs_rank(pct_change(close_adj, 1))")

    started = perf_counter()
    evaluated = evaluate_columnar_alpha_sessions(
        series,
        compiled_alpha=compiled,
        neutralization="industry",
        cancellation_check=lambda: None,
    )
    elapsed_seconds = perf_counter() - started

    assert [row["session"] for row in evaluated["sessions"]] == list(sessions)
    assert elapsed_seconds < 4.0
