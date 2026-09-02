from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_kernel.capacity import (
    SessionCapacityPlan,
    estimate_session_peak_bytes,
    estimate_session_work,
)
from thesistrace.research_run.models import ResearchExecutionChunk, ResearchExecutionPlan
from thesistrace.research_run.service import PreparedResearchRunAdmission

# A Batch child retains only the current bounded Arrow slice, coordinate indexes,
# dense numeric views, Python Decimal execution prices, Universe tuples, and
# Forward Labels while one ordinary bounded Chunk is calculated. These deliberately
# conservative per-cell allowances cover both Arrow buffers and Python object
# ownership; the ordinary execution estimate supplies interpreter/process and
# current-chunk working memory.
_BINARY64_BYTES = 8
_ARROW_SOURCE_AND_COORDINATE_BYTES = 256
_DECIMAL_OPEN_OBJECT_BYTES = 128
_UNIVERSE_MEMBER_BYTES = 32
_ADJUSTED_OPEN_COLUMNS = 1
_FORWARD_LABEL_COLUMNS = 3
_FORWARD_LABEL_STATE_BYTES = 3
_UNIVERSE_MASK_BYTES = 1
_BATCH_PROCESS_RUNTIME_MARGIN_BYTES = 96 * 1024**2
# Shared outcomes are retained as canonical bytes, not nested Python matrices.
# This allowance covers the exact encoded Alpha cell plus bytes/container
# overhead; the ordinary chunk peak separately covers one decoded active
# outcome and Strategy working state.
_STRATEGY_COMPACT_OUTCOME_BYTES_PER_CELL = 256
_STRATEGY_COMPACT_OUTCOME_BYTES_PER_CHUNK = 64 * 1024
_STRATEGY_SWEEP_CAPACITY_UTILIZATION_NUMERATOR = 3
_STRATEGY_SWEEP_CAPACITY_UTILIZATION_DENOMINATOR = 4
_MAX_PENDING_ALPHA_SESSIONS = 21
_ALPHA_CONTINUATION_BYTES_PER_CELL = 96
_STRATEGY_POSITION_CONTINUATION_BYTES = 1024
_STRATEGY_OBSERVATION_BYTES_PER_SESSION = 64 * 1024

type UniverseMemberUnionCardinalities = Callable[
    [str, tuple[tuple[date, ...], ...]],
    tuple[int, ...],
]


class ResearchBatchCapacityError(ValueError):
    pass


