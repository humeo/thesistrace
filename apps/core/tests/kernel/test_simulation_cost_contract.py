import pytest
from pydantic import ValidationError

from thesistrace.research_definition import StrategyBacktestSpec

DEFAULT_COSTS = {
    "commission_rate_all_in": "0.0003",
    "commission_min_cny": "5",
    "stamp_duty_sell_rate": "0.0005",
    "transfer_fee_rate": "0.00001",
    "slippage_bps": "0",
}


def spec(**changes):
    return StrategyBacktestSpec.model_validate({
        "research_kind": "strategy_backtest", "start_date": "2026-08-03",
        "end_date": "2026-08-11", "universe": "top300", "formula": "1",
        "neutralization": "none", "initial_cash_cny": "100000",
        "holdings_count": 1, "selection_every_sessions": 1, **changes,
    })


def test_authoring_defaults_are_explicit_and_custom_costs_are_frozen():
    assert spec().model_dump()["costs"] == DEFAULT_COSTS
    supplied = {**DEFAULT_COSTS, "commission_min_cny": "1", "slippage_bps": "10"}
    accepted = spec(costs=supplied)
    supplied["slippage_bps"] = "999"
    assert accepted.model_dump()["costs"]["slippage_bps"] == "10"
    with pytest.raises(ValidationError):
        accepted.costs.slippage_bps = "20"


@pytest.mark.parametrize("field", list(DEFAULT_COSTS))
@pytest.mark.parametrize("invalid", ["-0.01", "NaN", "Infinity", "-Infinity", "abc", 0.01, True])
def test_costs_reject_nonfinite_negative_and_non_decimal_string_values(field, invalid):
    with pytest.raises(ValidationError):
        spec(costs={**DEFAULT_COSTS, field: invalid})


@pytest.mark.parametrize("value", ["10000", "10000.01", "100000"])
def test_slippage_must_leave_a_strictly_positive_sell_price(value):
    with pytest.raises(ValidationError):
        spec(costs={**DEFAULT_COSTS, "slippage_bps": value})


def test_supplied_cost_object_must_be_complete_and_current():
    with pytest.raises(ValidationError):
        spec(costs={"slippage_bps": "10"})
    with pytest.raises(ValidationError):
        spec(costs={**DEFAULT_COSTS, "unknown_fee": "0"})
    assert spec(costs={name: "0" for name in DEFAULT_COSTS}).costs.slippage_bps == "0"


def test_discovery_exposes_the_same_defaults_and_child_order_cost_semantics():
    from thesistrace.research_authoring.service import CURRENT_RESEARCH_AUTHORING_CONSTRAINTS

    constraints = CURRENT_RESEARCH_AUTHORING_CONSTRAINTS.model_dump()
    assert constraints["simulation_cost_defaults"] == DEFAULT_COSTS
    assert "child order" in constraints["simulation_cost_rules"]
    assert "not a second fee" in constraints["simulation_cost_rules"]
