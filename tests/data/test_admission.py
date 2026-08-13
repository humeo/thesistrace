from datetime import date

import pytest

from thesistrace.data import DatasetAdmissionSnapshot, DatasetWarmupUnavailable


def test_calculation_shape_rejects_a_truncated_warmup_window() -> None:
    sessions = (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=sessions[-1],
        coverage_start=sessions[0],
        coverage_end=sessions[-1],
        research_sessions=sessions,
        available_field_ids=frozenset({"price.close.adjusted"}),
        count_universe_instruments=lambda _universe, _start, _end: 300,
    )

    with pytest.raises(DatasetWarmupUnavailable):
        snapshot.calculation_shape(
            start=sessions[0],
            end=sessions[1],
            lookback=1,
            universe="top300",
        )
