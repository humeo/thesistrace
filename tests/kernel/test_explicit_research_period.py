import copy
from datetime import date, timedelta

import pytest
from contracts import CLOSE_ADJUSTED, FIELD_BINDINGS, literal, operation

from thesistrace.research_kernel import (
    AdvanceInput,
    InsufficientCalculationWarmupError,
    KernelRunError,
    KernelState,
    RunInput,
    advance,
    continuation_snapshot,
    run,
)
from thesistrace.research_kernel.canonical_state import slice_canonical_sessions
from thesistrace.research_kernel.equivalence import equivalence_bytes, first_divergence
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_run.result import build_result_payload, result_publication_payloads

SESSIONS = (
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
    "2024-01-08",
)
INSTRUMENT_ID = "equity:600000.SH"


@pytest.mark.parametrize("session_count", [1, 2, 4])
def test_explicit_research_period_accepts_any_positive_session_count(session_count: int) -> None:
    canonical = _canonical(session_count=session_count)
    run_output = run(
        _run_input(
            canonical,
            expression=CLOSE_ADJUSTED,
            start=SESSIONS[0],
            end=SESSIONS[session_count - 1],
        )
    )
    output = run_output.artifacts_snapshot()

    expected_sessions = list(SESSIONS[:session_count])
    assert [row["session"] for row in output["alpha_matrix"]["sessions"]] == expected_sessions
    assert output["forward_labels"]["report_session_count"] == session_count
    assert [row["session"] for row in output["strategy_backtest"]["daily"]] == expected_sessions
    for horizon in ("1", "5", "20"):
        summary = output["factor_evaluation"]["horizons"][horizon]["summary"]
        assert summary["ic"]["mean"] is None
        assert summary["ic"]["valid_session_count"] == 0
    if session_count == 1:
        resumable = run_output.track_state.strategy_resume_snapshot()
        assert [row["session"] for row in resumable["daily"]] == expected_sessions
        assert resumable["daily"][0]["cycle_type"] == "open"
        assert resumable["positions"] == []


@pytest.mark.parametrize("session_count", [1, 2, 4])
def test_explicit_research_period_projects_four_variable_length_result_values(
    session_count: int,
) -> None:
    output = run(
        _run_input(
            _canonical(session_count=session_count),
            expression=CLOSE_ADJUSTED,
            start=SESSIONS[0],
            end=SESSIONS[session_count - 1],
        )
    )

    result = build_result_payload(output, rebalance_interval=1, universe="manual")
    payloads = result_publication_payloads(result)

    assert set(result) == {
        "factor_summary",
        "strategy_summary",
        "strategy_daily_observations",
        "terminal_strategy_state",
    }
    assert len(result["strategy_daily_observations"]) == session_count
    assert "strategy_daily_observations.part-000000" in payloads
    serialized = canonical_json_bytes(result)
    for excluded in (
        b"strategy_ledger",
        b"alpha_matrix",
        b"forward_labels",
        b"orders",
        b"fills",
        b"position_history",
    ):
        assert excluded not in serialized


def test_explicit_research_period_rejects_empty_reversed_or_partial_boundaries() -> None:
    canonical = _canonical(session_count=3)

    with pytest.raises(KernelRunError, match="first session is after"):
        run(
            _run_input(
                canonical,
                expression=CLOSE_ADJUSTED,
                start=SESSIONS[2],
                end=SESSIONS[1],
            )
        )
    with pytest.raises(KernelRunError, match="not a canonical Research Session"):
        run(
            _run_input(
                canonical,
                expression=CLOSE_ADJUSTED,
                start="2024-01-06",
                end="2024-01-06",
            )
        )
    with pytest.raises(KernelRunError, match="requires both"):
        run(
            _run_input(
                canonical,
                expression=CLOSE_ADJUSTED,
                start=SESSIONS[0],
                end=None,
            )
        )


