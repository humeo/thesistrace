from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from contracts import FIELD_BINDINGS
from series import aligned_market_data

from thesistrace.alpha_language import alpha_language
from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
    terminal_strategy_state,
)
from thesistrace.daily_track.observation_state import (
    TrackingObservationState,
    initial_tracking_observation_state,
)
from thesistrace.data.columnar_series import ColumnarResearchData
from thesistrace.fixture import build_fixture
from thesistrace.research_kernel import (
    AdvanceInput,
    RunInput,
    StrategyRunInput,
    advance,
    advance_continuation,
    continuation_snapshot,
    empty_continuation,
    run,
)
from thesistrace.research_kernel.tracking_advance import (
    advance_tracking,
    advance_tracking_continuation,
)
from thesistrace.research_series import slice_research_sessions


def columnar_fixture(canonical) -> ColumnarResearchData:
    columns = dict(zip(FIELD_BINDINGS, (
        "open_adj", "high_adj", "low_adj", "close_adj", "volume_shares", "turnover_cny",
    ), strict=True))

    def coordinates(rows):
        return sorted(rows, key=lambda row: (row["session"], row["instrument_id"]))

    return ColumnarResearchData(
        sessions=tuple(canonical["research_calendar"]),
        _instruments=pa.Table.from_pylist(sorted(
            canonical["instruments"], key=lambda row: row["instrument_id"],
        )),
        _eod_prices=pa.Table.from_pylist([
            {
                "session_date": row["session"], "instrument_id": row["instrument_id"],
                "turnover_amount_cny": Decimal(str(row["turnover_cny"])),
                **{column: Decimal(str(row[column])) for column in {"open_raw", *columns.values()}},
            }
            for row in coordinates(canonical["prices"])
        ]),
        _universes=pa.Table.from_pylist(canonical["liquidity_universes"]["top300"]),
        _trading_states=pa.Table.from_pylist(coordinates(canonical["trading_states"])),
        _price_limits=pa.Table.from_pylist(coordinates(canonical["price_limits"])),
        _industries=pa.Table.from_pylist(canonical["industry_membership"]),
        _financial_values=None,
        _field_columns=columns,
    )


def run_input(data, source, neutralization, holdings=10, rebalance=5):
    compiled = alpha_language.compile(source)
    return RunInput(
        research_data=data,
        alpha_expression=compiled.expression,
        field_bindings={
            **FIELD_BINDINGS,
            **{value: key for key, value in compiled.field_ids_by_identifier.items()},
        },
        effective_alpha_lookback=compiled.effective_lookback,
        universe="top300",
        neutralization=neutralization,
        research_kind="strategy_backtest",
        strategy=StrategyRunInput(
            holdings_count=holdings, rebalance_interval=rebalance,
            initial_cash_cny="10000000", commission_rate_all_in="0.0003",
            commission_min_cny="5", stamp_duty_sell_rate="0.0005", transfer_fee_rate="0.00001",
        ),
        research_start_session=data.sessions[20],
        research_end_session=data.sessions[-1],
    )


@pytest.mark.parametrize(("source", "neutralization", "holdings", "rebalance"), [
    ("rank(pct_change(close, 20))", "none", 10, 5),
    ("-rank(pct_change(close, 20))", "none", 3, 1),
    ("ts_mean(close, 3) + ts_mean(close, 3)", "industry", 5, 3),
])
def test_columnar_tracking_matches_every_checkpoint_and_recovery_boundary(
    source, neutralization, holdings, rebalance,
) -> None:
    _, canonical = build_fixture(session_count=68)
    row = aligned_market_data(canonical, neutralization=neutralization)
    calendar = list(row.sessions)
    initial = slice_research_sessions(row, calendar[:45])
    prior = run(run_input(initial, source, neutralization, holdings, rebalance)).track_state
    observation = initial_tracking_observation_state(prior.boundary_session, "10000000")
    checkpoint = project_tracking_checkpoint(
        prior, prior_observation_state=observation,
        retained_strategy_sessions=[prior.boundary_session],
    )
    continuation = continuation_snapshot(prior)
    # Include a revised historical fact. Stored Alpha stays frozen; new Alpha
    # sees the corrected lookback and newly matured labels see current opens.
    corrected = copy.deepcopy(canonical)
    for price in corrected["prices"]:
        if price["session"] == calendar[40]:
            price["close_adj"] = float(price["close_adj"]) * 1.01
    columnar = columnar_fixture(corrected)
    row = aligned_market_data(corrected, neutralization=neutralization)
    start = 45
    for end in (46, 52, 68):
        target = calendar[max(0, start - 21):end]
        appended = calendar[start:end]
        outputs = []
        for data, calculate in ((row, advance), (columnar, advance_tracking)):
            prior_data = slice_research_sessions(data, target[:-len(appended)])
            restored = restore_tracking_checkpoint(checkpoint, research_data=prior_data)
            state = calculate(AdvanceInput(
                prior_state=restored,
                target_research_data=slice_research_sessions(data, target),
                appended_sessions=appended, continuation=continuation,
                calculation_scope="forward_tracking",
            ))
            outputs.append((
                project_tracking_checkpoint(
                    state, retained_strategy_sessions=[calendar[start - 1], *appended],
                    prior_observation_state=TrackingObservationState.model_validate(
                        checkpoint["tracking_observation_state"],
                    ),
                ),
                continuation_snapshot(state), terminal_strategy_state(state),
                state.output_snapshot()["alpha_matrix"],
                state.output_snapshot()["strategy_backtest"],
                state.strategy_resume_snapshot(),
            ))
        assert outputs[0] == outputs[1]
        checkpoint, continuation, *_ = outputs[1]
        start = end


