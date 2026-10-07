from __future__ import annotations

from datetime import date, timedelta

import pytest

from thesistrace.research_run.planning import (
    ResearchChunkCapacityError,
    plan_research_chunks,
)


def _sessions(count: int) -> tuple[date, ...]:
    origin = date(2024, 1, 1)
    return tuple(origin + timedelta(days=index) for index in range(count))


def test_planner_selects_the_largest_fixed_chunk_and_only_shortens_the_final_chunk() -> None:
    plan = plan_research_chunks(
        calculation_sessions=_sessions(150),
        research_session_offset=24,
        formula_work=1,
        node_count=1,
        field_count=1,
        maximum_universe_cardinality=3000,
        effective_lookback=24,
        execution_memory_bytes=1536 * 1024**2,
    )

    assert plan.chunk_session_count == 128
    assert [chunk.session_count for chunk in plan.chunks] == [128, 22]
    assert plan.chunks[0].first_session == date(2024, 1, 1)
    assert plan.chunks[-1].last_session == date(2024, 5, 29)
    assert plan.research_session_offset == 24
    assert plan.research_session_count == 126
    assert plan.time_target_exceeded is False


@pytest.mark.parametrize("maximum", [10, 64, 128])
@pytest.mark.parametrize("decision_mode", ["factor_evaluation", "framework"])
def test_configured_maximum_chunks_preserve_every_session(
    maximum: int, decision_mode: str,
) -> None:
    sessions = _sessions(300)
    plan = plan_research_chunks(
        calculation_sessions=sessions,
        research_session_offset=0,
        formula_work=1,
        node_count=1,
        field_count=1,
        maximum_universe_cardinality=300,
        effective_lookback=0,
        execution_memory_bytes=1536 * 1024**2,
        max_chunk_sessions=maximum,
        decision_mode=decision_mode,
    )

    assert plan.chunk_session_count == maximum
    assert sum(chunk.session_count for chunk in plan.chunks) == len(sessions)
    assert plan.chunks[0].first_session == sessions[0]
    assert plan.chunks[-1].last_session == sessions[-1]
    assert all(chunk.session_count == maximum for chunk in plan.chunks[:-1])


def test_python_time_allowance_does_not_shrink_a_chunk_that_fits_memory() -> None:
    plan = plan_research_chunks(
        calculation_sessions=_sessions(256), research_session_offset=0,
        formula_work=1, node_count=1, field_count=1,
        maximum_universe_cardinality=1000, effective_lookback=20,
        execution_memory_bytes=1536 * 1024**2,
        decision_mode="framework", python_program_count=1, max_chunk_sessions=128,
    )
    assert plan.chunk_session_count == 128
    assert [chunk.session_count for chunk in plan.chunks] == [128, 128]
    assert plan.estimated_peak_bytes < plan.execution_memory_bytes


def test_high_formula_work_does_not_shrink_a_chunk_that_fits_memory() -> None:
    plan = plan_research_chunks(
        calculation_sessions=_sessions(256), research_session_offset=0,
        formula_work=10_000, node_count=1, field_count=1,
        maximum_universe_cardinality=1000, effective_lookback=20,
        execution_memory_bytes=1536 * 1024**2, max_chunk_sessions=128,
    )
    assert plan.chunk_session_count == 128
    assert sum(chunk.research_session_count for chunk in plan.chunks) == 256


@pytest.mark.parametrize("maximum", [0, -1, True, 1.5])
def test_chunk_maximum_requires_a_positive_integer(maximum: object) -> None:
    with pytest.raises(ValueError, match="maximum.*positive integer"):
        plan_research_chunks(
            calculation_sessions=_sessions(2), research_session_offset=0,
            formula_work=1, node_count=1, field_count=1,
            maximum_universe_cardinality=300, effective_lookback=0,
            execution_memory_bytes=1536 * 1024**2,
            max_chunk_sessions=maximum,
        )


def test_work_estimate_remains_telemetry_when_time_target_is_exceeded() -> None:
    plan = plan_research_chunks(
        calculation_sessions=_sessions(3),
        research_session_offset=1,
        formula_work=10_000,
        node_count=1,
        field_count=1,
        maximum_universe_cardinality=3000,
        effective_lookback=1,
        execution_memory_bytes=1536 * 1024**2,
    )

    assert plan.chunk_session_count == 128
    assert plan.time_target_exceeded is True
    assert [chunk.session_count for chunk in plan.chunks] == [3]


def test_planner_rejects_when_one_complete_universe_session_cannot_fit() -> None:
    with pytest.raises(
        ResearchChunkCapacityError,
        match="one complete full-Universe Research Session",
    ):
        plan_research_chunks(
            calculation_sessions=_sessions(2),
            research_session_offset=1,
            formula_work=1,
            node_count=64,
            field_count=8,
            maximum_universe_cardinality=1_000_000,
            effective_lookback=252,
            execution_memory_bytes=1536 * 1024**2,
        )


def test_framework_plan_reserves_four_isolated_invocations_and_bounded_evidence() -> None:
    common = dict(
        calculation_sessions=_sessions(65), research_session_offset=1,
        formula_work=1, node_count=1, field_count=1,
        maximum_universe_cardinality=3000, effective_lookback=1,
        execution_memory_bytes=1536 * 1024**2,
    )
    ordinary = plan_research_chunks(**common)
    framework = plan_research_chunks(
        **common, decision_mode="framework", python_program_count=4,
    )
    assert ordinary.chunk_session_count == 128
    assert 1 < framework.chunk_session_count < 128
    assert framework.time_target_exceeded is True
    assert framework.estimated_peak_bytes > ordinary.estimated_peak_bytes // 64
    assert framework.estimated_peak_bytes <= framework.execution_memory_bytes


def test_isolated_program_must_fit_memory_before_admission() -> None:
    common = dict(
        calculation_sessions=_sessions(2), research_session_offset=1,
        formula_work=1, node_count=1, field_count=1,
        maximum_universe_cardinality=3000, effective_lookback=1,
        execution_memory_bytes=190 * 1024**2,
    )
    assert plan_research_chunks(**common).chunk_session_count >= 1
    with pytest.raises(
        ResearchChunkCapacityError, match="one complete full-Universe Research Session",
    ):
        plan_research_chunks(**common, decision_mode="direct", python_program_count=1)


def test_planner_rejects_unknown_decision_mode() -> None:
    with pytest.raises(ValueError, match="decision capacity facts"):
        plan_research_chunks(
            calculation_sessions=_sessions(2), research_session_offset=1,
            formula_work=1, node_count=1, field_count=1,
            maximum_universe_cardinality=3000, effective_lookback=1,
            execution_memory_bytes=1536 * 1024**2,
            decision_mode="unknown",  # type: ignore[arg-type]
        )
