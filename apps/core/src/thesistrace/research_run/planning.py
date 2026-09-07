from __future__ import annotations

from datetime import date

from thesistrace.research_kernel.capacity import (
    CHUNK_TIME_TARGET_SECONDS,
    SessionCapacityError,
    plan_session_capacity,
)
from thesistrace.research_run.models import (
    ResearchExecutionChunk,
    ResearchExecutionPlan,
)

DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES = 1536 * 1024**2


class ResearchChunkCapacityError(SessionCapacityError):
    pass


def plan_research_chunks(
    *,
    calculation_sessions: tuple[date, ...],
    research_session_offset: int,
    formula_work: int,
    node_count: int,
    field_count: int,
    maximum_universe_cardinality: int,
    effective_lookback: int,
    execution_memory_bytes: int,
) -> ResearchExecutionPlan:
    if not calculation_sessions or calculation_sessions != tuple(sorted(calculation_sessions)):
        raise ValueError("Research calculation sessions must be ordered")
    if not 0 <= research_session_offset < len(calculation_sessions):
        raise ValueError("Research Period offset is outside calculation sessions")
    try:
        capacity = plan_session_capacity(
            formula_work=formula_work,
            node_count=node_count,
            field_count=field_count,
            maximum_universe_cardinality=maximum_universe_cardinality,
            effective_lookback=effective_lookback,
            execution_memory_bytes=execution_memory_bytes,
        )
    except SessionCapacityError as error:
        raise ResearchChunkCapacityError(str(error)) from error
    chunk_session_count = capacity.session_count

    chunks: list[ResearchExecutionChunk] = []
    for ordinal, start in enumerate(
        range(0, len(calculation_sessions), chunk_session_count),
        start=1,
    ):
        selected = calculation_sessions[start : start + chunk_session_count]
        warmup_count = max(0, min(len(selected), research_session_offset - start))
        chunks.append(
            ResearchExecutionChunk(
                ordinal=ordinal,
                first_session=selected[0],
                last_session=selected[-1],
                session_count=len(selected),
                warmup_session_count=warmup_count,
                research_session_count=len(selected) - warmup_count,
            )
        )
    return ResearchExecutionPlan(
        execution_memory_bytes=execution_memory_bytes,
        chunk_time_target_seconds=CHUNK_TIME_TARGET_SECONDS,
        chunk_session_count=chunk_session_count,
        time_target_exceeded=capacity.time_target_exceeded,
        estimated_peak_bytes=capacity.estimated_peak_bytes,
        estimated_chunk_work=capacity.estimated_work,
        maximum_universe_cardinality=maximum_universe_cardinality,
        calculation_sessions=calculation_sessions,
        research_session_offset=research_session_offset,
        research_session_count=len(calculation_sessions) - research_session_offset,
        chunks=tuple(chunks),
    )
