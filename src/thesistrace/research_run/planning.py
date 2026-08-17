from __future__ import annotations

from datetime import date

from thesistrace.research_run.models import (
    ResearchExecutionChunk,
    ResearchExecutionPlan,
)

MAX_CHUNK_SESSION_COUNT = 63
CHUNK_TIME_TARGET_SECONDS = 30
CHUNK_TIME_TARGET_WORK = 15_000_000
DEFAULT_RESEARCH_EXECUTION_MEMORY_BYTES = 1536 * 1024**2
_FIXED_EXECUTION_OVERHEAD_BYTES = 64 * 1024**2
_BINARY64_BYTES = 8
_LIVE_CALCULATION_COLUMNS = 32
_CONTINUATION_COLUMNS = 16
_LIVE_BUFFER_MULTIPLIER = 3
_MAX_LABEL_HORIZON = 20


class ResearchChunkCapacityError(ValueError):
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
    positive_values = (
        formula_work,
        node_count,
        field_count,
        maximum_universe_cardinality,
        execution_memory_bytes,
    )
    if any(value <= 0 for value in positive_values) or effective_lookback < 0:
        raise ValueError("Research Chunk capacity facts are invalid")

    continuation_sessions = max(effective_lookback, _MAX_LABEL_HORIZON)
    continuation_bytes = (
        maximum_universe_cardinality
        * _BINARY64_BYTES
        * (field_count + node_count + _CONTINUATION_COLUMNS)
        * continuation_sessions
    )
    per_session_bytes = (
        maximum_universe_cardinality
        * _BINARY64_BYTES
        * (field_count + node_count + _LIVE_CALCULATION_COLUMNS)
        * _LIVE_BUFFER_MULTIPLIER
    )
    fixed_bytes = _FIXED_EXECUTION_OVERHEAD_BYTES + continuation_bytes
    if fixed_bytes + per_session_bytes > execution_memory_bytes:
        raise ResearchChunkCapacityError(
            "Worker capacity cannot fit one complete full-Universe Research Session"
        )
    memory_session_count = min(
        MAX_CHUNK_SESSION_COUNT,
        (execution_memory_bytes - fixed_bytes) // per_session_bytes,
    )
    per_session_work = maximum_universe_cardinality * (
        formula_work + _LIVE_CALCULATION_COLUMNS
    )
    time_session_count = CHUNK_TIME_TARGET_WORK // per_session_work
    time_target_exceeded = time_session_count < 1
    chunk_session_count = min(
        memory_session_count,
        1 if time_target_exceeded else time_session_count,
        MAX_CHUNK_SESSION_COUNT,
    )
    chunk_session_count = max(1, int(chunk_session_count))

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
        time_target_exceeded=time_target_exceeded,
        estimated_peak_bytes=fixed_bytes + per_session_bytes * chunk_session_count,
        estimated_chunk_work=per_session_work * chunk_session_count,
        maximum_universe_cardinality=maximum_universe_cardinality,
        calculation_sessions=calculation_sessions,
        research_session_offset=research_session_offset,
        research_session_count=len(calculation_sessions) - research_session_offset,
        chunks=tuple(chunks),
    )
