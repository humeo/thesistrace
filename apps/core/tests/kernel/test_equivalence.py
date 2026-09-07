from decimal import Decimal

import pytest

from thesistrace.research_kernel.equivalence import first_divergence
from thesistrace.research_kernel.numeric import NumericContractError


def test_first_divergence_preserves_canonical_scalar_semantics() -> None:
    assert first_divergence(-0.0, 0.0) == ""
    assert first_divergence(Decimal("1.00"), Decimal("1")) == ""
    assert first_divergence(1.0, 1.5) == "$"
    assert first_divergence(Decimal("1"), Decimal("2")) == "$"
    assert first_divergence(1, True) == "$"
    expected = {
        "output": {
            "strategy_backtest": {
                "daily": [
                    {"net_nav": "1"},
                    {"net_nav": "2"},
                ]
            }
        }
    }
    actual = {
        "output": {
            "strategy_backtest": {
                "daily": [
                    {"net_nav": "semantic-mismatch"},
                    {"net_nav": "2"},
                ]
            }
        }
    }
    assert first_divergence(actual, expected) == (
        "$.output.strategy_backtest.daily[0].net_nav"
    )
    with pytest.raises(NumericContractError):
        first_divergence(float("nan"), float("nan"))
