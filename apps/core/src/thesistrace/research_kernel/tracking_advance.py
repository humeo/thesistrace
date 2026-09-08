"""Columnar DailyTrack calculation over bounded dependency slices.

Tracking retains pending Alpha and rolling Factor days, not row Label artifacts.
The row-oriented Advance entry points remain the independent calculation reference.
"""

from __future__ import annotations

from collections.abc import Mapping

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_columnar_alpha_sessions,
)
from thesistrace.research_kernel.factor import (
    HORIZONS,
    affected_label_sessions,
    prepare_columnar_forward_labels,
    summarize_factor_days,
)
from thesistrace.research_kernel.kernel_advance import (
    MAX_ROLLING_FACTOR_SESSIONS,
    AdvanceInput,
    _accept_target_research_data,
    _with_continuation,
    continuation_from_output,
)
from thesistrace.research_kernel.kernel_run import (
    KernelRunError,
    KernelState,
    RunInput,
    calculation_definition,
    compose_output,
)
from thesistrace.research_kernel.strategy import transition_columnar_strategy
from thesistrace.research_series import ColumnarResearchSeries


def advance_tracking(value: AdvanceInput) -> KernelState:
    if value.calculation_scope != "forward_tracking":
        raise KernelRunError("Columnar Tracking requires Forward Tracking scope")
    prior = value.prior_state()
    appended = value.appended_sessions_snapshot()
    data = _accept_target_research_data(
        prior.research_data_snapshot(), value.target_research_data_snapshot(), appended,
    )
    if not isinstance(data, ColumnarResearchSeries):
        raise KernelRunError("Tracking calculation requires columnar input")
    restored = _with_continuation(prior.output_snapshot(), value.continuation_snapshot())
    run_input = prior.run_input_with_research_data(data)
    matrix, factor = _tracking_delta(
        run_input, data, restored, appended,
    )
    strategy = transition_columnar_strategy(
        data, matrix, calculation_definition(run_input),
        origin_session=prior.origin_session,
        continuation=prior.strategy_resume_snapshot(),
        cancellation_check=lambda: None,
    )
    return KernelState(
        run_input=run_input,
        output=compose_output(matrix, {"horizons": {}}, factor, strategy.finalized),
        strategy_resume=strategy.resumable,
        origin_session=prior.origin_session,
    )


def advance_tracking_continuation(
    *,
    run_input: RunInput,
    prior_continuation: Mapping[str, object],
    target_research_data: ColumnarResearchSeries,
    appended_sessions: list[str],
) -> dict[str, object]:
    """Rebuild transient tracking state with the same delta calculation as warm Advance."""
    if not isinstance(target_research_data, ColumnarResearchSeries):
        raise KernelRunError("Tracking calculation requires columnar input")
    restored = _with_continuation(
        {
            "alpha_matrix": {"sessions": []},
            "factor_evaluation": {
                "horizons": {str(horizon): {"daily": []} for horizon in HORIZONS},
            },
        },
        prior_continuation,
    )
    matrix, factor = _tracking_delta(
        run_input, target_research_data, restored, appended_sessions,
    )
    return continuation_from_output({"alpha_matrix": matrix, "factor_evaluation": factor})


def _tracking_delta(
    run_input: RunInput,
    data: ColumnarResearchSeries,
    restored: dict[str, dict[str, object]],
    appended: list[str],
) -> tuple[dict[str, object], dict[str, object]]:
    calendar = list(data.sessions)
    if not appended or any(session not in calendar for session in appended):
        raise KernelRunError("Tracking appended sessions are invalid")
    first = calendar.index(appended[0])
    if appended != calendar[first:]:
        raise KernelRunError("Tracking appended sessions must be a canonical suffix")
    lookback = run_input.alpha_execution_plan().effective_lookback
    window = data.slice_sessions(tuple(calendar[max(0, first - lookback):]))
    evaluated = evaluate_columnar_alpha_sessions(
        window, compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization, cancellation_check=lambda: None,
    )
    selected = set(appended)
    new_rows = [row for row in evaluated["sessions"] if row["session"] in selected]
    if [row["session"] for row in new_rows] != appended:
        raise KernelRunError("Tracking Alpha calculation did not cover every new session")
    prior_rows = restored["alpha_matrix"]["sessions"]
    if not isinstance(prior_rows, list):
        raise KernelRunError("Tracking prior Alpha sessions are invalid")
    alpha_by_session = {str(row["session"]): row for row in [*prior_rows, *new_rows]}
    alpha_rows = [alpha_by_session[session] for session in sorted(alpha_by_session)]
    matrix = {
        "expression": run_input.alpha_expression_snapshot(),
        "effective_lookback": lookback,
        "neutralization": run_input.neutralization,
        "sessions": alpha_rows,
        "checksum": alpha_matrix_checksum(alpha_rows),
    }
    prior_horizons = restored["factor_evaluation"]["horizons"]
    retained = set(alpha_by_session)
    for horizon in HORIZONS:
        daily = prior_horizons[str(horizon)]["daily"]
        if not isinstance(daily, list):
            raise KernelRunError("Tracking prior Factor days are invalid")
        retained.update(str(day["session"]) for day in daily)
    retained_sessions = sorted(retained)[-MAX_ROLLING_FACTOR_SESSIONS:]
    retained_set = set(retained_sessions)
    affected = {
        horizon: [
            session for session in affected_label_sessions(calendar, appended, horizon)
            if session in alpha_by_session and session in retained_set
        ]
        for horizon in HORIZONS
    }
    # Labels need at most 21 prior sessions even when Alpha has a long lookback.
    label_start = max(0, first - max(HORIZONS) - 1)
    label_data = data.slice_sessions(tuple(calendar[label_start:])) if label_start else data
    prepared = prepare_columnar_forward_labels(label_data, cancellation_check=lambda: None)
    partial = prepared.factor_days_by_horizon(
        matrix, signal_sessions_by_horizon=affected, cancellation_check=lambda: None,
    )
    horizons: dict[str, object] = {}
    for horizon in HORIZONS:
        by_session = {
            str(day["session"]): day
            for day in [*prior_horizons[str(horizon)]["daily"], *partial[str(horizon)]]
            if str(day["session"]) in retained_set
        }
        daily = [by_session[session] for session in retained_sessions if session in by_session]
        horizons[str(horizon)] = {
            "horizon": horizon, "daily": daily, "summary": summarize_factor_days(daily),
        }
    return matrix, {"horizons": horizons}
