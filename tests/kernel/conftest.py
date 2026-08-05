import pytest

from thesistrace.alpha import evaluate_alpha_matrix
from thesistrace.factor import build_forward_labels, evaluate_factor
from thesistrace.fixture import build_fixture
from thesistrace.strategy import run_strategy


@pytest.fixture(scope="session")
def accepted_calculation_case() -> dict[str, object]:
    """Build inputs independently, then expose every accepted calculation seam."""
    _, canonical = build_fixture()
    definition = {
        "alpha": {"expression": "pct_change($close_adj, 20)"},
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
        expression="pct_change($close_adj, 20)",
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