def test_calculation_warmup_is_derived_and_excluded_from_every_reported_session() -> None:
    canonical = _canonical(session_count=5)
    expression = operation("pct_change", CLOSE_ADJUSTED, literal(1))
    output = run(
        _run_input(
            canonical,
            expression=expression,
            start=SESSIONS[1],
            end=SESSIONS[3],
        )
    ).artifacts_snapshot()

    period = list(SESSIONS[1:4])
    assert output["alpha_matrix"]["effective_lookback"] == 1
    assert [row["session"] for row in output["alpha_matrix"]["sessions"]] == period
    assert [row["session"] for row in output["diagnostics"]["alpha_coverage"]] == period
    assert [row["session"] for row in output["strategy_backtest"]["daily"]] == period
    for horizon in ("1", "5", "20"):
        assert [
            row["session"] for row in output["forward_labels"]["horizons"][horizon]["sessions"]
        ] == period
        assert [
            row["session"] for row in output["factor_evaluation"]["horizons"][horizon]["daily"]
        ] == period


def test_incomplete_derived_warmup_fails_without_moving_the_period() -> None:
    canonical = _canonical(session_count=2)
    expression = operation("pct_change", CLOSE_ADJUSTED, literal(1))

    with pytest.raises(
        InsufficientCalculationWarmupError,
        match=r"insufficient Calculation Warm-up: requires 1 sessions before 2024-01-02",
    ):
        run(
            _run_input(
                canonical,
                expression=expression,
                start=SESSIONS[0],
                end=SESSIONS[1],
            )
        )


def test_forward_labels_and_results_never_read_after_the_period_end() -> None:
    canonical = _canonical(session_count=4)
    changed_future = copy.deepcopy(canonical)
    for row in changed_future["prices"]:
        if row["session"] in SESSIONS[2:]:
            row["open_raw"] = "9999"
            row["open_adj"] = "9999"
            row["close_adj"] = "9999"

    baseline = run(
        _run_input(
            canonical,
            expression=CLOSE_ADJUSTED,
            start=SESSIONS[0],
            end=SESSIONS[1],
        )
    ).artifacts_snapshot()
    changed = run(
        _run_input(
            changed_future,
            expression=CLOSE_ADJUSTED,
            start=SESSIONS[0],
            end=SESSIONS[1],
        )
    ).artifacts_snapshot()

    assert changed == baseline
    for horizon in ("1", "5", "20"):
        last = baseline["forward_labels"]["horizons"][horizon]["sessions"][-1]
        assert last["samples"] == []


def test_terminal_valuation_retains_holdings_without_a_final_order() -> None:
    canonical = _canonical(session_count=3)
    output = run(
        _run_input(
            canonical,
            expression=CLOSE_ADJUSTED,
            start=SESSIONS[0],
            end=SESSIONS[2],
        )
    ).artifacts_snapshot()
    strategy = output["strategy_backtest"]

    assert strategy["daily"][-1]["cycle_type"] == "terminal_valuation"
    assert strategy["positions"]
    assert all(order["session"] != SESSIONS[2] for order in strategy["orders"])