def validate_research_batch_capacity(
    batch_kind: ResearchBatchKind,
    children: Sequence[PreparedResearchRunAdmission],
    *,
    research_calendar: tuple[date, ...],
    universe_member_union_cardinalities: UniverseMemberUnionCardinalities,
) -> SessionCapacityPlan:
    if not children:
        raise ValueError("Research Batch capacity requires child Runs")
    inputs = [child.immutable_input for child in children]
    first = inputs[0]
    execution_memory_bytes = first.execution_plan.execution_memory_bytes
    if any(
        value.execution_plan.execution_memory_bytes != execution_memory_bytes
        or value.data_admission.generation_manifest_sha256
        != first.data_admission.generation_manifest_sha256
        or value.requested_start_date != first.requested_start_date
        or value.requested_end_date != first.requested_end_date
        or value.universe != first.universe
        or value.neutralization != first.neutralization
        for value in inputs[1:]
    ):
        raise ValueError("Research Batch child scope is inconsistent")
    field_ids = {field_id for value in inputs for field_id in value.field_bindings}
    maximum_chunk_session_count = min(value.execution_plan.chunk_session_count for value in inputs)
    if not research_calendar or research_calendar != tuple(sorted(set(research_calendar))):
        raise ValueError("Research Batch calendar is invalid")
    research_sessions = tuple(
        session
        for session in research_calendar
        if first.requested_start_date <= session <= first.requested_end_date
    )
    if not research_sessions:
        raise ValueError("Research Batch plan has no Research Sessions")
    context_session_count = max(
        _MAX_PENDING_ALPHA_SESSIONS,
        max(value.alpha_admission.effective_lookback for value in inputs),
        2,
    )
    candidate_windows = {
        session_count: _context_windows(
            shared_sessions=research_calendar,
            research_sessions=research_sessions,
            chunk_session_count=session_count,
            context_session_count=context_session_count,
        )
        for session_count in range(maximum_chunk_session_count, 0, -1)
    }
    unique_windows = tuple(
        dict.fromkeys(window for windows in candidate_windows.values() for window in windows)
    )
    union_counts = universe_member_union_cardinalities(first.universe, unique_windows)
    if len(union_counts) != len(unique_windows) or any(
        isinstance(count, bool) or not isinstance(count, int) or count <= 0
        for count in union_counts
    ):
        raise ValueError("Research Batch Universe member union measurement is invalid")
    count_by_window = dict(zip(unique_windows, union_counts, strict=True))
    capacity_limit_bytes = execution_memory_bytes
    if batch_kind == "strategy_sweep":
        # Canonical compaction temporarily overlaps the active decoded outcome,
        # and Python/Arrow allocators retain high-water pages. Keep explicit
        # headroom proven by the real widest-admitted child RSS boundary.
        capacity_limit_bytes = (
            execution_memory_bytes
            * _STRATEGY_SWEEP_CAPACITY_UTILIZATION_NUMERATOR
            // _STRATEGY_SWEEP_CAPACITY_UTILIZATION_DENOMINATOR
        )
    alpha_continuation_count = len(inputs) if batch_kind == "factor_evaluation" else 1
    strategy_held_instrument_count = (
        0
        if batch_kind != "strategy_sweep"
        else max(int(value.strategy["holdings_count"]) for value in inputs if value.strategy)
    )
    for session_count, windows in candidate_windows.items():
        maximum_slice_union = max(count_by_window[window] for window in windows)
        maximum_execution_cardinality = maximum_slice_union + strategy_held_instrument_count
        maximum_resident_cell_count = max(
            len(window) * (count_by_window[window] + strategy_held_instrument_count)
            for window in windows
        )
        ordinary_chunk_peak_bytes = max(
            estimate_session_peak_bytes(
                session_count=session_count,
                formula_work=value.alpha_admission.formula_work,
                node_count=value.alpha_admission.node_count,
                field_count=len(value.field_bindings),
                maximum_universe_cardinality=maximum_execution_cardinality,
                effective_lookback=value.alpha_admission.effective_lookback,
                execution_memory_bytes=execution_memory_bytes,
            )
            for value in inputs
        )
        ordinary_chunk_work = max(
            estimate_session_work(
                session_count=session_count,
                formula_work=value.alpha_admission.formula_work,
                maximum_universe_cardinality=maximum_execution_cardinality,
            )
            for value in inputs
        )
        resident_bytes = maximum_resident_cell_count * (
            _ARROW_SOURCE_AND_COORDINATE_BYTES
            + _DECIMAL_OPEN_OBJECT_BYTES
            + _UNIVERSE_MEMBER_BYTES
            + _BINARY64_BYTES * (len(field_ids) + _ADJUSTED_OPEN_COLUMNS + _FORWARD_LABEL_COLUMNS)
            + _FORWARD_LABEL_STATE_BYTES
            + _UNIVERSE_MASK_BYTES
        )
        continuation_bytes = (
            alpha_continuation_count
            * _MAX_PENDING_ALPHA_SESSIONS
            * maximum_slice_union
            * _ALPHA_CONTINUATION_BYTES_PER_CELL
            + strategy_held_instrument_count * _STRATEGY_POSITION_CONTINUATION_BYTES
        )
        strategy_private_bytes = 0
        strategy_output_bytes = 0
        if batch_kind == "strategy_sweep":
            strategy_private_bytes = strategy_sweep_private_artifact_capacity_bytes(
                encoded_outcome_cell_count=(
                    min(
                        len(research_sessions),
                        session_count + _MAX_PENDING_ALPHA_SESSIONS,
                    )
                    * maximum_slice_union
                ),
                chunk_count=1,
            )
            strategy_output_bytes = session_count * _STRATEGY_OBSERVATION_BYTES_PER_SESSION
        estimated_peak_bytes = (
            ordinary_chunk_peak_bytes
            + _BATCH_PROCESS_RUNTIME_MARGIN_BYTES
            + resident_bytes
            + continuation_bytes
            + strategy_private_bytes
            + strategy_output_bytes
        )
        if estimated_peak_bytes <= capacity_limit_bytes:
            return SessionCapacityPlan(
                session_count=session_count,
                time_target_exceeded=(
                    session_count < maximum_chunk_session_count
                    or any(value.execution_plan.time_target_exceeded for value in inputs)
                ),
                estimated_peak_bytes=estimated_peak_bytes,
                estimated_work=ordinary_chunk_work,
            )
    raise ResearchBatchCapacityError(
        "Worker capacity cannot execute one shared Research Batch session"
    )


