import copy

from fixture_sessions import extend_fixture_sessions

import thesistrace.tracking as tracking
from thesistrace.research_kernel import AdvanceInput, KernelState, RunInput, advance, run
from thesistrace.research_kernel.canonical_state import slice_canonical_sessions
from thesistrace.research_kernel.equivalence import equivalence_bytes, first_divergence

FIELD_BINDINGS = {
    "price.open.adjusted": "open_adj",
    "price.high.adjusted": "high_adj",
    "price.low.adjusted": "low_adj",
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
    "market.turnover.cny": "turnover_amount_cny",
}


def test_one_batch_and_multi_advance_reach_exactly_the_same_kernel_state(
    accepted_calculation_case: dict[str, object],
) -> None:
    canonical = accepted_calculation_case["canonical"]
    definition = accepted_calculation_case["definition"]
    assert isinstance(canonical, dict)
    assert isinstance(definition, dict)
    complete, new_sessions = extend_fixture_sessions(canonical, count=4)
    seed = run(_run_input(canonical, definition)).track_state

    one_batch = advance(
        AdvanceInput(
            prior_state=seed,
            target_canonical_release=complete,
            appended_sessions=new_sessions,
        )
    )
    chunked = seed
    for chunk in (new_sessions[:1], new_sessions[1:3], new_sessions[3:]):
        chunked = advance(
            AdvanceInput(
                prior_state=chunked,
                target_canonical_release=_target_through(complete, chunk[-1]),
                appended_sessions=chunk,
            )
        )

    assert first_divergence(_state_evidence(chunked), _state_evidence(one_batch)) == ""
    assert equivalence_bytes(_state_evidence(chunked)) == equivalence_bytes(
        _state_evidence(one_batch)
    )
    assert chunked.origin_session == seed.origin_session
    assert chunked.boundary_session == new_sessions[-1]
    output = chunked.output_snapshot()
    labels = output["forward_labels"]
    factor = output["factor_evaluation"]
    strategy = output["strategy_backtest"]
    assert all(len(labels["horizons"][horizon]["sessions"]) == 504 for horizon in ("1", "5", "20"))
    assert all(len(factor["horizons"][horizon]["daily"]) == 504 for horizon in ("1", "5", "20"))
    assert (
        strategy["daily"][-1]["benchmark_nav"]
        == one_batch.output_snapshot()["strategy_backtest"]["daily"][-1]["benchmark_nav"]
    )


def test_equivalence_evidence_reports_the_first_divergent_boundary(
    accepted_calculation_case: dict[str, object],
) -> None:
    canonical = accepted_calculation_case["canonical"]
    definition = accepted_calculation_case["definition"]
    assert isinstance(canonical, dict)
    assert isinstance(definition, dict)
    complete, new_sessions = extend_fixture_sessions(canonical, count=2)
    seed = run(_run_input(canonical, definition)).track_state
    state = advance(
        AdvanceInput(
            prior_state=seed,
            target_canonical_release=complete,
            appended_sessions=new_sessions,
        )
    )
    expected = _state_evidence(state)
    mismatched = copy.deepcopy(expected)
    daily = mismatched["output"]["strategy_backtest"]["daily"]
    divergent_index = len(daily) - 2
    daily[divergent_index]["benchmark_nav"] = "semantic-mismatch"

    assert first_divergence(expected, mismatched) == (
        f"$.output.strategy_backtest.daily[{divergent_index}].benchmark_nav"
    )


def test_tracking_uses_the_kernel_owned_equivalence_implementation() -> None:
    assert tracking.equivalence_bytes is equivalence_bytes
    assert tracking.first_divergence is first_divergence


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


def _run_input(canonical: dict[str, object], definition: dict[str, object]) -> RunInput:
    alpha = definition["alpha"]
    strategy = definition["strategy"]
    costs = definition["costs"]
    assert isinstance(alpha, dict)
    assert isinstance(strategy, dict)
    assert isinstance(costs, dict)
    return RunInput(
        canonical_data=canonical,
        alpha_expression=alpha["expression"],
        field_bindings=FIELD_BINDINGS,
        universe=str(definition["universe"]),
        neutralization=str(definition["neutralization"]),
        holdings_count=int(strategy["holdings_count"]),
        rebalance_interval=int(strategy["rebalance_interval"]),
        initial_cash_cny=str(strategy["initial_cash_cny"]),
        commission_rate_all_in=str(costs["commission_rate_all_in"]),
        commission_min_cny=str(costs["commission_min_cny"]),
        stamp_duty_sell_rate=str(costs["stamp_duty_sell_rate"]),
        transfer_fee_rate=str(costs["transfer_fee_rate"]),
    )