@pytest.mark.parametrize(
    "expression,start_index,seed_end_index,chunks",
    [
        (CLOSE_ADJUSTED, 0, 0, ((1,), (2, 3), (4,))),
        (operation("pct_change", CLOSE_ADJUSTED, literal(1)), 1, 1, ((2, 3, 4),)),
        (operation("pct_change", CLOSE_ADJUSTED, literal(1)), 1, 2, ((3,), (4,))),
    ],
)
def test_explicit_period_advance_matches_batch_across_irregular_chunks(
    expression: dict[str, object],
    start_index: int,
    seed_end_index: int,
    chunks: tuple[tuple[int, ...], ...],
) -> None:
    complete = _canonical(session_count=5)
    start = SESSIONS[start_index]
    expected = run(
        _run_input(
            complete,
            expression=expression,
            start=start,
            end=SESSIONS[-1],
        )
    ).track_state
    seed = run(
        _run_input(
            complete,
            expression=expression,
            start=start,
            end=SESSIONS[seed_end_index],
        )
    ).track_state

    actual = seed
    for chunk in chunks:
        boundary = SESSIONS[chunk[-1]]
        actual = advance(
            AdvanceInput(
                prior_state=actual,
                target_canonical_data=slice_canonical_sessions(
                    complete,
                    list(SESSIONS[: SESSIONS.index(boundary) + 1]),
                ),
                appended_sessions=[SESSIONS[index] for index in chunk],
                continuation=continuation_snapshot(actual),
                calculation_scope="research_period",
            )
        )

    actual_evidence = _retained_evidence(actual)
    expected_evidence = _retained_evidence(expected)
    assert equivalence_bytes(actual_evidence) == equivalence_bytes(expected_evidence), (
        first_divergence(actual_evidence, expected_evidence)
    )
    assert (
        actual.run_input_with_canonical(actual.canonical_snapshot()).research_end_session
        == SESSIONS[-1]
    )


def test_explicit_period_advance_rebuilds_the_same_bounded_continuation() -> None:
    complete = _canonical(session_count=5)
    expression = operation("pct_change", CLOSE_ADJUSTED, literal(1))
    expected = run(
        _run_input(
            complete,
            expression=expression,
            start=SESSIONS[1],
            end=SESSIONS[-1],
        )
    ).track_state
    seed = run(
        _run_input(
            complete,
            expression=expression,
            start=SESSIONS[1],
            end=SESSIONS[2],
        )
    ).track_state

    actual = advance(
        AdvanceInput(
            prior_state=seed,
            target_canonical_data=complete,
            appended_sessions=list(SESSIONS[3:]),
            continuation=continuation_snapshot(seed),
            calculation_scope="research_period",
        )
    )

    assert continuation_snapshot(actual) == continuation_snapshot(expected)
    actual_output = actual.output_snapshot()
    expected_output = expected.output_snapshot()
    for horizon in ("1", "5", "20"):
        assert (
            actual_output["factor_evaluation"]["horizons"][horizon]["summary"]
            == expected_output["factor_evaluation"]["horizons"][horizon]["summary"]
        )
    assert actual_output["strategy_backtest"] == expected_output["strategy_backtest"]
    assert actual.strategy_resume_snapshot() == expected.strategy_resume_snapshot()


@pytest.mark.parametrize(
    "seed_session_count,chunk_sizes",
    [
        (23, (1,)),
        (500, (2, 1, 2)),
    ],
)
def test_bounded_continuation_preserves_full_explicit_period_results(
    seed_session_count: int,
    chunk_sizes: tuple[int, ...],
) -> None:
    sessions = _business_sessions(seed_session_count + sum(chunk_sizes))
    complete = _canonical_for_sessions(sessions)
    expected = run(
        _run_input(
            complete,
            expression=CLOSE_ADJUSTED,
            start=sessions[0],
            end=sessions[-1],
        )
    ).track_state
    seed_canonical = slice_canonical_sessions(
        complete,
        sessions[:seed_session_count],
    )
    actual = run(
        _run_input(
            seed_canonical,
            expression=CLOSE_ADJUSTED,
            start=sessions[0],
            end=sessions[seed_session_count - 1],
        )
    ).track_state

    cursor = seed_session_count
    for chunk_size in chunk_sizes:
        appended = sessions[cursor : cursor + chunk_size]
        cursor += chunk_size
        compact_prior, bounded = _compact_for_continuation(actual)
        actual = advance(
            AdvanceInput(
                prior_state=compact_prior,
                target_canonical_data=slice_canonical_sessions(
                    complete,
                    sessions[:cursor],
                ),
                appended_sessions=appended,
                continuation=bounded,
                calculation_scope="research_period",
            )
        )

    actual_evidence = _retained_evidence(actual)
    expected_evidence = _retained_evidence(expected)
    assert equivalence_bytes(actual_evidence) == equivalence_bytes(expected_evidence), (
        first_divergence(actual_evidence, expected_evidence)
    )
    assert len(actual.output_snapshot()["alpha_matrix"]["sessions"]) == len(sessions)
    for horizon in ("1", "5", "20"):
        assert len(
            actual.output_snapshot()["factor_evaluation"]["horizons"][horizon]["daily"]
        ) == len(sessions)


