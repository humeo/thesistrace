import copy
from decimal import Decimal

import pytest
from fixture_sessions import append_fixture_session

from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
)
from thesistrace.fixture import build_fixture
from thesistrace.research_kernel import (
    AdvanceInput,
    KernelState,
    RunInput,
    advance,
    advance_continuation,
    continuation_snapshot,
    empty_continuation,
    run,
)
from thesistrace.research_kernel.canonical_state import slice_canonical_sessions
from thesistrace.research_kernel.strategy import advance_strategy_metric_state

FIELD_BINDINGS = {
    "price.open.adjusted": "open_adj",
    "price.high.adjusted": "high_adj",
    "price.low.adjusted": "low_adj",
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
    "market.turnover.cny": "turnover_amount_cny",
}


def test_kernel_advance_matches_the_characterized_state_at_the_same_boundary(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = accepted_kernel_state
    prior_output = prior.output_snapshot()
    advance_input = AdvanceInput(
        prior_state=prior,
        target_canonical_release=complete,
        appended_sessions=list(appended["research_calendar"]),
        continuation=continuation_snapshot(prior),
        calculation_scope="research_period",
    )

    appended["research_calendar"] = []
    result = advance(advance_input)
    expected_input = _run_input(complete, definition)
    expected = run(expected_input).artifacts_snapshot()
    output = result.output_snapshot()
    expected_sessions = list(complete["research_calendar"])[20:]

    assert result.output_snapshot() == expected
    assert result.origin_session == prior.origin_session
    assert result.session_count == prior.session_count + 1
    assert result.boundary_session == complete["research_calendar"][-1]
    assert prior.output_snapshot() == prior_output
    assert prior.session_count == len(canonical["research_calendar"])
    assert not {
        "run_id",
        "release_id",
        "request_id",
        "transaction",
        "object_key",
        "workspace_id",
        "mode",
    } & set(AdvanceInput.__dataclass_fields__)
    for field_name in AdvanceInput.__dataclass_fields__:
        assert not isinstance(getattr(advance_input, field_name), (dict, list, set))
    assert [item["session"] for item in output["alpha_matrix"]["sessions"]] == (
        expected_sessions
    )
    assert [item["session"] for item in output["strategy_backtest"]["daily"]] == (
        expected_sessions
    )
    for horizon in ("1", "5", "20"):
        assert [
            item["session"] for item in output["forward_labels"]["horizons"][horizon]["sessions"]
        ] == expected_sessions
        assert [
            item["session"]
            for item in output["factor_evaluation"]["horizons"][horizon]["daily"]
        ] == expected_sessions
    bounded = continuation_snapshot(result)
    assert len(bounded["pending_alpha"]) <= 21
    assert len(bounded["rolling_factor"]) <= 3 * 504


def test_kernel_advance_rejects_static_contract_replacement(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    complete["field_catalog"] = [{"field_id": "replacement"}]
    prior = accepted_kernel_state

    with pytest.raises(ValueError, match="cannot replace pinned static table"):
        advance(
            AdvanceInput(
                prior_state=prior,
                target_canonical_release=complete,
                appended_sessions=list(appended["research_calendar"]),
                continuation=continuation_snapshot(prior),
                calculation_scope="research_period",
            )
        )


def test_kernel_advance_uses_bounded_continuation_with_compact_prior_state(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = accepted_kernel_state
    with pytest.raises(
        ValueError,
        match="Forward Tracking Advance cannot carry Research Period boundaries",
    ):
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation_snapshot(prior),
            calculation_scope="forward_tracking",
        )
    expected = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation_snapshot(prior),
            calculation_scope="research_period",
        )
    )
    continuation = continuation_snapshot(prior)

    compact_output = prior.output_snapshot()
    compact_output["alpha_matrix"]["sessions"] = []
    compact_output["forward_labels"] = {"horizons": {}}
    for horizon in compact_output["factor_evaluation"]["horizons"].values():
        horizon["daily"] = []
    resume = prior.strategy_resume_snapshot()
    resume_daily = resume["daily"]
    terminal = resume_daily[-1]
    metric_state = advance_strategy_metric_state(
        None,
        daily=resume_daily,
        turnover_events=resume["metrics"]["turnover"]["events"],
        cumulative_cost=Decimal(str(terminal["cumulative_transaction_cost"])),
        rejections=resume["rejections"],
    )
    compact_prior = KernelState(
        run_input=prior.run_input_with_canonical(prior.canonical_snapshot()),
        output=compact_output,
        strategy_resume={
            "daily": resume_daily[-504:],
            "positions": resume["positions"],
            "report_session_count": metric_state["session_count"],
            "metric_state": metric_state,
        },
        origin_session=prior.origin_session,
    )

    actual = advance(
        AdvanceInput(
            prior_state=compact_prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation,
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
    for key in ("daily", "positions"):
        assert actual_output["strategy_backtest"][key] == expected_output["strategy_backtest"][key]
    assert _compact_metrics(actual_output["strategy_backtest"]["metrics"]) == (
        _compact_metrics(expected_output["strategy_backtest"]["metrics"])
    )

    with pytest.raises(TypeError, match="continuation"):
        AdvanceInput(
            prior_state=compact_prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            calculation_scope="research_period",
        )


def test_compact_advance_retains_exact_latest_504_factor_sessions(
) -> None:
    _, canonical = build_fixture(session_count=525)
    definition = {
        "alpha": {"expression": {"field_id": "price.close.adjusted"}},
        "neutralization": "none",
        "universe": "top300",
        "strategy": {
            "holdings_count": 10,
            "rebalance_interval": 5,
            "initial_cash_cny": "10000000",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
    }
    definition["alpha"] = {"expression": {"field_id": "price.close.adjusted"}}
    calendar = list(canonical["research_calendar"])
    seed_canonical = slice_canonical_sessions(canonical, calendar[:21])
    target_canonical = slice_canonical_sessions(canonical, calendar)
    explicit_seed = run(
        _run_input(
            seed_canonical,
            definition,
            research_start_session=calendar[0],
            research_end_session=calendar[20],
        )
    ).track_state
    seed = KernelState(
        run_input=_run_input(
            seed_canonical,
            definition,
            tracking_continuation=True,
        ),
        output=explicit_seed.output_snapshot(),
        strategy_resume=explicit_seed.strategy_resume_snapshot(),
        origin_session=explicit_seed.origin_session,
    )

    with pytest.raises(
        ValueError,
        match="Research Period Advance requires explicit boundaries",
    ):
        AdvanceInput(
            prior_state=seed,
            target_canonical_release=target_canonical,
            appended_sessions=calendar[21:],
            continuation=continuation_snapshot(seed),
            calculation_scope="research_period",
        )

    advanced = advance(
        AdvanceInput(
            prior_state=seed,
            target_canonical_release=target_canonical,
            appended_sessions=calendar[21:],
            continuation=continuation_snapshot(seed),
            calculation_scope="forward_tracking",
        )
    )

    horizons = advanced.output_snapshot()["factor_evaluation"]["horizons"]
    for horizon in ("1", "5", "20"):
        assert [item["session"] for item in horizons[horizon]["daily"]] == calendar[-504:]
        assert len(horizons[horizon]["daily"]) == 504


def test_kernel_rebuilds_only_bounded_alpha_and_factor_continuation(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = accepted_kernel_state
    expected = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation_snapshot(prior),
            calculation_scope="research_period",
        )
    )

    rebuilt = advance_continuation(
        run_input=prior.run_input_with_canonical(complete),
        prior_continuation=continuation_snapshot(prior),
        target_canonical=complete,
        appended_sessions=list(appended["research_calendar"]),
    )

    assert rebuilt == continuation_snapshot(expected)
    assert len(rebuilt["pending_alpha"]) == 21
    expected_factor_sessions = len(
        expected.output_snapshot()["factor_evaluation"]["horizons"]["1"]["daily"]
    )
    assert len(rebuilt["rolling_factor"]) == 3 * expected_factor_sessions


def test_ordinary_advance_and_rebuild_share_historical_correction_semantics(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    corrected, appended = append_fixture_session(canonical)
    uncorrected = copy.deepcopy(corrected)
    historical_session = canonical["research_calendar"][-20]
    corrected_price = next(
        row for row in corrected["prices"] if row["session"] == historical_session
    )
    corrected_price["close_adj"] = float(corrected_price["close_adj"]) * 1.25
    prior = accepted_kernel_state
    prior_canonical = prior.canonical_snapshot()
    appended_sessions = list(appended["research_calendar"])

    uncorrected_ordinary = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=uncorrected,
            appended_sessions=appended_sessions,
            continuation=continuation_snapshot(prior),
            calculation_scope="research_period",
        )
    )
    ordinary = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=corrected,
            appended_sessions=appended_sessions,
            continuation=continuation_snapshot(prior),
            calculation_scope="research_period",
        )
    )
    rebuilt = advance_continuation(
        run_input=prior.run_input_with_canonical(corrected),
        prior_continuation=continuation_snapshot(prior),
        target_canonical=corrected,
        appended_sessions=appended_sessions,
    )

    assert continuation_snapshot(ordinary) != continuation_snapshot(uncorrected_ordinary)
    assert ordinary.strategy_resume_snapshot() != uncorrected_ordinary.strategy_resume_snapshot()
    assert rebuilt == continuation_snapshot(ordinary)
    assert prior.canonical_snapshot() == prior_canonical