def _context_windows(
    *,
    shared_sessions: tuple[date, ...],
    research_sessions: tuple[date, ...],
    chunk_session_count: int,
    context_session_count: int,
) -> tuple[tuple[date, ...], ...]:
    windows: list[tuple[date, ...]] = []
    positions = {session: position for position, session in enumerate(shared_sessions)}
    for start in range(0, len(research_sessions), chunk_session_count):
        selected = research_sessions[start : start + chunk_session_count]
        first = positions[selected[0]]
        last = positions[selected[-1]]
        windows.append(shared_sessions[max(0, first - context_session_count) : last + 1])
    return tuple(windows)


def rechunk_research_execution_plan(
    plan: ResearchExecutionPlan,
    *,
    chunk_session_count: int,
) -> ResearchExecutionPlan:
    if not 1 <= chunk_session_count <= plan.chunk_session_count:
        raise ValueError("Research Batch Chunk size is invalid")
    chunks: list[ResearchExecutionChunk] = []
    for ordinal, start in enumerate(
        range(0, len(plan.calculation_sessions), chunk_session_count),
        start=1,
    ):
        selected = plan.calculation_sessions[start : start + chunk_session_count]
        warmup_count = max(
            0,
            min(len(selected), plan.research_session_offset - start),
        )
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
    return plan.model_copy(
        update={
            "chunk_session_count": chunk_session_count,
            "time_target_exceeded": (
                plan.time_target_exceeded or chunk_session_count < plan.chunk_session_count
            ),
            "chunks": tuple(chunks),
        }
    )


def strategy_sweep_private_artifact_capacity_bytes(
    *,
    encoded_outcome_cell_count: int,
    chunk_count: int,
) -> int:
    if encoded_outcome_cell_count <= 0 or chunk_count <= 0:
        raise ValueError("Strategy Sweep private artifact capacity facts are invalid")
    return (
        encoded_outcome_cell_count * _STRATEGY_COMPACT_OUTCOME_BYTES_PER_CELL
        + chunk_count * _STRATEGY_COMPACT_OUTCOME_BYTES_PER_CHUNK
    )


def strategy_sweep_encoded_outcome_cell_count(
    *,
    research_session_counts: Sequence[int],
    maximum_universe_cardinality: int,
) -> int:
    if (
        not research_session_counts
        or maximum_universe_cardinality <= 0
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in research_session_counts
        )
    ):
        raise ValueError("Strategy Sweep outcome capacity facts are invalid")
    encoded_session_count = 0
    completed_research_sessions = 0
    for research_session_count in research_session_counts:
        if research_session_count == 0:
            continue
        encoded_session_count += research_session_count + min(
            completed_research_sessions,
            _MAX_PENDING_ALPHA_SESSIONS,
        )
        completed_research_sessions += research_session_count
    if completed_research_sessions == 0:
        raise ValueError("Strategy Sweep outcome capacity requires Research Sessions")
    return encoded_session_count * maximum_universe_cardinality
