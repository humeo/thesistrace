"""Pure Research Kernel Run contract and calculation seam."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_alpha_matrix,
    validate_alpha,
)
from thesistrace.research_kernel.alpha_expression import AlphaExpression
from thesistrace.research_kernel.canonical_state import slice_canonical_sessions
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.strategy import transition_strategy

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
    research_start_session: str | None
    research_end_session: str | None

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
        research_start_session: str | None = None,
        research_end_session: str | None = None,
    ) -> None:
        if not isinstance(alpha_expression, Mapping):
            raise KernelRunError("Alpha expression must be a normalized tree")
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
        object.__setattr__(self, "research_start_session", research_start_session)
        object.__setattr__(self, "research_end_session", research_end_session)

    def canonical_snapshot(self) -> dict[str, object]:
        value = json.loads(self._canonical_data_json)
        if not isinstance(value, dict):
            raise KernelRunError("canonical data snapshot is invalid")
        return value

    def alpha_expression_snapshot(self) -> AlphaExpression:
        value = json.loads(self._alpha_expression_json)
        if not isinstance(value, Mapping):
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
            research_start_session=self.research_start_session,
            research_end_session=self.research_end_session,
        )


@dataclass(frozen=True, init=False)
class KernelState:
    _run_input: RunInput = field(repr=False)
    _output_json: bytes = field(repr=False)
    _strategy_resume_json: bytes = field(repr=False)
    origin_session: str
    session_count: int
    boundary_session: str

    def __init__(
        self,
        *,
        run_input: RunInput,
        output: dict[str, dict[str, object]],
        strategy_resume: dict[str, object],
        origin_session: str,
    ) -> None:
        calendar = run_input.canonical_snapshot().get("research_calendar")
        if not isinstance(calendar, list) or not calendar:
            raise KernelRunError("Kernel state requires canonical sessions")
        object.__setattr__(self, "_run_input", run_input)
        object.__setattr__(self, "_output_json", canonical_json_bytes(output))
        object.__setattr__(
            self,
            "_strategy_resume_json",
            canonical_json_bytes(strategy_resume),
        )
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

    def strategy_resume_snapshot(self) -> dict[str, object]:
        value = json.loads(self._strategy_resume_json)
        if not isinstance(value, dict):
            raise KernelRunError("Kernel Strategy resume snapshot is invalid")
        return value


@dataclass(frozen=True, init=False)
class RunOutput:
    _artifacts_json: bytes = field(repr=False)
    track_state: KernelState

    def __init__(
        self,
        *,
        artifacts: dict[str, dict[str, object]],
        track_state: KernelState,
    ) -> None:
        object.__setattr__(self, "_artifacts_json", canonical_json_bytes(artifacts))
        object.__setattr__(self, "track_state", track_state)

    def artifacts_snapshot(self) -> dict[str, dict[str, object]]:
        value = json.loads(self._artifacts_json)
        if not isinstance(value, dict):
            raise KernelRunError("Kernel Run artifacts snapshot is invalid")
        return value


def run(run_input: RunInput) -> RunOutput:
    canonical = run_input.canonical_snapshot()
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list) or not calendar:
        raise KernelRunError("Kernel Run requires canonical Research Sessions")
    if run_input.research_start_session is None and run_input.research_end_session is None:
        return _run_legacy_window(run_input, canonical, calendar)
    if run_input.research_start_session is None or run_input.research_end_session is None:
        raise KernelRunError("Research Period requires both first and last Research Sessions")
    return _run_explicit_period(run_input, canonical, [str(session) for session in calendar])


def _run_legacy_window(
    run_input: RunInput,
    canonical: dict[str, object],
    calendar: list[object],
) -> RunOutput:
    if len(calendar) != INPUT_SESSION_COUNT:
        raise KernelRunError("Kernel Run requires exactly 756 canonical sessions")
    origin_session = str(calendar[-504])
    return _calculate(run_input, canonical, origin_session=origin_session)


def _run_explicit_period(
    run_input: RunInput,
    canonical: dict[str, object],
    calendar: list[str],
) -> RunOutput:
    start_session = str(run_input.research_start_session)
    end_session = str(run_input.research_end_session)
    try:
        start_index = calendar.index(start_session)
        end_index = calendar.index(end_session)
    except ValueError as error:
        raise KernelRunError(
            "Research Period boundary is not a canonical Research Session"
        ) from error
    if start_index > end_index:
        raise KernelRunError("Research Period first session is after its last session")

    alpha_expression = run_input.alpha_expression_snapshot()
    parsed = validate_alpha(
        alpha_expression,
        field_bindings=run_input.field_bindings_snapshot(),
    )
    warmup_start = start_index - parsed.effective_lookback
    if warmup_start < 0:
        raise KernelRunError(
            "insufficient Calculation Warm-up: "
            f"requires {parsed.effective_lookback} sessions before {start_session}"
        )
    period_sessions = calendar[start_index : end_index + 1]
    calculation_sessions = calendar[warmup_start : end_index + 1]
    calculation_canonical = slice_canonical_sessions(canonical, calculation_sessions)
    calculation_input = run_input.with_canonical_data(calculation_canonical)
    return _calculate(
        calculation_input,
        calculation_canonical,
        origin_session=start_session,
        period_sessions=period_sessions,
    )


def _calculate(
    run_input: RunInput,
    canonical: dict[str, object],
    *,
    origin_session: str,
    period_sessions: list[str] | None = None,
) -> RunOutput:
    alpha_expression = run_input.alpha_expression_snapshot()
    definition = calculation_definition(run_input, alpha_expression)
    matrix = evaluate_alpha_matrix(
        canonical,
        expression=alpha_expression,
        field_bindings=run_input.field_bindings_snapshot(),
        universe_name=run_input.universe,
        neutralization=run_input.neutralization,
    )
    if period_sessions is not None:
        selected = set(period_sessions)
        matrix["sessions"] = [
            session for session in matrix["sessions"] if str(session["session"]) in selected
        ]
        matrix["checksum"] = alpha_matrix_checksum(matrix["sessions"])
    labels = build_forward_labels(canonical, matrix, signal_sessions=period_sessions)
    factor = evaluate_factor(labels)
    strategy = transition_strategy(
        canonical,
        matrix,
        definition,
        origin_session=origin_session,
    )
    artifacts = compose_output(matrix, labels, factor, strategy.finalized)
    track_state = KernelState(
        run_input=run_input,
        output=artifacts,
        strategy_resume=strategy.resumable,
        origin_session=origin_session,
    )
    return RunOutput(
        artifacts=artifacts,
        track_state=track_state,
    )


def calculation_definition(
    run_input: RunInput,
    alpha_expression: AlphaExpression | None = None,
) -> dict[str, object]:
    return {
        "alpha": {
            "expression": (
                run_input.alpha_expression_snapshot()
                if alpha_expression is None
                else alpha_expression
            )
        },
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


def compose_output(
    matrix: dict[str, object],
    labels: dict[str, object],
    factor: dict[str, object],
    strategy: dict[str, object],
) -> dict[str, dict[str, object]]:
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
