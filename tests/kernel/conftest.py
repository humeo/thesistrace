import pytest
from contracts import FIELD_BINDINGS, PCT_CHANGE_20

from thesistrace.fixture import build_fixture
from thesistrace.research_kernel import KernelState, RunInput, RunOutput, run
from thesistrace.research_kernel.alpha import evaluate_alpha_matrix
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.strategy import run_strategy


@pytest.fixture(scope="session")
def accepted_calculation_case() -> dict[str, object]:
    """Build inputs independently, then expose every accepted calculation seam."""
    _, canonical = build_fixture()
    definition = {
        "alpha": {"expression": PCT_CHANGE_20},
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
    matrix = evaluate_alpha_matrix(
        canonical,
        expression=PCT_CHANGE_20,
        field_bindings=FIELD_BINDINGS,
        universe_name="top300",
        neutralization="none",
    )
    labels = build_forward_labels(canonical, matrix)
    factor = evaluate_factor(labels)
    strategy = run_strategy(canonical, matrix, definition)
    artifacts = {
        "alpha_matrix": matrix,
        "forward_labels": labels,
        "factor_evaluation": factor,
        "strategy_backtest": strategy,
        "diagnostics": {
            "alpha_coverage": [
                {
                    "session": item["session"],
                    "coverage_loss": item["coverage_loss"],
                }
                for item in matrix["sessions"]
            ],
            "strategy": strategy["diagnostics"],
        },
    }
    return {
        **artifacts,
        "canonical": canonical,
        "definition": definition,
    }


@pytest.fixture(scope="session")
def accepted_kernel_run(
    accepted_calculation_case: dict[str, object],
) -> RunOutput:
    canonical = accepted_calculation_case["canonical"]
    definition = accepted_calculation_case["definition"]
    assert isinstance(canonical, dict)
    assert isinstance(definition, dict)
    alpha = definition["alpha"]
    strategy = definition["strategy"]
    costs = definition["costs"]
    assert isinstance(alpha, dict)
    assert isinstance(strategy, dict)
    assert isinstance(costs, dict)
    return run(
        RunInput(
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
    )


@pytest.fixture(scope="session")
def accepted_kernel_state(accepted_kernel_run: RunOutput) -> KernelState:
    return accepted_kernel_run.track_state
