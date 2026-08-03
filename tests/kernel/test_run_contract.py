import copy
from dataclasses import FrozenInstanceError

import pytest

from thesistrace.research_kernel import RunInput, run

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
) -> None:
    definition = accepted_calculation_case["definition"]
    assert isinstance(definition, dict)
    run_input = _run_input(accepted_calculation_case["canonical"], definition)

    output = run(run_input)

    assert output["alpha_matrix"] == accepted_calculation_case["alpha_matrix"]
    assert output["forward_labels"] == accepted_calculation_case["forward_labels"]
    assert output["factor_evaluation"] == accepted_calculation_case["factor_evaluation"]
    assert output["strategy_backtest"] == accepted_calculation_case["strategy_backtest"]
    assert output["diagnostics"] == accepted_calculation_case["diagnostics"]


def test_kernel_run_input_snapshots_values_and_has_no_product_context(
    accepted_calculation_case: dict[str, object],
) -> None:
    canonical = copy.deepcopy(accepted_calculation_case["canonical"])
    definition = copy.deepcopy(accepted_calculation_case["definition"])
    assert isinstance(canonical, dict)
    assert isinstance(definition, dict)
    run_input = _run_input(canonical, definition)
    expected = run(run_input)

    canonical["research_calendar"] = []
    definition["universe"] = "top3000"

    assert run(run_input) == expected
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

    expression = run_input.alpha_expression_snapshot()
    assert isinstance(expression, str)


def test_kernel_run_input_does_not_expose_mutable_expression_state(
    accepted_calculation_case: dict[str, object],
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
    expected = run(run_input)

    exposed = run_input.alpha_expression_snapshot()
    assert isinstance(exposed, dict)
    exposed["operator_id"] = "add"

    assert run(run_input) == expected


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
