"""Pure Research Kernel Run contract and calculation seam."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field

from thesistrace.research_kernel.alpha import evaluate_alpha_matrix
from thesistrace.research_kernel.alpha_expression import AlphaExpression
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.strategy import run_strategy

INPUT_SESSION_COUNT = 756


class KernelRunError(ValueError):
    pass


@dataclass(frozen=True, init=False)
class RunInput:
    _canonical_data: dict[str, object] = field(repr=False)
    _alpha_expression: AlphaExpression = field(repr=False)
    _field_bindings: dict[str, str] = field(repr=False)
    universe: str
    neutralization: str
    holdings_count: int
    rebalance_interval: int
    initial_cash_cny: str
    commission_rate_all_in: str
    commission_min_cny: str
    stamp_duty_sell_rate: str
    transfer_fee_rate: str

    def __init__(
        self,
        *,
        canonical_data: dict[str, object],
        alpha_expression: AlphaExpression,
        field_bindings: Mapping[str, str],
        universe: str,
        neutralization: str,
        holdings_count: int,
        rebalance_interval: int,
        initial_cash_cny: str,
        commission_rate_all_in: str,
        commission_min_cny: str,
        stamp_duty_sell_rate: str,
        transfer_fee_rate: str,
    ) -> None:
        object.__setattr__(self, "_canonical_data", copy.deepcopy(canonical_data))
        object.__setattr__(self, "_alpha_expression", copy.deepcopy(alpha_expression))
        object.__setattr__(self, "_field_bindings", copy.deepcopy(dict(field_bindings)))
        object.__setattr__(self, "universe", universe)
        object.__setattr__(self, "neutralization", neutralization)
        object.__setattr__(self, "holdings_count", holdings_count)
        object.__setattr__(self, "rebalance_interval", rebalance_interval)
        object.__setattr__(self, "initial_cash_cny", initial_cash_cny)
        object.__setattr__(self, "commission_rate_all_in", commission_rate_all_in)
        object.__setattr__(self, "commission_min_cny", commission_min_cny)
        object.__setattr__(self, "stamp_duty_sell_rate", stamp_duty_sell_rate)
        object.__setattr__(self, "transfer_fee_rate", transfer_fee_rate)

    def canonical_snapshot(self) -> dict[str, object]:
        return copy.deepcopy(self._canonical_data)

    def alpha_expression_snapshot(self) -> AlphaExpression:
        return copy.deepcopy(self._alpha_expression)

    def field_bindings_snapshot(self) -> dict[str, str]:
        return copy.deepcopy(self._field_bindings)


def run(run_input: RunInput) -> dict[str, dict[str, object]]:
    canonical = run_input.canonical_snapshot()
    alpha_expression = run_input.alpha_expression_snapshot()
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or len(calendar) != INPUT_SESSION_COUNT:
        raise KernelRunError("Kernel Run requires exactly 756 canonical sessions")
    definition = {
        "alpha": {"expression": copy.deepcopy(alpha_expression)},
        "universe": run_input.universe,
        "neutralization": run_input.neutralization,
        "strategy": {
            "holdings_count": run_input.holdings_count,
            "rebalance_interval": run_input.rebalance_interval,
            "initial_cash_cny": run_input.initial_cash_cny,
        },
        "costs": {
            "commission_rate_all_in": run_input.commission_rate_all_in,
            "commission_min_cny": run_input.commission_min_cny,
            "stamp_duty_sell_rate": run_input.stamp_duty_sell_rate,
            "transfer_fee_rate": run_input.transfer_fee_rate,
        },
    }
    matrix = evaluate_alpha_matrix(
        canonical,
        expression=alpha_expression,
        field_bindings=run_input.field_bindings_snapshot(),
        universe_name=run_input.universe,
        neutralization=run_input.neutralization,
    )
    labels = build_forward_labels(canonical, matrix)
    factor = evaluate_factor(labels)
    strategy = run_strategy(canonical, matrix, definition)
    return {
        "alpha_matrix": matrix,
        "forward_labels": labels,
        "factor_evaluation": factor,
        "strategy_backtest": strategy,
        "strategy_time_series": {"daily": strategy["daily"]},
        "strategy_events": {
            "orders": strategy["orders"],
            "child_orders": strategy["child_orders"],
            "fills": strategy["fills"],
            "rebalance_events": strategy["rebalance_events"],
            "rejections": strategy["rejections"],
        },
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