def _retained_evidence(state: KernelState) -> dict[str, object]:
    return {
        "origin_session": state.origin_session,
        "session_count": state.session_count,
        "boundary_session": state.boundary_session,
        "canonical": state.canonical_snapshot(),
        "output": state.output_snapshot(),
        "strategy_resume": state.strategy_resume_snapshot(),
    }


def _compact_for_continuation(
    state: KernelState,
) -> tuple[KernelState, dict[str, object]]:
    bounded = continuation_snapshot(state)
    output = state.output_snapshot()
    output["alpha_matrix"]["sessions"] = []
    output["forward_labels"] = {"horizons": {}}
    for horizon in output["factor_evaluation"]["horizons"].values():
        horizon["daily"] = []
    compact = KernelState(
        run_input=state.run_input_with_canonical(state.canonical_snapshot()),
        output=output,
        strategy_resume=state.strategy_resume_snapshot(),
        origin_session=state.origin_session,
    )
    assert compact.output_snapshot()["alpha_matrix"]["sessions"] == []
    return compact, bounded


def _run_input(
    canonical: dict[str, object],
    *,
    expression: dict[str, object],
    start: str | None,
    end: str | None,
) -> RunInput:
    return RunInput(
        canonical_data=canonical,
        alpha_expression=expression,
        field_bindings=FIELD_BINDINGS,
        universe="manual",
        neutralization="none",
        holdings_count=1,
        rebalance_interval=1,
        initial_cash_cny="10000000",
        commission_rate_all_in="0.0003",
        commission_min_cny="5",
        stamp_duty_sell_rate="0.0005",
        transfer_fee_rate="0.00001",
        research_start_session=start,
        research_end_session=end,
    )


def _canonical(*, session_count: int) -> dict[str, object]:
    return _canonical_for_sessions(list(SESSIONS[:session_count]))


def _canonical_for_sessions(sessions: list[str]) -> dict[str, object]:
    prices = []
    states = []
    limits = []
    for index, session in enumerate(sessions):
        price = str(10 + index)
        prices.append(
            {
                "session": session,
                "instrument_id": INSTRUMENT_ID,
                "open_raw": price,
                "open_adj": price,
                "high_adj": price,
                "low_adj": price,
                "close_adj": price,
                "volume_shares": "1000000",
                "turnover_cny": "10000000",
            }
        )
        states.append({"session": session, "instrument_id": INSTRUMENT_ID, "state": "normal"})
        limits.append(
            {
                "session": session,
                "instrument_id": INSTRUMENT_ID,
                "upper": str((10 + index) * 2),
                "lower": "1",
            }
        )
    return {
        "schema_version": "test.explicit-period.v1",
        "research_calendar": sessions,
        "instruments": [
            {
                "instrument_id": INSTRUMENT_ID,
                "board": "main",
                "listed_from": sessions[0],
                "listed_to": "",
            }
        ],
        "prices": prices,
        "trading_states": states,
        "price_limits": limits,
        "base_pool": [{"session": session, "instrument_id": INSTRUMENT_ID} for session in sessions],
        "liquidity_universes": {
            "manual": [
                {"session": session, "instrument_ids": [INSTRUMENT_ID]} for session in sessions
            ]
        },
        "industry_membership": [],
    }


def _business_sessions(session_count: int) -> list[str]:
    sessions: list[str] = []
    candidate = date(2024, 1, 2)
    while len(sessions) < session_count:
        if candidate.weekday() < 5:
            sessions.append(candidate.isoformat())
        candidate += timedelta(days=1)
    return sessions
