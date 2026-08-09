import copy

import pytest
from contracts import CLOSE_ADJUSTED, FIELD_BINDINGS, literal, operation

from thesistrace.research_kernel import KernelRunError, RunInput, run

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
    output = run(
        _run_input(
            canonical,
            expression=CLOSE_ADJUSTED,
            start=SESSIONS[0],
            end=SESSIONS[session_count - 1],
        )
    ).artifacts_snapshot()

    expected_sessions = list(SESSIONS[:session_count])
    assert [row["session"] for row in output["alpha_matrix"]["sessions"]] == expected_sessions
    assert output["forward_labels"]["report_session_count"] == session_count
    assert [row["session"] for row in output["strategy_backtest"]["daily"]] == expected_sessions
    for horizon in ("1", "5", "20"):
        summary = output["factor_evaluation"]["horizons"][horizon]["summary"]
        assert summary["ic"]["mean"] is None
        assert summary["ic"]["valid_session_count"] == 0


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
        KernelRunError,
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
    sessions = list(SESSIONS[:session_count])
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
        states.append(
            {"session": session, "instrument_id": INSTRUMENT_ID, "state": "normal"}
        )
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
        "base_pool": [
            {"session": session, "instrument_id": INSTRUMENT_ID} for session in sessions
        ],
        "liquidity_universes": {
            "manual": [
                {"session": session, "instrument_ids": [INSTRUMENT_ID]}
                for session in sessions
            ]
        },
        "industry_membership": [],
        "st_designations": [],
    }
