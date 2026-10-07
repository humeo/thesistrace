from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from thesistrace.research_kernel.strategy_event_limits import (
    MAX_EVENT_RECORD_BYTES,
    MAX_FRAMEWORK_RECORD_BYTES,
    MAX_TARGET_RECORD_BYTES,
)
from thesistrace.research_kernel.strategy_program_runtime import (
    BOOTSTRAP_WALL_SECONDS,
    HISTORY_CELLS,
    HISTORY_REQUESTS,
    INPUT_BYTES,
    MEMORY_BYTES,
    OUTPUT_BYTES,
    STATE_BYTES,
    WALL_SECONDS,
)
from thesistrace.research_kernel.terminal_state_schema import FRAMEWORK_STATE_BYTES
from thesistrace.research_series import HISTORY_PROJECTION_CACHE_BYTES

DEFAULT_MAX_CHUNK_SESSIONS = 128
CHUNK_TIME_TARGET_SECONDS = 30
CHUNK_TIME_TARGET_WORK = 15_000_000
_FIXED_EXECUTION_OVERHEAD_BYTES = 64 * 1024**2
_BINARY64_BYTES = 8
_LIVE_CALCULATION_COLUMNS = 32
_CONTINUATION_COLUMNS = 16
_LIVE_BUFFER_MULTIPLIER = 3
_MAX_LABEL_HORIZON = 20
_WORK_PER_SECOND = CHUNK_TIME_TARGET_WORK // CHUNK_TIME_TARGET_SECONDS
_OTHER_STRATEGY_RECORDS_PER_SESSION = 8
type DecisionMode = Literal["factor_evaluation", "framework", "direct"]


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
    decision_mode: DecisionMode = "factor_evaluation",
    python_program_count: int = 0,
    max_chunk_sessions: int = DEFAULT_MAX_CHUNK_SESSIONS,
) -> SessionCapacityPlan:
    if type(max_chunk_sessions) is not int or max_chunk_sessions < 1:
        raise ValueError("Research Chunk maximum must be a positive integer")
    _validate_decision_capacity(decision_mode, python_program_count)
    continuation_bytes, per_session_bytes = _capacity_memory_components(
        node_count=node_count,
        field_count=field_count,
        maximum_universe_cardinality=maximum_universe_cardinality,
        effective_lookback=effective_lookback,
        execution_memory_bytes=execution_memory_bytes,
        formula_work=formula_work,
        additional_live_columns=additional_live_columns,
    )
    fixed_bytes = (_FIXED_EXECUTION_OVERHEAD_BYTES + continuation_bytes
                   + _decision_fixed_bytes(decision_mode, python_program_count))
    per_session_bytes += _decision_session_bytes(decision_mode, python_program_count)
    if fixed_bytes + per_session_bytes > execution_memory_bytes:
        raise SessionCapacityError(
            "Worker capacity cannot fit one complete full-Universe Research Session"
        )
    memory_session_count = min(
        max_chunk_sessions,
        (execution_memory_bytes - fixed_bytes) // per_session_bytes,
    )
    per_session_work = _session_work(
        formula_work, maximum_universe_cardinality, python_program_count,
    )
    # Worst-case Python deadlines are useful telemetry, not throughput estimates.
    # Cancellation is supervised independently of a completed Chunk.
    session_count = max(1, int(memory_session_count))
    return SessionCapacityPlan(
        session_count=session_count,
        time_target_exceeded=per_session_work * session_count > CHUNK_TIME_TARGET_WORK,
        estimated_peak_bytes=fixed_bytes + per_session_bytes * session_count,
        estimated_work=per_session_work * session_count,
    )


