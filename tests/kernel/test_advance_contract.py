import copy
from decimal import Decimal

import pytest
from fixture_sessions import append_fixture_session

import thesistrace.research_kernel.kernel_advance as advance_module
from thesistrace.daily_track.checkpoint import (
    project_tracking_checkpoint,
    restore_tracking_checkpoint,
)
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
from thesistrace.research_kernel.alpha import evaluate_alpha_matrix
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.kernel_run import calculation_definition, compose_output
from thesistrace.research_kernel.strategy import (
    StrategyTransition,
    advance_strategy_metric_state,
    run_strategy,
)

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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = run(_run_input(canonical, definition)).track_state
    prior_output = prior.output_snapshot()
    advance_input = AdvanceInput(
        prior_state=prior,
        target_canonical_release=complete,
        appended_sessions=list(appended["research_calendar"]),
    )

    calls: dict[str, object] = {"label_sessions": [], "strategy_calls": []}
    original_alpha = advance_module.evaluate_alpha_matrix
    original_labels = advance_module.build_forward_labels
    original_factor = advance_module.evaluate_factor
    original_strategy_transition = advance_module.transition_strategy

    def observed_alpha(
        calculation_window: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        calls["alpha_session_count"] = len(calculation_window["research_calendar"])
        return original_alpha(calculation_window, **kwargs)

    def observed_labels(
        calculation_canonical: dict[str, object],
        matrix: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        signal_sessions = kwargs.get("signal_sessions")
        assert isinstance(signal_sessions, list)
        calls["label_sessions"].append(len(signal_sessions))
        return original_labels(calculation_canonical, matrix, **kwargs)

    def observed_strategy_transition(
        calculation_canonical: dict[str, object],
        matrix: dict[str, object],
        calculation_definition: dict[str, object],
        **kwargs: object,
    ) -> StrategyTransition:
        continuation = kwargs.get("continuation")
        assert isinstance(continuation, dict)
        prior_daily_count = len(continuation["daily"])
        transition = original_strategy_transition(
            calculation_canonical,
            matrix,
            calculation_definition,
            **kwargs,
        )
        calls["strategy_calls"].append(
            (
                prior_daily_count,
                len(transition.finalized["daily"]),
                len(transition.resumable["daily"]),
            )
        )
        return transition

    def observed_factor(labels: dict[str, object]) -> dict[str, object]:
        horizons = labels["horizons"]
        assert isinstance(horizons, dict)
        calls["factor_sessions"] = [
            len(horizons[horizon]["sessions"]) for horizon in sorted(horizons, key=int)
        ]
        return original_factor(labels)

    monkeypatch.setattr(advance_module, "evaluate_alpha_matrix", observed_alpha)
    monkeypatch.setattr(advance_module, "build_forward_labels", observed_labels)
    monkeypatch.setattr(advance_module, "evaluate_factor", observed_factor)
    monkeypatch.setattr(
        advance_module,
        "transition_strategy",
        observed_strategy_transition,
    )

    appended["research_calendar"] = []
    result = advance(advance_input)
    expected_input = _run_input(complete, definition)
    expected_matrix = evaluate_alpha_matrix(
        complete,
        expression=expected_input.alpha_expression_snapshot(),
        field_bindings=expected_input.field_bindings_snapshot(),
        universe_name=expected_input.universe,
        neutralization=expected_input.neutralization,
    )
    expected_labels = build_forward_labels(complete, expected_matrix)
    expected_factor = evaluate_factor(expected_labels)
    expected_strategy = run_strategy(
        complete,
        expected_matrix,
        calculation_definition(expected_input),
        origin_session=prior.origin_session,
    )
    expected = compose_output(
        expected_matrix,
        expected_labels,
        expected_factor,
        expected_strategy,
    )

    assert result.output_snapshot() == expected
    assert result.origin_session == prior.origin_session
    assert result.session_count == prior.session_count + 1
    assert result.boundary_session == complete["research_calendar"][-1]
    assert prior.output_snapshot() == prior_output
    assert prior.session_count == 756
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
    assert calls == {
        "alpha_session_count": 21,
        "label_sessions": [2, 2, 2],
        "factor_sessions": [2, 2, 2],
        "strategy_calls": [(503, 505, 504)],
    }


def test_kernel_advance_rejects_static_contract_replacement(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    complete["field_catalog"] = [{"field_id": "replacement"}]
    prior = run(_run_input(canonical, definition)).track_state

    with pytest.raises(ValueError, match="cannot replace pinned static table"):
        advance(
            AdvanceInput(
                prior_state=prior,
                target_canonical_release=complete,
                appended_sessions=list(appended["research_calendar"]),
            )
        )


def test_kernel_advance_uses_bounded_continuation_with_compact_prior_state(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = run(_run_input(canonical, definition)).track_state
    expected = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
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

    with pytest.raises(ValueError, match="prior Label horizon"):
        advance(
            AdvanceInput(
                prior_state=compact_prior,
                target_canonical_release=complete,
                appended_sessions=list(appended["research_calendar"]),
            )
        )


def test_kernel_rebuilds_only_bounded_alpha_and_factor_continuation(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = run(_run_input(canonical, definition)).track_state
    expected = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
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
    assert len(rebuilt["rolling_factor"]) == 1_512


def test_ordinary_advance_and_rebuild_share_historical_correction_semantics(
    accepted_calculation_case: dict[str, object],
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
    prior = run(_run_input(canonical, definition)).track_state
    appended_sessions = list(appended["research_calendar"])

    uncorrected_ordinary = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=uncorrected,
            appended_sessions=appended_sessions,
        )
    )
    ordinary = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=corrected,
            appended_sessions=appended_sessions,
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
    assert prior.canonical_snapshot() == canonical


def test_kernel_rebuild_warms_from_empty_with_fixed_525_session_tail(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    state = run(_run_input(canonical, definition)).track_state
    calendar = list(canonical["research_calendar"])

    rebuilt = advance_continuation(
        run_input=state.run_input_with_canonical(canonical),
        prior_continuation=empty_continuation(),
        target_canonical=canonical,
        appended_sessions=calendar[-525:],
    )

    assert rebuilt == continuation_snapshot(state)


def test_daily_track_owns_minimal_tracking_checkpoint_projection_and_restoration(
    accepted_calculation_case: dict[str, object],
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
    prior = run(_run_input(canonical, definition)).track_state
    advanced = advance(
        AdvanceInput(
            prior_state=prior,
            target_canonical_release=complete,
            appended_sessions=list(appended["research_calendar"]),
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
        )
    )
    actual = advance(
        AdvanceInput(
            prior_state=restored,
            target_canonical_release=complete_next,
            appended_sessions=list(appended_next["research_calendar"]),
            continuation=continuation_snapshot(advanced),
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
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    complete, appended = append_fixture_session(canonical)
    prior = run(_run_input(canonical, definition)).track_state
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
        )
    )
    complete_input = _run_input(complete, definition)
    complete_matrix = evaluate_alpha_matrix(
        complete,
        expression=complete_input.alpha_expression_snapshot(),
        field_bindings=complete_input.field_bindings_snapshot(),
        universe_name=complete_input.universe,
        neutralization=complete_input.neutralization,
    )
    once_strategy = run_strategy(
        complete,
        complete_matrix,
        calculation_definition(complete_input),
        origin_session=result.track_state.origin_session,
    )
    advanced_strategy = advanced.output_snapshot()["strategy_backtest"]

    assert advanced_strategy == once_strategy
    assert advanced_strategy["daily"][-2]["rebalance"] is True


def _run_input(canonical: object, definition: dict[str, object]) -> RunInput:
    alpha = definition["alpha"]
    strategy = definition["strategy"]
    costs = definition["costs"]
    assert isinstance(canonical, dict)
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
