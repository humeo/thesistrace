from __future__ import annotations

from dataclasses import dataclass

MAX_CHUNK_SESSION_COUNT = 64
CHUNK_TIME_TARGET_SECONDS = 30
CHUNK_TIME_TARGET_WORK = 15_000_000
_FIXED_EXECUTION_OVERHEAD_BYTES = 64 * 1024**2
_BINARY64_BYTES = 8
_LIVE_CALCULATION_COLUMNS = 32
_CONTINUATION_COLUMNS = 16
_LIVE_BUFFER_MULTIPLIER = 3
_MAX_LABEL_HORIZON = 20


class SessionCapacityError(ValueError):
    pass


@dataclass(frozen=True)
class SessionCapacityPlan:
    session_count: int
    time_target_exceeded: bool
    estimated_peak_bytes: int
    estimated_work: int


def plan_session_capacity(
    *,
    formula_work: int,
    node_count: int,
    field_count: int,
    maximum_universe_cardinality: int,
    effective_lookback: int,
    execution_memory_bytes: int,
    additional_live_columns: int = 0,
) -> SessionCapacityPlan:
    positive_values = (
        formula_work,
        node_count,
        field_count,
        maximum_universe_cardinality,
        execution_memory_bytes,
    )
    if (
        any(value <= 0 for value in positive_values)
        or effective_lookback < 0
        or additional_live_columns < 0
    ):
        raise ValueError("Research capacity facts are invalid")
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
        * (
            field_count
            + node_count
            + _LIVE_CALCULATION_COLUMNS
            + additional_live_columns
        )
        * _LIVE_BUFFER_MULTIPLIER
    )
    fixed_bytes = _FIXED_EXECUTION_OVERHEAD_BYTES + continuation_bytes
    if fixed_bytes + per_session_bytes > execution_memory_bytes:
        raise SessionCapacityError(
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
    session_count = min(
        memory_session_count,
        1 if time_target_exceeded else time_session_count,
        MAX_CHUNK_SESSION_COUNT,
    )
    session_count = max(1, int(session_count))
    return SessionCapacityPlan(
        session_count=session_count,
        time_target_exceeded=time_target_exceeded,
        estimated_peak_bytes=fixed_bytes + per_session_bytes * session_count,
        estimated_work=per_session_work * session_count,
    )
