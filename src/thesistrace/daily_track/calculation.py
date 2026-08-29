from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
    restore_tracking_origin,
    terminal_strategy_state,
)
from thesistrace.daily_track.models import KernelStateCheckpoint, TrackingOrigin
from thesistrace.data import MountedGenerationStore
from thesistrace.research_kernel import (
    AdvanceInput,
    KernelState,
    advance,
    advance_continuation,
    continuation_snapshot,
    empty_continuation,
)
from thesistrace.research_kernel.numeric import require_current_numeric_contract
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    research_sessions,
    slice_research_sessions,
)


def origin_calculation_start_index(
    origin: TrackingOrigin,
    calendar: list[str],
) -> int:
    requested_start = origin.immutable_input.get("requested_start_date")
    admission = origin.immutable_input.get("alpha_admission")
    if not isinstance(requested_start, str) or not isinstance(admission, Mapping):
        raise RuntimeError("DailyTrack frozen calculation input is invalid")
    try:
        first_research_index = next(
            index for index, session in enumerate(calendar) if session >= requested_start
        )
        lookback = int(admission["effective_lookback"])
    except (KeyError, StopIteration, TypeError, ValueError) as error:
        raise RuntimeError("DailyTrack frozen calculation input is outside current data") from error
    calculation_start = first_research_index - lookback
    if calculation_start < 0:
        raise RuntimeError("DailyTrack frozen calculation warm-up is outside current data")
    return calculation_start


