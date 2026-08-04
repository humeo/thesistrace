import copy

import pytest
from fixture_sessions import append_fixture_session

import thesistrace.research_kernel.kernel_advance as advance_module
from thesistrace.research_kernel import (
    AdvanceInput,
    RunInput,
    advance,
    run,
)
from thesistrace.research_kernel.alpha import evaluate_alpha_matrix
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.kernel_run import calculation_definition, compose_output
from thesistrace.research_kernel.strategy import StrategyTransition, run_strategy

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
        new_canonical_sessions=appended,
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
    _complete, appended = append_fixture_session(canonical)
    appended["field_catalog"] = [{"field_id": "replacement"}]
    prior = run(_run_input(canonical, definition)).track_state

    with pytest.raises(ValueError, match="cannot replace pinned static table"):
        advance(
            AdvanceInput(
                prior_state=prior,
                new_canonical_sessions=appended,
            )
        )


def test_kernel_advance_accepts_new_reference_facts_without_mutating_prior_state(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    canonical = accepted_calculation_case["canonical"]
    assert isinstance(definition, dict)
    assert isinstance(canonical, dict)
    _complete, appended = append_fixture_session(canonical)
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
    appended["instruments"] = instruments

    result = advance(
        AdvanceInput(
            prior_state=prior,
            new_canonical_sessions=appended,
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
            new_canonical_sessions=appended,
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
