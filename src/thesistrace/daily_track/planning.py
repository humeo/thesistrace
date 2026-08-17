from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from thesistrace.research_kernel.capacity import (
    MAX_CHUNK_SESSION_COUNT,
    SessionCapacityError,
    plan_session_capacity,
)

DEFAULT_TRACKING_EXECUTION_MEMORY_BYTES = 1536 * 1024**2


@dataclass(frozen=True)
class TrackingAdvancePlan:
    target_sessions: tuple[date, ...]
    capacity_blocked: bool
    time_target_exceeded: bool
    estimated_peak_bytes: int | None
    estimated_target_work: int | None


def plan_tracking_advance(
    *,
    unpublished_sessions: tuple[date, ...],
    formula_work: int,
    node_count: int,
    field_count: int,
    maximum_universe_cardinality: int,
    effective_lookback: int,
    execution_memory_bytes: int,
) -> TrackingAdvancePlan:
    if not unpublished_sessions:
        raise ValueError("Tracking Advance needs an unpublished Research Session")
    candidates = unpublished_sessions[:MAX_CHUNK_SESSION_COUNT]
    try:
        capacity = plan_session_capacity(
            formula_work=formula_work,
            node_count=node_count,
            field_count=field_count,
            maximum_universe_cardinality=maximum_universe_cardinality,
            effective_lookback=effective_lookback,
            execution_memory_bytes=execution_memory_bytes,
        )
    except SessionCapacityError:
        return TrackingAdvancePlan(
            target_sessions=candidates[:1],
            capacity_blocked=True,
            time_target_exceeded=False,
            estimated_peak_bytes=None,
            estimated_target_work=None,
        )
    target = candidates[: capacity.session_count]
    return TrackingAdvancePlan(
        target_sessions=target,
        capacity_blocked=False,
        time_target_exceeded=capacity.time_target_exceeded,
        estimated_peak_bytes=capacity.estimated_peak_bytes,
        estimated_target_work=capacity.estimated_work,
    )
