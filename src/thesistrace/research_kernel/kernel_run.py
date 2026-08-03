"""Pure Research Kernel Run contract and calculation seam."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from thesistrace.research_kernel.alpha import evaluate_alpha_matrix
from thesistrace.research_kernel.alpha_expression import AlphaExpression
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import run_strategy

INPUT_SESSION_COUNT = 756


class KernelRunError(ValueError):
    pass


@dataclass(frozen=True, init=False)
class RunInput:
    _canonical_data_json: bytes = field(repr=False)
    _alpha_expression_json: bytes = field(repr=False)
    _field_bindings: tuple[tuple[str, str], ...] = field(repr=False)
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
        object.__setattr__(self, "_canonical_data_json", canonical_json_bytes(canonical_data))
        object.__setattr__(
            self,
            "_alpha_expression_json",
            canonical_json_bytes(alpha_expression),
        )
        object.__setattr__(
            self,
            "_field_bindings",
            tuple(sorted((str(key), str(value)) for key, value in field_bindings.items())),
        )
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
        value = json.loads(self._canonical_data_json)
        if not isinstance(value, dict):
            raise KernelRunError("canonical data snapshot is invalid")
        return value

    def alpha_expression_snapshot(self) -> AlphaExpression:
        value = json.loads(self._alpha_expression_json)
        if not isinstance(value, (str, Mapping)):
            raise KernelRunError("Alpha expression snapshot is invalid")
        return value

    def field_bindings_snapshot(self) -> dict[str, str]:
        return dict(self._field_bindings)

    def with_canonical_data(self, canonical_data: dict[str, object]) -> RunInput:
        return RunInput(
            canonical_data=canonical_data,
            alpha_expression=self.alpha_expression_snapshot(),
            field_bindings=self.field_bindings_snapshot(),
            universe=self.universe,
            neutralization=self.neutralization,
            holdings_count=self.holdings_count,
            rebalance_interval=self.rebalance_interval,
            initial_cash_cny=self.initial_cash_cny,
            commission_rate_all_in=self.commission_rate_all_in,
            commission_min_cny=self.commission_min_cny,
            stamp_duty_sell_rate=self.stamp_duty_sell_rate,
            transfer_fee_rate=self.transfer_fee_rate,
        )


@dataclass(frozen=True, init=False)
class KernelState:
    _run_input: RunInput = field(repr=False)
    _output_json: bytes = field(repr=False)
    origin_session: str
    session_count: int
    boundary_session: str

    def __init__(
        self,
        *,
        run_input: RunInput,
        output: dict[str, dict[str, object]],
        origin_session: str,
    ) -> None:
        calendar = run_input.canonical_snapshot().get("research_calendar")
        if not isinstance(calendar, list) or not calendar:
            raise KernelRunError("Kernel state requires canonical sessions")
        object.__setattr__(self, "_run_input", run_input)
        object.__setattr__(self, "_output_json", canonical_json_bytes(output))
        object.__setattr__(self, "origin_session", origin_session)
        object.__setattr__(self, "session_count", len(calendar))
        object.__setattr__(self, "boundary_session", str(calendar[-1]))

    def canonical_snapshot(self) -> dict[str, object]:
        return self._run_input.canonical_snapshot()

    def output_snapshot(self) -> dict[str, dict[str, object]]:
        value = json.loads(self._output_json)
        if not isinstance(value, dict):
            raise KernelRunError("Kernel output snapshot is invalid")
        return value

    def run_input_with_canonical(self, canonical_data: dict[str, object]) -> RunInput:
        return self._run_input.with_canonical_data(canonical_data)


def run(run_input: RunInput) -> dict[str, dict[str, object]]:
    canonical = run_input.canonical_snapshot()
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or len(calendar) != INPUT_SESSION_COUNT:
        raise KernelRunError("Kernel Run requires exactly 756 canonical sessions")
    return initial_state(run_input).output_snapshot()


def initial_state(
    run_input: RunInput,
    *,
    origin_session: str | None = None,
) -> KernelState:
    canonical = run_input.canonical_snapshot()
    alpha_expression = run_input.alpha_expression_snapshot()
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or len(calendar) < INPUT_SESSION_COUNT:
        raise KernelRunError("Kernel state requires at least 756 canonical sessions")
    selected_origin = str(calendar[-504]) if origin_session is None else str(origin_session)
    if selected_origin not in calendar:
        raise KernelRunError("Kernel state origin is outside canonical sessions")
    definition = {
        "alpha": {"expression": alpha_expression},
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
    strategy = run_strategy(
        canonical,
        matrix,
        definition,
        origin_session=selected_origin,
    )
    output = {
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
    return KernelState(
        run_input=run_input,
        output=output,
        origin_session=selected_origin,
    )
