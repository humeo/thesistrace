"""Pure Research Kernel Advance contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_alpha_matrix,
)
from thesistrace.research_kernel.canonical_state import (
    canonical_sessions,
    slice_canonical_sessions,
)
from thesistrace.research_kernel.factor import (
    HORIZONS,
    affected_label_sessions,
    build_forward_labels,
    evaluate_factor,
    factor_horizon_from_daily,
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

MAX_PENDING_ALPHA_SESSIONS = 21
MAX_ROLLING_FACTOR_SESSIONS = 504
MAX_ALPHA_LOOKBACK_SESSIONS = 252


@dataclass(frozen=True, init=False)
class AdvanceInput:
    _prior_state: KernelState = field(repr=False)
    _target_canonical_json: bytes = field(repr=False)
    _appended_sessions: tuple[str, ...] = field(repr=False)
    _continuation_json: bytes | None = field(repr=False)

    def __init__(
        self,
        *,
        prior_state: KernelState,
        target_canonical_release: dict[str, object],
        appended_sessions: list[str],
        continuation: Mapping[str, object] | None = None,
    ) -> None:
        object.__setattr__(self, "_prior_state", prior_state)
        object.__setattr__(
            self,
            "_target_canonical_json",
            canonical_json_bytes(target_canonical_release),
        )
        object.__setattr__(self, "_appended_sessions", tuple(appended_sessions))
        object.__setattr__(
            self,
            "_continuation_json",
            None if continuation is None else canonical_json_bytes(continuation),
        )

    def prior_state(self) -> KernelState:
        return self._prior_state

    def target_canonical_snapshot(self) -> dict[str, object]:
        value = json.loads(self._target_canonical_json)
        if not isinstance(value, dict):
            raise KernelRunError("Advance canonical snapshot is invalid")
        return value

    def appended_sessions_snapshot(self) -> list[str]:
        return list(self._appended_sessions)

    def continuation_snapshot(self) -> dict[str, object] | None:
        if self._continuation_json is None:
            return None
        value = json.loads(self._continuation_json)
        if not isinstance(value, dict):
            raise KernelRunError("Advance continuation snapshot is invalid")
        return value


def advance(advance_input: AdvanceInput) -> KernelState:
    prior = advance_input.prior_state()
    prior_output = prior.output_snapshot()
    continuation = advance_input.continuation_snapshot()
    if continuation is not None:
        prior_output = _with_continuation(prior_output, continuation)
    prior_matrix = _mapping(prior_output.get("alpha_matrix"), "prior Alpha Matrix")
    prior_labels = _mapping(prior_output.get("forward_labels"), "prior Labels")
    prior_factor = _mapping(prior_output.get("factor_evaluation"), "prior Factor")
    canonical = _accept_target_canonical_release(
        prior.canonical_snapshot(),
        advance_input.target_canonical_snapshot(),
        advance_input.appended_sessions_snapshot(),
    )
    new_sessions = advance_input.appended_sessions_snapshot()
    prior_run_input = prior.run_input_with_canonical(prior.canonical_snapshot())
    run_input = prior.run_input_with_canonical(
        canonical,
        research_end_session=(
            new_sessions[-1]
            if prior_run_input.research_end_session is not None
            else None
        ),
    )
    matrix = _advance_alpha(
        run_input,
        canonical,
        prior_matrix,
        new_sessions,
        prior.session_count,
    )
    research_sessions = _research_period_sessions(run_input, canonical)
    if research_sessions is not None:
        if _alpha_session_ids(matrix) != research_sessions:
            matrix = _rebuild_explicit_alpha(run_input, canonical, research_sessions)
        labels = build_forward_labels(
            canonical,
            matrix,
            signal_sessions=research_sessions,
        )
        factor = evaluate_factor(labels)
    else:
        if continuation is None:
            labels = _advance_labels(canonical, matrix, prior_labels, new_sessions)
        else:
            labels = _advance_labels_from_continuation(canonical, matrix, new_sessions)
        factor = _advance_factor(
            canonical,
            labels,
            prior_factor,
            new_sessions,
            compact_continuation=continuation is not None,
        )
    strategy_resume = prior.strategy_resume_snapshot()
    definition = calculation_definition(run_input)
    strategy = transition_strategy(
        canonical,
        matrix,
        definition,
        origin_session=prior.origin_session,
        continuation=strategy_resume,
    )
    return KernelState(
        run_input=run_input,
        output=compose_output(matrix, labels, factor, strategy.finalized),
        strategy_resume=strategy.resumable,
        origin_session=prior.origin_session,
    )


def continuation_snapshot(state: KernelState) -> dict[str, object]:
    output = state.output_snapshot()
    alpha = _mapping(output.get("alpha_matrix"), "Alpha Matrix")
    factor = _mapping(output.get("factor_evaluation"), "Factor")
    alpha_sessions = alpha.get("sessions")
    horizons = _mapping(factor.get("horizons"), "Factor horizons")
    if not isinstance(alpha_sessions, list):
        raise KernelRunError("Pending Alpha continuation is invalid")
    selected_alpha = alpha_sessions[-MAX_PENDING_ALPHA_SESSIONS:]
    if any(not isinstance(item, Mapping) for item in selected_alpha):
        raise KernelRunError("Pending Alpha continuation is invalid")
    rolling_factor: list[dict[str, object]] = []
    for horizon in HORIZONS:
        horizon_value = _mapping(
            horizons.get(str(horizon)),
            f"Factor horizon {horizon}",
        )
        daily = horizon_value.get("daily")
        if not isinstance(daily, list):
            raise KernelRunError("rolling Factor continuation is invalid")
        selected_daily = daily[-MAX_ROLLING_FACTOR_SESSIONS:]
        if any(not isinstance(item, Mapping) for item in selected_daily):
            raise KernelRunError("rolling Factor continuation is invalid")
        rolling_factor.extend(
            {"horizon": horizon, **dict(item)}
            for item in selected_daily
            if isinstance(item, Mapping)
        )
    return {
        "schema_version": "daily-track-working-state-v1",
        "pending_alpha": [dict(item) for item in selected_alpha if isinstance(item, Mapping)],
        "rolling_factor": rolling_factor,
    }


def empty_continuation() -> dict[str, object]:
    return {
        "schema_version": "daily-track-working-state-v1",
        "pending_alpha": [],
        "rolling_factor": [],
    }


def advance_continuation(
    *,
    run_input: RunInput,
    prior_continuation: Mapping[str, object],
    target_canonical: dict[str, object],
    appended_sessions: list[str],
) -> dict[str, object]:
    """Advance only the bounded transient Alpha and Factor working state."""
    restored = _with_continuation(
        {
            "alpha_matrix": {
                "expression": run_input.alpha_expression_snapshot(),
                "effective_lookback": MAX_ALPHA_LOOKBACK_SESSIONS,
                "neutralization": run_input.neutralization,
                "sessions": [],
            },
            "factor_evaluation": {
                "horizons": {
                    str(horizon): {"horizon": horizon, "daily": []} for horizon in HORIZONS
                }
            },
        },
        prior_continuation,
    )
    prior_alpha = _mapping(restored.get("alpha_matrix"), "prior Alpha continuation")
    prior_factor = _mapping(restored.get("factor_evaluation"), "prior Factor continuation")
    calendar = canonical_sessions(target_canonical, "Continuation rebuild")
    if not appended_sessions or any(session not in calendar for session in appended_sessions):
        raise KernelRunError("Continuation rebuild appended sessions are invalid")
    first_index = calendar.index(appended_sessions[0])
    window = slice_canonical_sessions(
        target_canonical,
        calendar[max(0, first_index - MAX_ALPHA_LOOKBACK_SESSIONS) :],
    )
    evaluated = evaluate_alpha_matrix(
        window,
        expression=run_input.alpha_expression_snapshot(),
        field_bindings=run_input.field_bindings_snapshot(),
        universe_name=run_input.universe,
        neutralization=run_input.neutralization,
    )
    evaluated_rows = evaluated.get("sessions")
    prior_rows = prior_alpha.get("sessions")
    if not isinstance(evaluated_rows, list) or not isinstance(prior_rows, list):
        raise KernelRunError("Continuation rebuild Alpha state is invalid")
    selected_set = set(calendar[-MAX_ROLLING_FACTOR_SESSIONS:])
    new_set = set(appended_sessions)
    alpha_rows = [dict(item) for item in prior_rows if isinstance(item, Mapping)]
    alpha_rows.extend(
        dict(item)
        for item in evaluated_rows
        if isinstance(item, Mapping)
        and str(item.get("session")) in new_set
        and str(item.get("session")) in selected_set
    )
    alpha_by_session = {str(item["session"]): item for item in alpha_rows}
    matrix = {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": int(evaluated["effective_lookback"]),
        "neutralization": run_input.neutralization,
        "sessions": list(alpha_by_session.values()),
        "checksum": alpha_matrix_checksum(list(alpha_by_session.values())),
    }
    prior_horizons = _mapping(prior_factor.get("horizons"), "prior Factor horizons")
    rolling_factor: list[dict[str, object]] = []
    for horizon in HORIZONS:
        affected = [
            session
            for session in affected_label_sessions(calendar, appended_sessions, horizon)
            if session in alpha_by_session and session in selected_set
        ]
        partial_daily: list[dict[str, object]] = []
        if affected:
            labels = build_forward_labels(
                target_canonical,
                matrix,
                signal_sessions=affected,
                horizons=(horizon,),
            )
            partial_factor = evaluate_factor(labels)
            partial_horizon = _mapping(
                _mapping(partial_factor.get("horizons"), "partial Factor horizons").get(
                    str(horizon)
                ),
                f"partial Factor horizon {horizon}",
            )
            value = partial_horizon.get("daily")
            if not isinstance(value, list):
                raise KernelRunError("Continuation rebuild Factor rows are invalid")
            partial_daily = [dict(item) for item in value if isinstance(item, Mapping)]
        prior_horizon = _mapping(
            prior_horizons.get(str(horizon)),
            f"prior Factor horizon {horizon}",
        )
        prior_daily = prior_horizon.get("daily")
        if not isinstance(prior_daily, list):
            raise KernelRunError("Continuation rebuild prior Factor rows are invalid")
        by_session = {
            str(item["session"]): dict(item)
            for item in prior_daily
            if isinstance(item, Mapping) and str(item.get("session")) in selected_set
        }
        by_session.update({str(item["session"]): item for item in partial_daily})
        rolling_factor.extend(
            {"horizon": horizon, **by_session[session]}
            for session in calendar[-MAX_ROLLING_FACTOR_SESSIONS:]
            if session in by_session
        )
    return {
        "schema_version": "daily-track-working-state-v1",
        "pending_alpha": [
            alpha_by_session[session]
            for session in calendar[-MAX_PENDING_ALPHA_SESSIONS:]
            if session in alpha_by_session
        ],
        "rolling_factor": rolling_factor,
    }


def _with_continuation(
    prior_output: dict[str, dict[str, object]],
    continuation: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    if set(continuation) != {"schema_version", "pending_alpha", "rolling_factor"} or (
        continuation.get("schema_version") != "daily-track-working-state-v1"
    ):
        raise KernelRunError("Advance continuation contract is invalid")
    pending = continuation.get("pending_alpha")
    rolling = continuation.get("rolling_factor")
    if (
        not isinstance(pending, list)
        or len(pending) > MAX_PENDING_ALPHA_SESSIONS
        or not isinstance(rolling, list)
        or len(rolling) > len(HORIZONS) * MAX_ROLLING_FACTOR_SESSIONS
    ):
        raise KernelRunError("Advance continuation bound is invalid")
    restored = json.loads(canonical_json_bytes(prior_output))
    alpha = _mapping(restored.get("alpha_matrix"), "prior Alpha Matrix")
    factor = _mapping(restored.get("factor_evaluation"), "prior Factor")
    alpha_sessions = alpha.get("sessions")
    if not isinstance(alpha_sessions, list):
        raise KernelRunError("prior Alpha Matrix sessions are invalid")
    if not alpha_sessions:
        alpha["sessions"] = [dict(item) for item in pending if isinstance(item, Mapping)]
    horizons = _mapping(factor.get("horizons"), "prior Factor horizons")
    by_horizon: dict[int, list[dict[str, object]]] = {}
    for item in rolling:
        if not isinstance(item, Mapping):
            raise KernelRunError("rolling Factor continuation row is invalid")
        row = dict(item)
        horizon = int(row.pop("horizon"))
        by_horizon.setdefault(horizon, []).append(row)
    for horizon in HORIZONS:
        horizon_value = _mapping(
            horizons.get(str(horizon)),
            f"prior Factor horizon {horizon}",
        )
        daily = horizon_value.get("daily")
        if not isinstance(daily, list):
            raise KernelRunError("prior Factor daily continuation is invalid")
        if not daily:
            horizon_value["daily"] = by_horizon.get(horizon, [])
    return restored


def _advance_alpha(
    run_input: RunInput,
    canonical: dict[str, object],
    prior_matrix: Mapping[str, object],
    new_sessions: list[str],
    prior_session_count: int,
) -> dict[str, object]:
    lookback = int(prior_matrix["effective_lookback"])
    calendar = canonical_sessions(canonical, "Canonical")
    window_start = max(0, prior_session_count - lookback)
    window = slice_canonical_sessions(canonical, calendar[window_start:])
    evaluated = evaluate_alpha_matrix(
        window,
        expression=run_input.alpha_expression_snapshot(),
        field_bindings=run_input.field_bindings_snapshot(),
        universe_name=run_input.universe,
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


def _advance_labels(
    canonical: dict[str, object],
    matrix: dict[str, object],
    prior_labels: Mapping[str, object],
    new_sessions: list[str],
) -> dict[str, object]:
    calendar = canonical_sessions(canonical, "Canonical")
    selected_sessions = calendar[-504:]
    selected_set = set(selected_sessions)
    prior_horizons = _mapping(prior_labels.get("horizons"), "prior Label horizons")
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        prior_horizon = _mapping(
            prior_horizons.get(str(horizon)),
            f"prior Label horizon {horizon}",
        )
        prior_rows = prior_horizon.get("sessions")
        if not isinstance(prior_rows, list):
            raise KernelRunError("prior Label sessions are invalid")
        affected_sessions = affected_label_sessions(calendar, new_sessions, horizon)
        partial = build_forward_labels(
            canonical,
            matrix,
            signal_sessions=affected_sessions,
            horizons=(horizon,),
        )
        partial_horizon = _mapping(
            _mapping(partial.get("horizons"), "partial Label horizons").get(str(horizon)),
            "partial Label horizon",
        )
        partial_rows = partial_horizon.get("sessions")
        if not isinstance(partial_rows, list):
            raise KernelRunError("partial Label sessions are invalid")
        by_session = {
            str(item["session"]): dict(item)
            for item in prior_rows
            if isinstance(item, Mapping) and str(item.get("session")) in selected_set
        }
        by_session.update(
            {str(item["session"]): dict(item) for item in partial_rows if isinstance(item, Mapping)}
        )
        if set(by_session) != selected_set:
            raise KernelRunError("Advance Label state is incomplete")
        sessions = [by_session[session] for session in selected_sessions]
        payload = {"horizon": horizon, "sessions": sessions}
        horizons[str(horizon)] = {
            **payload,
            "checksum": sha256(canonical_json_bytes(payload)).hexdigest(),
        }
    return {
        "alpha_checksum": matrix["checksum"],
        "report_session_count": len(selected_sessions),
        "horizons": horizons,
    }


def _advance_labels_from_continuation(
    canonical: dict[str, object],
    matrix: dict[str, object],
    new_sessions: list[str],
) -> dict[str, object]:
    """Recompute only labels whose value can change at this Release boundary."""
    calendar = canonical_sessions(canonical, "Canonical")
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        affected_sessions = affected_label_sessions(calendar, new_sessions, horizon)
        partial = build_forward_labels(
            canonical,
            matrix,
            signal_sessions=affected_sessions,
            horizons=(horizon,),
        )
        partial_horizon = _mapping(
            _mapping(partial.get("horizons"), "partial Label horizons").get(str(horizon)),
            f"partial Label horizon {horizon}",
        )
        horizons[str(horizon)] = dict(partial_horizon)
    return {
        "alpha_checksum": matrix["checksum"],
        "report_session_count": min(504, len(calendar)),
        "horizons": horizons,
    }


def _advance_factor(
    canonical: dict[str, object],
    labels: dict[str, object],
    prior_factor: Mapping[str, object],
    new_sessions: list[str],
    *,
    compact_continuation: bool = False,
) -> dict[str, object]:
    calendar = canonical_sessions(canonical, "Canonical")
    label_horizons = _mapping(labels.get("horizons"), "Label horizons")
    prior_horizons = _mapping(prior_factor.get("horizons"), "prior Factor horizons")
    partial_horizons: dict[str, object] = {}
    selected_by_horizon: dict[int, list[str]] = {}
    for horizon in HORIZONS:
        label_horizon = _mapping(
            label_horizons.get(str(horizon)),
            f"Label horizon {horizon}",
        )
        label_sessions = label_horizon.get("sessions")
        if not isinstance(label_sessions, list):
            raise KernelRunError("Factor Label sessions are invalid")
        label_selected = [
            str(item["session"]) for item in label_sessions if isinstance(item, Mapping)
        ]
        if len(label_selected) != len(label_sessions):
            raise KernelRunError("Factor Label session is invalid")
        selected = calendar[-504:] if compact_continuation else label_selected
        selected_by_horizon[horizon] = selected
        affected = set(affected_label_sessions(calendar, new_sessions, horizon))
        partial_horizons[str(horizon)] = {
            **dict(label_horizon),
            "sessions": [
                dict(item)
                for item in label_sessions
                if isinstance(item, Mapping) and str(item["session"]) in affected
            ],
        }
    partial = evaluate_factor(
        {
            "alpha_checksum": labels["alpha_checksum"],
            "horizons": partial_horizons,
        }
    )
    partial_factor_horizons = _mapping(
        partial.get("horizons"),
        "partial Factor horizons",
    )
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        selected = selected_by_horizon[horizon]
        selected_set = set(selected)
        prior_horizon = _mapping(
            prior_horizons.get(str(horizon)),
            f"prior Factor horizon {horizon}",
        )
        partial_horizon = _mapping(
            partial_factor_horizons.get(str(horizon)),
            f"partial Factor horizon {horizon}",
        )
        prior_daily = prior_horizon.get("daily")
        partial_daily = partial_horizon.get("daily")
        if not isinstance(prior_daily, list) or not isinstance(partial_daily, list):
            raise KernelRunError("Factor daily continuation is invalid")
        by_session = {
            str(item["session"]): dict(item)
            for item in prior_daily
            if isinstance(item, Mapping) and str(item.get("session")) in selected_set
        }
        by_session.update(
            {
                str(item["session"]): dict(item)
                for item in partial_daily
                if isinstance(item, Mapping)
                and str(item.get("session")) in selected_set
            }
        )
        if set(by_session) != selected_set:
            raise KernelRunError("Factor daily continuation is incomplete")
        label_horizon = _mapping(
            label_horizons.get(str(horizon)),
            f"Label horizon {horizon}",
        )
        horizons[str(horizon)] = factor_horizon_from_daily(
            horizon=horizon,
            alpha_checksum=str(labels["alpha_checksum"]),
            label_checksum=str(label_horizon["checksum"]),
            daily=[by_session[session] for session in selected],
        )
    return {"horizons": horizons}


def _accept_target_canonical_release(
    prior: dict[str, object],
    target: dict[str, object],
    appended_sessions: list[str],
) -> dict[str, object]:
    prior_calendar = prior.get("research_calendar")
    target_calendar = target.get("research_calendar")
    if not isinstance(prior_calendar, list) or not isinstance(target_calendar, list):
        raise KernelRunError("Advance requires canonical Research Sessions")
    new_sessions = [str(value) for value in appended_sessions]
    if not new_sessions:
        raise KernelRunError("Advance requires at least one new Research Session")
    prior_sessions = [str(value) for value in prior_calendar]
    selected_target = [str(value) for value in target_calendar]
    if (
        new_sessions != sorted(set(new_sessions))
        or selected_target[: len(prior_sessions)] != prior_sessions
        or selected_target[len(prior_sessions) :] != new_sessions
    ):
        raise KernelRunError("Advance Research Sessions must be new and canonically ordered")
    if target.get("schema_version") != prior.get("schema_version"):
        raise KernelRunError("Advance canonical schema does not match prior state")
    if target.get("field_catalog") != prior.get("field_catalog"):
        raise KernelRunError("Advance cannot replace pinned static table: field_catalog")
    return json.loads(canonical_json_bytes(target))


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
    canonical: dict[str, object],
) -> list[str] | None:
    if run_input.research_start_session is None and run_input.research_end_session is None:
        return None
    if run_input.research_start_session is None or run_input.research_end_session is None:
        raise KernelRunError("Advance Research Period boundaries are incomplete")
    calendar = canonical_sessions(canonical, "Canonical")
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
    canonical: dict[str, object],
    research_sessions: list[str],
) -> dict[str, object]:
    evaluated = evaluate_alpha_matrix(
        canonical,
        expression=run_input.alpha_expression_snapshot(),
        field_bindings=run_input.field_bindings_snapshot(),
        universe_name=run_input.universe,
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
