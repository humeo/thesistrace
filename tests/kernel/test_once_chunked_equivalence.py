import copy

from fixture_sessions import extend_fixture_sessions

from thesistrace.research_kernel import (
    AdvanceInput,
    KernelState,
    advance,
    continuation_snapshot,
)
from thesistrace.research_kernel.canonical_state import slice_canonical_sessions
from thesistrace.research_kernel.equivalence import equivalence_bytes, first_divergence


def test_one_batch_and_multi_advance_reach_exactly_the_same_kernel_state(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(canonical, dict)
    complete, new_sessions = extend_fixture_sessions(canonical, count=4)
    seed = accepted_kernel_state

    one_batch = advance(
        AdvanceInput(
            prior_state=seed,
            target_canonical_release=complete,
            appended_sessions=new_sessions,
            continuation=continuation_snapshot(seed),
            calculation_scope="research_period",
        )
    )
    chunked = seed
    for chunk in (new_sessions[:1], new_sessions[1:3], new_sessions[3:]):
        chunked = advance(
            AdvanceInput(
                prior_state=chunked,
                target_canonical_release=_target_through(complete, chunk[-1]),
                appended_sessions=chunk,
                continuation=continuation_snapshot(chunked),
                calculation_scope="research_period",
            )
        )

    actual_evidence = _state_evidence(chunked)
    expected_evidence = _state_evidence(one_batch)
    assert equivalence_bytes(actual_evidence) == equivalence_bytes(
        expected_evidence
    ), first_divergence(actual_evidence, expected_evidence)
    assert chunked.origin_session == seed.origin_session
    assert chunked.boundary_session == new_sessions[-1]
    output = chunked.output_snapshot()
    labels = output["forward_labels"]
    factor = output["factor_evaluation"]
    strategy = output["strategy_backtest"]
    period_count = len(strategy["daily"])
    assert all(
        len(labels["horizons"][horizon]["sessions"]) == period_count
        for horizon in ("1", "5", "20")
    )
    assert all(
        len(factor["horizons"][horizon]["daily"]) == period_count
        for horizon in ("1", "5", "20")
    )
    assert (
        strategy["daily"][-1]["benchmark_nav"]
        == one_batch.output_snapshot()["strategy_backtest"]["daily"][-1]["benchmark_nav"]
    )


def test_equivalence_evidence_reports_the_first_divergent_boundary(
) -> None:
    expected = {
        "output": {
            "strategy_backtest": {
                "daily": [
                    {"benchmark_nav": "1"},
                    {"benchmark_nav": "2"},
                ]
            }
        }
    }
    mismatched = copy.deepcopy(expected)
    daily = mismatched["output"]["strategy_backtest"]["daily"]
    divergent_index = len(daily) - 2
    daily[divergent_index]["benchmark_nav"] = "semantic-mismatch"

    assert first_divergence(expected, mismatched) == (
        f"$.output.strategy_backtest.daily[{divergent_index}].benchmark_nav"
    )


def _state_evidence(state: KernelState) -> dict[str, object]:
    return {
        "origin_session": state.origin_session,
        "session_count": state.session_count,
        "boundary_session": state.boundary_session,
        "canonical": state.canonical_snapshot(),
        "output": state.output_snapshot(),
        "strategy_resume": state.strategy_resume_snapshot(),
    }


def _target_through(complete: dict[str, object], boundary: str) -> dict[str, object]:
    calendar = list(complete["research_calendar"])
    if boundary == calendar[-1]:
        return copy.deepcopy(complete)
    return slice_canonical_sessions(complete, calendar[: calendar.index(boundary) + 1])