def test_kernel_rebuild_warms_from_empty_with_explicit_dependency_sessions(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    state = accepted_kernel_state
    calendar = list(canonical["research_calendar"])
    origin_index = calendar.index(state.origin_session)

    rebuilt = advance_continuation(
        run_input=state.run_input_with_canonical(canonical),
        prior_continuation=empty_continuation(),
        target_canonical=canonical,
        appended_sessions=calendar[origin_index:],
    )

    assert rebuilt == continuation_snapshot(state)


def test_daily_track_owns_minimal_tracking_checkpoint_projection_and_restoration(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    appended_session = appended["research_calendar"][0]
    for row in complete["prices"]:
        if row["session"] == appended_session:
            row["open_adj"] = float(row["open_adj"]) * 1.02
    prior = accepted_kernel_state
    advanced = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation_snapshot(prior),
            calculation_scope="research_period",
        )
    )

    checkpoint = project_tracking_checkpoint(
        advanced,
        retained_strategy_sessions=[prior.boundary_session, advanced.boundary_session],
    )
    delta = checkpoint["strategy_state"]["retained_delta"]
    assert len(delta) == 2
    assert set(delta[0]) == {
        "session",
        "gross_nav",
        "net_nav",
        "benchmark_nav",
        "net_cash",
        "transaction_cost_cny",
        "holdings_count",
        "maximum_single_name_weight",
        "upper_limit_buy_rejections",
        "lower_limit_sell_rejections",
        "suspension_rejections",
    }
    terminal = checkpoint["strategy_state"]["terminal"]
    assert set(terminal["continuation_observation"]) == {
        "session",
        "gross_cash",
        "net_cash",
        "cumulative_transaction_cost",
        "benchmark_nav",
        "gross_nav",
        "net_nav",
    }
    assert terminal["positions"] == advanced.output_snapshot()["strategy_backtest"]["positions"]
    assert terminal["continuation_positions"] == advanced.strategy_resume_snapshot()["positions"]
    assert terminal["positions"] != terminal["continuation_positions"]
    restored = restore_tracking_checkpoint(checkpoint, canonical=complete)

    complete_next, appended_next = append_fixture_session(complete)
    expected = advance(
        AdvanceInput(
            prior_state=advanced,
            target_canonical_release=complete_next,
            appended_sessions=list(appended_next["research_calendar"]),
            continuation=continuation_snapshot(advanced),
            calculation_scope="research_period",
        )
    )
    actual = advance(
        AdvanceInput(
            prior_state=restored,
            target_canonical_release=complete_next,
            appended_sessions=list(appended_next["research_calendar"]),
            continuation=continuation_snapshot(advanced),
            calculation_scope="forward_tracking",
        )
    )

    assert actual.boundary_session == complete_next["research_calendar"][-1]
    assert continuation_snapshot(actual) == continuation_snapshot(expected)
    actual_strategy = actual.output_snapshot()["strategy_backtest"]
    expected_strategy = expected.output_snapshot()["strategy_backtest"]
    assert actual_strategy["daily"][1:] == expected_strategy["daily"][-2:]
    assert actual_strategy["positions"] == expected_strategy["positions"]
    assert _compact_metrics(actual_strategy["metrics"]) == _compact_metrics(
        expected_strategy["metrics"]
    )


