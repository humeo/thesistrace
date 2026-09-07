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
        maximum_universe_cardinality=lambda _universe, _start, _end: 300,
        universe_member_union_cardinalities=lambda _universe, windows: tuple(300 for _ in windows),
        financial_research_readiness="not_ready",
    )

    with pytest.raises(DatasetWarmupUnavailable):
        snapshot.calculation_shape(
            start=sessions[0],
            end=sessions[1],
            lookback=1,
            universe="top300",
        )


def test_admission_snapshot_preserves_degraded_financial_readiness() -> None:
    session = date(2026, 8, 14)
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=session,
        coverage_start=session,
        coverage_end=session,
        research_sessions=(session,),
        available_field_ids=frozenset({"financial.income.total_revenue.latest_fy"}),
        maximum_universe_cardinality=lambda _universe, _start, _end: 300,
        universe_member_union_cardinalities=lambda _universe, windows: tuple(300 for _ in windows),
        financial_coverage_start=session,
        financial_coverage_end=session,
        financial_research_readiness="ready_with_gaps",
    )

    assert snapshot.financial_research_readiness == "ready_with_gaps"


def test_admission_snapshot_exposes_exact_universe_member_union_measurement() -> None:
    sessions = (date(2026, 8, 3), date(2026, 8, 4))
    snapshot = DatasetAdmissionSnapshot(
        generation_manifest_sha256="a" * 64,
        data_through_session=sessions[-1],
        coverage_start=sessions[0],
        coverage_end=sessions[-1],
        research_sessions=sessions,
        available_field_ids=frozenset({"price.close.adjusted"}),
        maximum_universe_cardinality=lambda _universe, _start, _end: 1,
        universe_member_union_cardinalities=(
            lambda _universe, windows: tuple(len(window) for window in windows)
        ),
        financial_research_readiness="not_ready",
    )

    assert snapshot.universe_member_union_cardinalities("top300", (sessions, (sessions[-1],))) == (
        2,
        1,
    )