def estimate_session_peak_bytes(
    *,
    session_count: int,
    formula_work: int,
    node_count: int,
    field_count: int,
    maximum_universe_cardinality: int,
    effective_lookback: int,
    execution_memory_bytes: int,
    additional_live_columns: int = 0,
    decision_mode: DecisionMode = "factor_evaluation",
    python_program_count: int = 0,
) -> int:
    """Estimate one frozen Chunk using the ordinary ResearchRun memory model."""

    if type(session_count) is not int or session_count < 1:
        raise ValueError("Research Chunk session count is invalid")
    _validate_decision_capacity(decision_mode, python_program_count)
    continuation_bytes, per_session_bytes = _capacity_memory_components(
        node_count=node_count,
        field_count=field_count,
        maximum_universe_cardinality=maximum_universe_cardinality,
        effective_lookback=effective_lookback,
        execution_memory_bytes=execution_memory_bytes,
        formula_work=formula_work,
        additional_live_columns=additional_live_columns,
    )
    return (
        _FIXED_EXECUTION_OVERHEAD_BYTES + continuation_bytes
        + _decision_fixed_bytes(decision_mode, python_program_count)
        + (per_session_bytes + _decision_session_bytes(decision_mode, python_program_count))
        * session_count
    )


def estimate_session_work(
    *,
    session_count: int,
    formula_work: int,
    maximum_universe_cardinality: int,
    decision_mode: DecisionMode = "factor_evaluation",
    python_program_count: int = 0,
) -> int:
    if (
        type(session_count) is not int or session_count < 1
        or formula_work < 0
        or maximum_universe_cardinality <= 0
    ):
        raise ValueError("Research Chunk work facts are invalid")
    _validate_decision_capacity(decision_mode, python_program_count)
    return session_count * _session_work(formula_work, maximum_universe_cardinality,
                                         python_program_count)


def _validate_decision_capacity(mode: DecisionMode, programs: int) -> None:
    if (mode not in {"factor_evaluation", "direct", "framework"}
            or mode == "factor_evaluation" and programs != 0
            or mode == "direct" and programs != 1
            or mode == "framework" and not 0 <= programs <= 4):
        raise ValueError("Research decision capacity facts are invalid")


def _decision_fixed_bytes(mode: DecisionMode, programs: int) -> int:
    if mode == "factor_evaluation":
        return 0
    state = FRAMEWORK_STATE_BYTES if mode == "framework" else STATE_BYTES
    # Only one guest runs at a time; its input/output buffers overlap the host
    # continuation and the frozen next-Open target.
    # One bounded read may overlap Arrow buffers, Python numeric rows and its
    # encoded response. Programs execute sequentially, so reserve this once.
    guest = (MEMORY_BYTES + 2 * INPUT_BYTES + OUTPUT_BYTES
             + HISTORY_CELLS * 128 + HISTORY_PROJECTION_CACHE_BYTES) if programs else 0
    return state + MAX_TARGET_RECORD_BYTES + guest


def _decision_session_bytes(mode: DecisionMode, programs: int) -> int:
    # Admission allowance, not measured RSS or a transport/session limit.
    # The receiver independently checks actual encoded bytes per Chunk.
    if mode == "factor_evaluation":
        return 0
    return ((MAX_FRAMEWORK_RECORD_BYTES if mode == "framework" else 0)
            + MAX_TARGET_RECORD_BYTES
            + (_OTHER_STRATEGY_RECORDS_PER_SESSION
               + HISTORY_REQUESTS * programs) * MAX_EVENT_RECORD_BYTES)


def _session_work(formula_work: int, cardinality: int, programs: int) -> int:
    return (cardinality * (formula_work + _LIVE_CALCULATION_COLUMNS)
            + estimate_python_program_work(program_count=programs, session_count=1))


def estimate_python_program_work(*, program_count: int, session_count: int) -> int:
    if program_count < 0 or type(session_count) is not int or session_count < 1:
        raise ValueError("Python program work facts are invalid")
    return (program_count * session_count
            * (BOOTSTRAP_WALL_SECONDS + WALL_SECONDS) * _WORK_PER_SECOND)


def _capacity_memory_components(
    *,
    formula_work: int,
    node_count: int,
    field_count: int,
    maximum_universe_cardinality: int,
    effective_lookback: int,
    execution_memory_bytes: int,
    additional_live_columns: int,
) -> tuple[int, int]:
    positive_values = (maximum_universe_cardinality, execution_memory_bytes)
    nonnegative_values = (formula_work, node_count, field_count)
    if (
        any(value <= 0 for value in positive_values)
        or any(value < 0 for value in nonnegative_values)
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
        * (field_count + node_count + _LIVE_CALCULATION_COLUMNS + additional_live_columns)
        * _LIVE_BUFFER_MULTIPLIER
    )
    return continuation_bytes, per_session_bytes