def test_kernel_advance_accepts_new_reference_facts_without_mutating_prior_state(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_state: KernelState,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = accepted_kernel_state
    prior_canonical = prior.canonical_snapshot()
    instruments = copy.deepcopy(canonical["instruments"])
    assert isinstance(instruments, list)
    instruments.append(
        {
            "instrument_id": "equity:688999.SH",
            "ts_code": "688999.SH",
            "asset_type": "ordinary_a_share",
            "exchange": "SSE",
            "board": "star",
            "listed_from": appended["research_calendar"][0],
            "listed_to": "",
        }
    )
    complete["instruments"] = instruments

    result = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation_snapshot(prior),
            calculation_scope="research_period",
        )
    )

    assert result.canonical_snapshot()["instruments"] == instruments
    assert prior.canonical_snapshot() == prior_canonical


def test_track_seed_is_the_seed_run_terminal_strategy_state(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = copy.deepcopy(accepted_calculation_case["definition"])
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    strategy = definition["strategy"]
    assert isinstance(strategy, dict)
    strategy["rebalance_interval"] = 1

    result = run(_run_input(canonical, definition))

    artifacts = result.artifacts_snapshot()
    assert (
        result.track_state.output_snapshot()["strategy_backtest"] == artifacts["strategy_backtest"]
    )

    complete, appended = append_fixture_session(canonical)
    advanced = advance(
        AdvanceInput(
            prior_state=result.track_state,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
            continuation=continuation_snapshot(result.track_state),
            calculation_scope="research_period",
        )
    )
    complete_input = _run_input(complete, definition)
    once_strategy = run(complete_input).artifacts_snapshot()["strategy_backtest"]
    advanced_strategy = advanced.output_snapshot()["strategy_backtest"]

    assert advanced_strategy == once_strategy
    assert advanced_strategy["daily"][-2]["rebalance"] is True


def _run_input(
    canonical: object,
    definition: dict[str, object],
    *,
    research_start_session: str | None = None,
    research_end_session: str | None = None,
    tracking_continuation: bool = False,
) -> RunInput:
    alpha = definition["alpha"]
    strategy = definition["strategy"]
    costs = definition["costs"]
    assert isinstance(canonical, dict)
    assert isinstance(alpha, dict)
    assert isinstance(strategy, dict)
    assert isinstance(costs, dict)
    calendar = canonical["research_calendar"]
    assert isinstance(calendar, list)
    if (
        research_start_session is None
        and research_end_session is None
        and not tracking_continuation
    ):
        research_start_session = str(calendar[20])
        research_end_session = str(calendar[-1])
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
        research_start_session=research_start_session,
        research_end_session=research_end_session,
    )


def _compact_metrics(value: object) -> object:
    metrics = copy.deepcopy(value)
    for parent, child in (
        ("maximum_drawdown", "series"),
        ("turnover", "events"),
        ("holdings_count", "daily"),
        ("maximum_single_name_weight", "daily"),
        ("cash_ratio", "daily"),
    ):
        metrics[parent].pop(child, None)
    return metrics