@pytest.mark.parametrize("window", [20, 252])
def test_columnar_cold_rebuild_matches_row_reference_with_504_day_rollover(window) -> None:
    _, canonical = build_fixture(session_count=window + 515)
    row = aligned_market_data(canonical)
    columnar = columnar_fixture(canonical)
    value = run_input(row, f"ts_mean(close, {window})", "none")
    calendar = list(row.sessions)
    expected = empty_continuation()
    actual = empty_continuation()
    for start in range(window, len(calendar), 32):
        end = min(len(calendar), start + 32)
        sessions = calendar[max(0, start - max(window, 21)):end]
        appended = calendar[start:end]
        expected = advance_continuation(
            run_input=value, prior_continuation=expected,
            target_research_data=slice_research_sessions(row, sessions),
            appended_sessions=appended,
        )
        actual = advance_tracking_continuation(
            run_input=value, prior_continuation=actual,
            target_research_data=slice_research_sessions(columnar, sessions),
            appended_sessions=appended,
        )
        assert actual == expected
    assert len(actual["pending_alpha"]) == 21
    assert len(actual["rolling_factor"]) == 3 * 504


def test_columnar_tracking_preserves_aligned_financial_missingness_and_updates() -> None:
    _, canonical = build_fixture(session_count=65)
    row = aligned_market_data(canonical, neutralization="industry")
    columnar = columnar_fixture(canonical)
    field_id = "financial.income.total_revenue.latest_fy"
    values = {
        (session, instrument): Decimal((index % 7 + 1) * (1 + day // 40))
        for day, session in enumerate(row.sessions)
        for index, instrument in enumerate(sorted(row.instruments))
        if index % 5 or day >= 40
    }
    row = replace(row, fields={**row.fields, field_id: values})
    columnar = replace(
        columnar,
        _field_columns={**columnar._field_columns, field_id: field_id},
        _financial_values=pa.Table.from_pylist([
            {"session": session, "instrument_id": instrument, field_id: value}
            for (session, instrument), value in sorted(values.items())
        ]),
    )
    value = run_input(row, "rank(revenue) + rank(close)", "industry")
    expected, actual = empty_continuation(), empty_continuation()
    for start, end in ((20, 40), (40, 65)):
        sessions = row.sessions[max(0, start - 21):end]
        appended = list(row.sessions[start:end])
        expected = advance_continuation(
            run_input=value, prior_continuation=expected,
            target_research_data=slice_research_sessions(row, sessions),
            appended_sessions=appended,
        )
        actual = advance_tracking_continuation(
            run_input=value, prior_continuation=actual,
            target_research_data=slice_research_sessions(columnar, sessions),
            appended_sessions=appended,
        )
        assert actual == expected


def test_columnar_tracking_advances_through_an_empty_universe_then_recovers() -> None:
    _, canonical = build_fixture(session_count=25)
    calendar = canonical["research_calendar"]
    for universe in canonical["liquidity_universes"]["top300"]:
        if universe["session"] == calendar[-2]:
            universe["instrument_ids"] = []
    row, columnar = aligned_market_data(canonical), columnar_fixture(canonical)
    value = run_input(row, "ts_mean(close, 1)", "none")
    expected, actual = empty_continuation(), empty_continuation()
    for session in calendar[-2:]:
        expected = advance_continuation(
            run_input=value, prior_continuation=expected,
            target_research_data=slice_research_sessions(row, [session]),
            appended_sessions=[session],
        )
        actual = advance_tracking_continuation(
            run_input=value, prior_continuation=actual,
            target_research_data=slice_research_sessions(columnar, [session]),
            appended_sessions=[session],
        )
        assert actual == expected
    assert actual["pending_alpha"][0]["values"] == []
    assert actual["pending_alpha"][1]["values"]
