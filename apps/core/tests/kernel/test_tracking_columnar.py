from __future__ import annotations

import copy
import json
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
        _family_values=None,
        _field_columns=columns,
    )


def run_input(
    data, source, neutralization, holdings=10, rebalance=5, exposure="1", weighting="equal_weight",
):
    compiled = alpha_language.compile(source)
    exposure_compiled = alpha_language.compile(exposure, context="exposure")
    return RunInput(
        research_data=data,
        alpha_expression=compiled.expression,
        field_bindings={
            **FIELD_BINDINGS,
            **{value: key for key, value in compiled.field_ids_by_identifier.items()},
        },
        effective_lookback=max(
            compiled.effective_lookback, exposure_compiled.effective_lookback,
            20 if weighting == "inverse_volatility" else 0,
        ),
        universe="top300",
        neutralization=neutralization,
        research_kind="strategy_backtest",
        strategy=StrategyRunInput(
            holdings_count=holdings, selection_interval=rebalance, weighting=weighting,
            exposure_expression_json=json.dumps(exposure_compiled.expression).encode(),
            initial_cash_cny="10000000", commission_rate_all_in="0.0003",
            commission_min_cny="5", stamp_duty_sell_rate="0.0005", transfer_fee_rate="0.00001",
        ),
        research_start_session=data.sessions[20],
        research_end_session=data.sessions[-1],
    )