def origin_effective_lookback(origin: TrackingOrigin) -> int:
    admission = origin.immutable_input.get("alpha_admission")
    if not isinstance(admission, Mapping):
        raise RuntimeError("DailyTrack frozen Alpha admission is invalid")
    try:
        return int(admission["effective_lookback"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("DailyTrack frozen Alpha admission is invalid") from error


def origin_universe(origin: TrackingOrigin) -> str:
    universe = origin.immutable_input.get("universe")
    if not isinstance(universe, str) or not universe:
        raise RuntimeError("Tracking Universe is invalid")
    return universe


def origin_neutralization(origin: TrackingOrigin) -> str:
    neutralization = origin.immutable_input.get("neutralization")
    if neutralization not in {"none", "industry"}:
        raise RuntimeError("Tracking Neutralization is invalid")
    return str(neutralization)


def state_payload(
    state: KernelState,
    *,
    retained_strategy_sessions: list[str],
) -> dict[str, object]:
    return KernelStateCheckpoint.model_validate(
        project_tracking_checkpoint(
            state,
            retained_strategy_sessions=retained_strategy_sessions,
        )
    ).model_dump(mode="json")


def state_from_payload(
    value: Mapping[str, object],
    research_data: AlignedResearchData | ColumnarResearchSeries,
) -> KernelState:
    checkpoint = KernelStateCheckpoint.model_validate(value)
    return restore_tracking_checkpoint(
        checkpoint.model_dump(mode="json"),
        research_data=research_data,
    )


def execute_tracking_target(value: Mapping[str, object]) -> dict[str, object]:
    if value.get("schema_version") != "tracking-child-request-v1":
        raise RuntimeError("Tracking child request is incompatible")
    origin = TrackingOrigin.model_validate(value["origin"])
    predecessor = _mapping_value(value["predecessor"], "Tracking predecessor")
    generation_id = str(value["data_generation_id"])
    data_through_session = str(value["data_through_session"])
    current_session = str(value["current_session"])
    target_value = value.get("target_sessions")
    if not isinstance(target_value, list) or not target_value:
        raise RuntimeError("Tracking Target is invalid")
    target_sessions = tuple(str(session) for session in target_value)
    require_current_numeric_contract(
        origin.calculation_contracts.get("numeric_execution_contract")
    )
    store = MountedGenerationStore(Path(str(value["data_mount"])))
    admission = store.open_admission(generation_id)
    if admission.generation.data_through_session != data_through_session:
        raise RuntimeError("Pinned Data Generation metadata changed")
    full_calendar = list(admission.research_calendar)
    current_index = full_calendar.index(current_session)
    target_end_index = full_calendar.index(target_sessions[-1])
    if tuple(full_calendar[current_index + 1 : target_end_index + 1]) != target_sessions:
        raise RuntimeError("Pinned Data Generation does not contain the frozen Target")
    calculation_start_index = origin_calculation_start_index(origin, full_calendar)
    lookback = origin_effective_lookback(origin)
    dependency_sessions = full_calendar[
        max(calculation_start_index, current_index - max(lookback, 21) + 1) :
        target_end_index + 1
    ]
    research_data = store.read_columnar_slice(
        generation_id,
        sessions=dependency_sessions,
        universe_name=origin_universe(origin),
        neutralization=origin_neutralization(origin),
        field_bindings={
            str(key): str(binding)
            for key, binding in origin.immutable_input["field_bindings"].items()
        },
        fact_instrument_ids=_predecessor_instrument_ids(predecessor),
    )
    calendar = research_sessions(research_data)
    local_current_index = calendar.index(current_session)
    prior_research_data = slice_research_sessions(
        research_data, calendar[: local_current_index + 1]
    )
    if predecessor.get("schema_version") == "daily-track-activation-checkpoint-v2":
        prior = restore_tracking_origin(
            origin,
            _mapping_value(
                predecessor.get("terminal_strategy_state"),
                "Activation Terminal Strategy State",
            ),
            prior_research_data,
        )
    else:
        prior = state_from_payload(predecessor, prior_research_data)
    continuation_value = value.get("continuation")
    continuation = (
        dict(continuation_value)
        if isinstance(continuation_value, Mapping)
        else _rebuild_continuation(
            store,
            generation_id=generation_id,
            origin=origin,
            calendar=full_calendar,
            calculation_start_index=calculation_start_index,
            current_index=current_index,
            predecessor=predecessor,
        )
    )
    state = advance(
        AdvanceInput(
            prior_state=prior,
            target_research_data=research_data,
            appended_sessions=list(target_sessions),
            continuation=continuation,
            calculation_scope="forward_tracking",
        )
    )
    if state.boundary_session != target_sessions[-1]:
        raise RuntimeError("Tracking Advance returned an invalid boundary")
    return {
        "status": "succeeded",
        "checkpoint": state_payload(
            state,
            retained_strategy_sessions=[current_session, *target_sessions],
        ),
        "terminal_strategy_state": terminal_strategy_state(state),
        "continuation": continuation_snapshot(state),
    }


def _rebuild_continuation(
    store: MountedGenerationStore,
    *,
    generation_id: str,
    origin: TrackingOrigin,
    calendar: list[str],
    calculation_start_index: int,
    current_index: int,
    predecessor: Mapping[str, object],
) -> dict[str, object]:
    """Rebuild bounded transient state without retaining a 504-session data slice."""
    lookback = origin_effective_lookback(origin)
    appended_start = max(calculation_start_index, current_index - 504 + 1)
    continuation = empty_continuation()
    chunk_size = 32
    for chunk_start in range(appended_start, current_index + 1, chunk_size):
        chunk_end = min(current_index, chunk_start + chunk_size - 1)
        context_start = max(
            calculation_start_index,
            chunk_start - max(lookback, 21),
        )
        chunk_data = store.read_columnar_slice(
            generation_id,
            sessions=calendar[context_start : chunk_end + 1],
            universe_name=origin_universe(origin),
            neutralization=origin_neutralization(origin),
            field_bindings={
                str(key): str(binding)
                for key, binding in origin.immutable_input["field_bindings"].items()
            },
            fact_instrument_ids=_predecessor_instrument_ids(predecessor),
        )
        run_input = restore_tracking_origin(
            origin,
            origin.initial_strategy_state.model_dump(mode="json"),
            chunk_data,
        ).run_input_with_research_data(chunk_data)
        continuation = advance_continuation(
            run_input=run_input,
            prior_continuation=continuation,
            target_research_data=chunk_data,
            appended_sessions=calendar[chunk_start : chunk_end + 1],
        )
    return continuation


def _mapping_value(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{name} is invalid")
    return value


def _predecessor_instrument_ids(predecessor: Mapping[str, object]) -> frozenset[str]:
    if predecessor.get("schema_version") == "daily-track-activation-checkpoint-v2":
        terminal = _mapping_value(
            predecessor.get("terminal_strategy_state"),
            "Activation Terminal Strategy State",
        )
    else:
        strategy_state = _mapping_value(
            predecessor.get("strategy_state"),
            "Tracking Strategy State",
        )
        terminal = _mapping_value(
            strategy_state.get("terminal"),
            "Tracking Terminal Strategy State",
        )
    positions = terminal.get("continuation_positions", terminal.get("positions"))
    if not isinstance(positions, list) or any(not isinstance(item, Mapping) for item in positions):
        raise RuntimeError("Tracking predecessor Positions are invalid")
    return frozenset(str(item["instrument_id"]) for item in positions)
