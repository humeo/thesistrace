import copy
from dataclasses import FrozenInstanceError

import pytest

from thesistrace.research_kernel import KernelRunError, KernelState, RunInput, RunOutput, run
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_run.result import build_result_payload

FIELD_BINDINGS = {
    "price.open.adjusted": "open_adj",
    "price.high.adjusted": "high_adj",
    "price.low.adjusted": "low_adj",
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
    "market.turnover.cny": "turnover_amount_cny",
}


def test_kernel_run_matches_the_complete_characterization_baseline(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_run: RunOutput,
) -> None:
    run_output = accepted_kernel_run
    output = run_output.artifacts_snapshot()

    assert isinstance(run_output, RunOutput)
    assert isinstance(run_output.track_state, KernelState)
    assert output["alpha_matrix"] == accepted_calculation_case["alpha_matrix"]
    assert output["forward_labels"] == accepted_calculation_case["forward_labels"]
    assert output["factor_evaluation"] == accepted_calculation_case["factor_evaluation"]
    assert output["strategy_backtest"] == accepted_calculation_case["strategy_backtest"]
    assert output["diagnostics"] == accepted_calculation_case["diagnostics"]
    assert not isinstance(run_output, dict)
    output["diagnostics"] = {}
    assert (
        run_output.artifacts_snapshot()["diagnostics"] == accepted_calculation_case["diagnostics"]
    )


def test_strategy_ledger_is_transient_and_rejected_from_product_state(
    accepted_kernel_run: RunOutput,
) -> None:
    artifacts = accepted_kernel_run.artifacts_snapshot()
    ledger = accepted_kernel_run.strategy_ledger_snapshot()
    assert isinstance(ledger, list)
    assert len(ledger) == len(artifacts["strategy_backtest"]["daily"])
    assert "strategy_ledger" not in artifacts
    assert "strategy_ledger" not in accepted_kernel_run.track_state.output_snapshot()

    result = build_result_payload(
        accepted_kernel_run,
        rebalance_interval=5,
        universe="top300",
    )
    assert set(result) == {
        "factor_summary",
        "strategy_summary",
        "strategy_daily_observations",
        "terminal_strategy_state",
    }
    assert b"strategy_ledger" not in canonical_json_bytes(result)


def test_kernel_run_input_snapshots_values_and_has_no_product_context(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_run: RunOutput,
) -> None:
    canonical = copy.deepcopy(accepted_calculation_case["canonical"])
    definition = copy.deepcopy(accepted_calculation_case["definition"])
    assert isinstance(canonical, dict)
    assert isinstance(definition, dict)
    run_input = _run_input(canonical, definition)
    expected = accepted_kernel_run.artifacts_snapshot()

    canonical["research_calendar"] = []
    definition["universe"] = "top3000"

    assert run(run_input).artifacts_snapshot() == expected
    assert not {
        "run_id",
        "release_id",
        "request_id",
        "transaction",
        "object_key",
        "workspace_id",
        "mode",
    } & set(RunInput.__dataclass_fields__)
    with pytest.raises(FrozenInstanceError):
        run_input.universe = "top1000"
    for field_name in RunInput.__dataclass_fields__:
        assert not isinstance(getattr(run_input, field_name), (dict, list, set))

    expression = run_input.alpha_expression_snapshot()
    assert isinstance(expression, dict)


def test_kernel_run_input_does_not_expose_mutable_expression_state(
    accepted_calculation_case: dict[str, object],
    accepted_kernel_run: RunOutput,
) -> None:
    canonical = accepted_calculation_case["canonical"]
    definition = copy.deepcopy(accepted_calculation_case["definition"])
    assert isinstance(definition, dict)
    definition["alpha"] = {
        "expression": {
            "operator_id": "pct_change",
            "operands": [
                {"field_id": "price.close.adjusted"},
                {"literal": 20},
            ],
        }
    }
    run_input = _run_input(canonical, definition)
    expected = accepted_kernel_run.artifacts_snapshot()

    exposed = run_input.alpha_expression_snapshot()
    assert isinstance(exposed, dict)
    exposed["operator_id"] = "add"

    assert run(run_input).artifacts_snapshot() == expected


def test_kernel_run_input_rejects_string_alpha_expression(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    assert isinstance(definition, dict)
    strategy = definition["strategy"]
    costs = definition["costs"]
    assert isinstance(strategy, dict)
    assert isinstance(costs, dict)

    with pytest.raises(KernelRunError, match="normalized tree"):
        RunInput(
            canonical_data=accepted_calculation_case["canonical"],
            alpha_expression="pct_change($close_adj, 20)",  # type: ignore[arg-type]
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


def test_kernel_run_requires_an_explicit_research_period(
    accepted_calculation_case: dict[str, object],
) -> None:
    definition = accepted_calculation_case["definition"]
    assert isinstance(definition, dict)

    with pytest.raises(
        KernelRunError,
        match="Research Period requires both first and last Research Sessions",
    ):
        run(
            _run_input(
                accepted_calculation_case["canonical"],
                definition,
                include_period=False,
            )
        )


def _run_input(
    canonical: object,
    definition: dict[str, object],
    *,
    include_period: bool = True,
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
        research_start_session=str(calendar[20]) if include_period else None,
        research_end_session=str(calendar[-1]) if include_period else None,
    )
