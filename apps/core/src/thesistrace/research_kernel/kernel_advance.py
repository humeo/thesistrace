"""Pure Research Kernel Advance contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_alpha_matrix,
)
from thesistrace.research_kernel.common_observations import (
    attach_common_input_evidence,
    record_common_input,
)
from thesistrace.research_kernel.kernel_run import (
    KernelRunError,
    KernelState,
    RunInput,
    calculation_definition,
    compose_output,
)
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import transition_strategy
from thesistrace.research_series import (
    AlignedResearchData,
    research_sessions,
    slice_research_sessions,
)

MAX_PENDING_ALPHA_SESSIONS = 21


@dataclass(frozen=True, init=False)
class AdvanceInput:
    _prior_state: KernelState = field(repr=False)
    _target_research_data: AlignedResearchData = field(repr=False)
    _appended_sessions: tuple[str, ...] = field(repr=False)
    _continuation_json: bytes = field(repr=False)
    _calculation_scope: Literal["research_period", "forward_tracking"]

    def __init__(
        self,
        *,
        prior_state: KernelState,
        target_research_data: AlignedResearchData,
        appended_sessions: list[str],
        continuation: Mapping[str, object],
        calculation_scope: Literal["research_period", "forward_tracking"],
    ) -> None:
        if calculation_scope not in {"research_period", "forward_tracking"}:
            raise KernelRunError("Advance calculation scope is invalid")
        run_input = prior_state.run_input_with_research_data(prior_state.research_data_snapshot())
        has_research_period = (
            run_input.research_start_session is not None
            and run_input.research_end_session is not None
        )
        if calculation_scope == "research_period" and not has_research_period:
            raise KernelRunError("Research Period Advance requires explicit boundaries")
        if calculation_scope == "forward_tracking" and (
            run_input.research_start_session is not None
            or run_input.research_end_session is not None
        ):
            raise KernelRunError("Forward Tracking Advance cannot carry Research Period boundaries")
        object.__setattr__(self, "_prior_state", prior_state)
        object.__setattr__(
            self,
            "_target_research_data",
            target_research_data.snapshot(),
        )
        object.__setattr__(self, "_appended_sessions", tuple(appended_sessions))
        object.__setattr__(
            self,
            "_continuation_json",
            canonical_json_bytes(continuation),
        )
        object.__setattr__(self, "_calculation_scope", calculation_scope)

    def prior_state(self) -> KernelState:
        return self._prior_state

    def target_research_data_snapshot(self) -> AlignedResearchData:
        return self._target_research_data.snapshot()

    def appended_sessions_snapshot(self) -> list[str]:
        return list(self._appended_sessions)

    def continuation_snapshot(self) -> dict[str, object]:
        value = json.loads(self._continuation_json)
        if not isinstance(value, dict):
            raise KernelRunError("Advance continuation snapshot is invalid")
        return value

    @property
    def calculation_scope(self) -> Literal["research_period", "forward_tracking"]:
        return self._calculation_scope


def advance(advance_input: AdvanceInput) -> KernelState:
    prior = advance_input.prior_state()
    prior_output = prior.output_snapshot()
    continuation = advance_input.continuation_snapshot()
    prior_output = _with_continuation(prior_output, continuation)
    prior_matrix = _mapping(prior_output.get("alpha_matrix"), "prior Alpha Matrix")
    research_data = _accept_target_research_data(
        prior.research_data_snapshot(),
        advance_input.target_research_data_snapshot(),
        advance_input.appended_sessions_snapshot(),
    )
    new_sessions = advance_input.appended_sessions_snapshot()
    run_input = prior.run_input_with_research_data(
        research_data,
        research_end_session=(
            new_sessions[-1] if advance_input.calculation_scope == "research_period" else None
        ),
    )
    matrix = _advance_alpha(
        run_input,
        research_data,
        prior_matrix,
        new_sessions,
        prior.session_count,
    )
    if advance_input.calculation_scope == "research_period":
        selected_sessions = _research_period_sessions(run_input, research_data)
        if _alpha_session_ids(matrix) != selected_sessions:
            matrix = _rebuild_explicit_alpha(run_input, research_data, selected_sessions)
    strategy_resume = prior.strategy_resume_snapshot()
    definition = calculation_definition(run_input)
    exposure_observations = {}
    strategy = transition_strategy(
        research_data,
        matrix,
        definition,
        origin_session=prior.origin_session,
        observe_common=lambda identifier, code, values: record_common_input(
            exposure_observations, tuple(research_data.sessions), identifier, code, values,
        ),
        continuation=strategy_resume,
    )
    attach_common_input_evidence(matrix, exposure_observations, tuple(new_sessions))
    return KernelState(
        run_input=run_input,
        output=compose_output(matrix, strategy.finalized),
        strategy_resume=strategy.resumable,
        origin_session=prior.origin_session,
    )


def continuation_snapshot(state: KernelState) -> dict[str, object]:
    return continuation_from_output(state.output_snapshot())


def continuation_from_output(output: Mapping[str, object]) -> dict[str, object]:
    """Project the bounded working state shared by ordinary Advance and recovery."""
    alpha = _mapping(output.get("alpha_matrix"), "Alpha Matrix")
    alpha_sessions = alpha.get("sessions")
    if not isinstance(alpha_sessions, list):
        raise KernelRunError("Pending Alpha continuation is invalid")
    selected = alpha_sessions[-MAX_PENDING_ALPHA_SESSIONS:]
    if any(not isinstance(item, Mapping) for item in selected):
        raise KernelRunError("Pending Alpha continuation is invalid")
    return {
        "schema_version": "daily-track-working-state-v1",
        "pending_alpha": [dict(item) for item in selected],
    }


def empty_continuation() -> dict[str, object]:
    return {
        "schema_version": "daily-track-working-state-v1",
        "pending_alpha": [],
    }


def advance_continuation(
    *,
    run_input: RunInput,
    prior_continuation: Mapping[str, object],
    target_research_data: AlignedResearchData,
    appended_sessions: list[str],
) -> dict[str, object]:
    """Advance only the bounded transient Alpha working state."""
    effective_lookback = run_input.alpha_execution_plan().effective_lookback
    restored = _with_continuation(
        {
            "alpha_matrix": {
                "expression": run_input.alpha_expression_snapshot(),
                "effective_lookback": effective_lookback,
                "neutralization": run_input.neutralization,
                "sessions": [],
            },
        },
        prior_continuation,
    )
    prior_alpha = _mapping(restored.get("alpha_matrix"), "prior Alpha continuation")
    calendar = research_sessions(target_research_data)
    if not appended_sessions or any(session not in calendar for session in appended_sessions):
        raise KernelRunError("Continuation rebuild appended sessions are invalid")
    first_index = calendar.index(appended_sessions[0])
    window = slice_research_sessions(
        target_research_data,
        calendar[max(0, first_index - effective_lookback) :],
    )
    evaluated = evaluate_alpha_matrix(
        window,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
    )
    evaluated_rows = evaluated.get("sessions")
    prior_rows = prior_alpha.get("sessions")
    if not isinstance(evaluated_rows, list) or not isinstance(prior_rows, list):
        raise KernelRunError("Continuation rebuild Alpha state is invalid")
    new_set = set(appended_sessions)
    alpha_rows = [dict(item) for item in prior_rows if isinstance(item, Mapping)]
    alpha_rows.extend(
        dict(item)
        for item in evaluated_rows
        if isinstance(item, Mapping)
        and str(item.get("session")) in new_set
    )
    alpha_by_session = {str(item["session"]): item for item in alpha_rows}
    matrix = {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": int(evaluated["effective_lookback"]),
        "neutralization": run_input.neutralization,
        "sessions": list(alpha_by_session.values()),
        "checksum": alpha_matrix_checksum(list(alpha_by_session.values())),
    }
    return continuation_from_output({"alpha_matrix": matrix})


def _with_continuation(
    prior_output: dict[str, dict[str, object]],
    continuation: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    if set(continuation) != {"schema_version", "pending_alpha"} or (
        continuation.get("schema_version") != "daily-track-working-state-v1"
    ):
        raise KernelRunError("Advance continuation contract is invalid")
    pending = continuation.get("pending_alpha")
    if (
        not isinstance(pending, list)
        or len(pending) > MAX_PENDING_ALPHA_SESSIONS
        or any(not isinstance(item, Mapping) for item in pending)
    ):
        raise KernelRunError("Advance continuation bound is invalid")
    restored = json.loads(canonical_json_bytes(prior_output))
    alpha = _mapping(restored.get("alpha_matrix"), "prior Alpha Matrix")
    alpha_sessions = alpha.get("sessions")
    if not isinstance(alpha_sessions, list):
        raise KernelRunError("prior Alpha Matrix sessions are invalid")
    if not alpha_sessions:
        alpha["sessions"] = [dict(item) for item in pending]
    return restored


def _advance_alpha(
    run_input: RunInput,
    research_data: AlignedResearchData,
    prior_matrix: Mapping[str, object],
    new_sessions: list[str],
    prior_session_count: int,
) -> dict[str, object]:
    lookback = int(prior_matrix["effective_lookback"])
    calendar = research_sessions(research_data)
    window_start = max(0, prior_session_count - lookback)
    window = slice_research_sessions(research_data, calendar[window_start:])
    evaluated = evaluate_alpha_matrix(
        window,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
    )
    new_set = set(new_sessions)
    evaluated_sessions = evaluated.get("sessions")
    prior_sessions = prior_matrix.get("sessions")
    if not isinstance(evaluated_sessions, list) or not isinstance(prior_sessions, list):
        raise KernelRunError("Advance Alpha state is invalid")
    appended_sessions = [
        dict(item)
        for item in evaluated_sessions
        if isinstance(item, Mapping) and str(item.get("session")) in new_set
    ]
    if [str(item["session"]) for item in appended_sessions] != new_sessions:
        raise KernelRunError("Advance Alpha calculation did not cover every new session")
    sessions = [dict(item) for item in prior_sessions]
    sessions.extend(appended_sessions)
    return {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": lookback,
        "neutralization": run_input.neutralization,
        "sessions": sessions,
        "checksum": alpha_matrix_checksum(sessions),
    }


def _accept_target_research_data(
    prior: AlignedResearchData,
    target: AlignedResearchData,
    appended_sessions: list[str],
) -> AlignedResearchData:
    new_sessions = [str(value) for value in appended_sessions]
    if not new_sessions:
        raise KernelRunError("Advance requires at least one new Research Session")
    prior_sessions = research_sessions(prior)
    selected_target = research_sessions(target)
    if (
        new_sessions != sorted(set(new_sessions))
        or selected_target[: len(prior_sessions)] != prior_sessions
        or selected_target[len(prior_sessions) :] != new_sessions
    ):
        raise KernelRunError("Advance Research Sessions must be new and canonically ordered")
    if set(target.fields) != set(prior.fields):
        raise KernelRunError("Advance aligned Field set does not match prior state")
    return target.snapshot()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise KernelRunError(f"{name} is invalid")
    return value


def _alpha_session_ids(matrix: Mapping[str, object]) -> list[str]:
    rows = matrix.get("sessions")
    if not isinstance(rows, list) or any(not isinstance(item, Mapping) for item in rows):
        raise KernelRunError("Advance Alpha sessions are invalid")
    return [str(item["session"]) for item in rows]


def _research_period_sessions(
    run_input: RunInput,
    research_data: AlignedResearchData,
) -> list[str]:
    if run_input.research_start_session is None or run_input.research_end_session is None:
        raise KernelRunError("Advance Research Period boundaries are incomplete")
    calendar = research_sessions(research_data)
    try:
        start = calendar.index(run_input.research_start_session)
        end = calendar.index(run_input.research_end_session)
    except ValueError as error:
        raise KernelRunError("Advance Research Period boundary is not canonical") from error
    if start > end:
        raise KernelRunError("Advance Research Period boundary is reversed")
    return calendar[start : end + 1]


def _rebuild_explicit_alpha(
    run_input: RunInput,
    research_data: AlignedResearchData,
    research_sessions: list[str],
) -> dict[str, object]:
    evaluated = evaluate_alpha_matrix(
        research_data,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
    )
    selected = set(research_sessions)
    rows = [
        dict(item)
        for item in evaluated["sessions"]
        if isinstance(item, Mapping) and str(item["session"]) in selected
    ]
    if [str(item["session"]) for item in rows] != research_sessions:
        raise KernelRunError("Advance Alpha rebuild did not cover the Research Period")
    return {
        **evaluated,
        "sessions": rows,
        "checksum": alpha_matrix_checksum(rows),
    }
