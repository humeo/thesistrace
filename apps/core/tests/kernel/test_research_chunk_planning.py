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

    assert plan.chunk_session_count == 64
    assert [chunk.session_count for chunk in plan.chunks] == [64, 64, 22]
    assert plan.chunks[0].first_session == date(2024, 1, 1)
    assert plan.chunks[-1].last_session == date(2024, 5, 29)
    assert plan.research_session_offset == 24
    assert plan.research_session_count == 126
    assert plan.time_target_exceeded is False


def test_one_session_that_fits_memory_remains_admissible_when_time_target_is_exceeded() -> None:
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

    assert plan.chunk_session_count == 1
    assert plan.time_target_exceeded is True
    assert [chunk.session_count for chunk in plan.chunks] == [1, 1, 1]


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
