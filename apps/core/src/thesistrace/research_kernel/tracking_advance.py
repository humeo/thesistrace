"""Columnar DailyTrack calculation over bounded dependency slices.

Tracking retains only the pending Alpha required for strategy execution.
The row-oriented Advance entry points remain the independent calculation reference.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_columnar_alpha_sessions,
)
from thesistrace.research_kernel.common_observations import (
    attach_common_input_evidence,
    record_common_input,
)
from thesistrace.research_kernel.kernel_advance import (
    AdvanceInput,
    _accept_target_research_data,
    _with_continuation,
    continuation_from_output,
    empty_continuation,
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


def advance_tracking(
    value: AdvanceInput, *, observe_holdings: Callable[[dict[str, object]], None] | None = None,
) -> KernelState:
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
    matrix = None if not run_input.has_alpha else _tracking_delta(
        run_input, data, restored, appended,
    )
    exposure_observations = {}
    strategy = transition_columnar_strategy(
        data, matrix, calculation_definition(run_input),
        origin_session=prior.origin_session,
        observe_common=lambda identifier, code, values: record_common_input(
            exposure_observations, tuple(data.sessions), identifier, code, values,
        ),
        continuation=prior.strategy_resume_snapshot(),
        observe_holdings=observe_holdings,
        cancellation_check=lambda: None,
    )
    if matrix is not None:
        attach_common_input_evidence(matrix, exposure_observations, tuple(appended))
    return KernelState(
        run_input=run_input,
        output=compose_output(matrix, strategy.finalized),
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
    if not run_input.has_alpha:
        _with_continuation({}, prior_continuation)
        return empty_continuation()
    restored = _with_continuation(
        {
            "alpha_matrix": {"sessions": []},
        },
        prior_continuation,
    )
    matrix = _tracking_delta(
        run_input, target_research_data, restored, appended_sessions,
    )
    return continuation_from_output({"alpha_matrix": matrix})


def _tracking_delta(
    run_input: RunInput,
    data: ColumnarResearchSeries,
    restored: dict[str, dict[str, object]],
    appended: list[str],
) -> dict[str, object]:
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
    return matrix