@pytest.mark.parametrize(("source", "neutralization", "holdings", "rebalance"), [
    ("rank(pct_change(close, 20))", "none", 10, 5),
    ("close * universe_advancing_fraction()", "none", 5, 3),
    ("if_else(close > ts_mean(close, 5), rank(close), -rank(close))", "none", 5, 3),
    ("-rank(pct_change(close, 20))", "none", 3, 1),
    ("ts_mean(close, 3) + ts_mean(close, 3)", "industry", 5, 3),
])
@pytest.mark.parametrize("exposure", [
    "1", "if_else(universe_advancing_fraction() > 0.5, 1, 0.3)",
])
@pytest.mark.parametrize("weighting", ["equal_weight", "rank_weight", "inverse_volatility"])
def test_columnar_tracking_matches_every_checkpoint_and_recovery_boundary(
    source, neutralization, holdings, rebalance, exposure, weighting, monkeypatch,
) -> None:
    from thesistrace.research_kernel import factor, kernel_advance, tracking_advance

    def forbidden_labels(*_args, **_kwargs):
        raise AssertionError("Tracking must not calculate future labels")

    monkeypatch.setattr(factor, "build_forward_labels", forbidden_labels)
    monkeypatch.setattr(factor, "prepare_columnar_forward_labels", forbidden_labels)
    # Also guard consumer bindings used by from-import calls.
    monkeypatch.setattr(kernel_advance, "build_forward_labels", forbidden_labels, raising=False)
    monkeypatch.setattr(
        tracking_advance, "prepare_columnar_forward_labels", forbidden_labels, raising=False,
    )
    _, canonical = build_fixture(session_count=68)
    row = aligned_market_data(canonical, neutralization=neutralization)
    calendar = list(row.sessions)
    initial = slice_research_sessions(row, calendar[:45])
    prior = run(
        run_input(initial, source, neutralization, holdings, rebalance, exposure, weighting),
    ).track_state
    observation = initial_tracking_observation_state(
        calendar[43], prior.output_snapshot()["strategy_backtest"]["daily"][-2]["net_nav"],
    )
    checkpoint = project_tracking_checkpoint(
        prior, prior_observation_state=observation,
        retained_strategy_sessions=[prior.boundary_session],
    )
    assert checkpoint["run_input"]["strategy"]["weighting"] == weighting
    assert checkpoint["run_input"]["strategy"]["volatility_window"] == 20
    if weighting == "inverse_volatility":
        assert checkpoint["run_input"]["effective_lookback"] == 20
    continuation = continuation_snapshot(prior)
    # Include a revised historical fact. Stored Alpha stays frozen; new Alpha
    # sees the corrected lookback without computing future labels.
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
                    state, retained_strategy_sessions=appended,
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
        if "universe_advancing_fraction" in source or "universe_advancing_fraction" in exposure:
            common = checkpoint["common_input_observations"]
            assert [item["session"] for item in common] == appended
            assert all(item["identifier"] == "universe_advancing_fraction" for item in common)
            assert all(item["valid_count"] > 0 for item in common)
            from pydantic import ValidationError

            from thesistrace.daily_track.models import KernelStateCheckpoint

            KernelStateCheckpoint.model_validate(checkpoint)
            incomplete = {**checkpoint, "common_input_observations": common[:-1]}
            with pytest.raises(ValidationError, match="common observations"):
                KernelStateCheckpoint.model_validate(incomplete)
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
    assert set(actual) == {"schema_version", "pending_alpha"}


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
        _family_values=pa.Table.from_pylist([
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


def test_mounted_daily_fields_match_single_run_and_tracking_without_source_access(
    tmp_path, monkeypatch,
) -> None:
    from datetime import UTC, datetime

    from thesistrace.adapters.tushare_provider import TushareAdapter
    from thesistrace.data import MountedGenerationStore
    from thesistrace.data.canonical_mapping import daily_basic_field_catalog, field_catalog
    from thesistrace.data.fields import DAILY_BASIC_FIELDS

    _, canonical = build_fixture(session_count=65)
    calendar = canonical["research_calendar"]
    instruments = sorted(row["instrument_id"] for row in canonical["instruments"])
    pe_id = "market.valuation.pe"
    turnover_id = "market.turnover.float_ratio"
    pe_values = {}
    turnover_values = {}
    observations = []
    for day, session in enumerate(calendar):
        for index, instrument in enumerate(instruments):
            # An entire collected date without observations must remain missing.
            if day == 40:
                continue
            pe = Decimal(10 + index + day % 3)
            turnover = Decimal("0.025")
            pe_values[session, instrument] = pe
            turnover_values[session, instrument] = turnover
            observations.append({
                **dict.fromkeys(field.source_column for field in DAILY_BASIC_FIELDS),
                "session": session, "instrument_id": instrument,
                "source_close": "999", "pe": str(pe), "turnover_rate": str(turnover),
            })
    canonical["daily_basic"] = observations
    canonical["daily_basic_sessions"] = [{"session": session} for session in calendar]
    canonical["field_catalog"] = [
        *field_catalog(calendar[-1]), *daily_basic_field_catalog(calendar[-1]),
    ]
    store = MountedGenerationStore(tmp_path)
    generation = store.materialize(
        canonical, prepared_at=datetime(2026, 9, 13, tzinfo=UTC),
        source_name="deterministic-test", source_lineage={},
    )

    def reject_source(*_args, **_kwargs):
        raise AssertionError("Research must use its mounted Generation")

    monkeypatch.setattr(TushareAdapter, "query_raw", reject_source)
    source = "rank(close_raw / pe + turnover_rate)"
    compiled = alpha_language.compile(source)
    bindings = {value: key for key, value in compiled.field_ids_by_identifier.items()}
    columnar = MountedGenerationStore(tmp_path).read_columnar_slice(
        generation.manifest_sha256, sessions=calendar, universe_name="top300",
        neutralization="none", field_bindings=bindings, fact_instrument_ids=frozenset(instruments),
    )
    row = aligned_market_data(canonical)
    row = replace(row, fields={
        **row.fields,
        pe_id: pe_values, turnover_id: turnover_values,
        "price.close.raw": {
            (price["session"], price["instrument_id"]): Decimal(str(price["close_raw"]))
            for price in canonical["prices"]
        },
    })
    value = run_input(row, source, "none")
    expected = run(value).track_state.output_snapshot()
    mounted_row = store.read_composite_slice(
        generation.manifest_sha256, sessions=calendar, universe_name="top300",
        neutralization="none", field_bindings=bindings,
    ).research_data
    actual = run(run_input(mounted_row, source, "none")).track_state.output_snapshot()
    assert actual == expected
    missing_day = next(item for item in actual["alpha_matrix"]["sessions"]
                       if item["session"] == calendar[40])
    assert missing_day["values"] == []
    expected_continuation, actual_continuation = empty_continuation(), empty_continuation()
    for start, end in ((20, 40), (40, 41), (41, 65)):
        sessions = calendar[max(0, start - 21):end]
        appended = calendar[start:end]
        expected_continuation = advance_continuation(
            run_input=value, prior_continuation=expected_continuation,
            target_research_data=slice_research_sessions(row, sessions),
            appended_sessions=appended,
        )
        actual_continuation = advance_tracking_continuation(
            run_input=value, prior_continuation=actual_continuation,
            target_research_data=slice_research_sessions(columnar, sessions),
            appended_sessions=appended,
        )
        assert actual_continuation == expected_continuation
