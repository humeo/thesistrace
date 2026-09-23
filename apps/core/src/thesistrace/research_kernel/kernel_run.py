"""Pure Research Kernel Run contract and calculation seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from thesistrace.research_kernel.alpha import (
    alpha_matrix_checksum,
    evaluate_alpha_matrix,
    evaluate_columnar_alpha_matrix,
)
from thesistrace.research_kernel.alpha_expression import (
    AlphaExpression,
    validate_normalized_alpha,
)
from thesistrace.research_kernel.builtin_framework import BUILTIN_FRAMEWORK_MODULES
from thesistrace.research_kernel.common_observations import (
    attach_common_input_evidence,
    merge_common_input_sessions,
    record_common_input,
)
from thesistrace.research_kernel.direct_strategy import PythonProgram
from thesistrace.research_kernel.exposure import validate_exposure
from thesistrace.research_kernel.factor import build_forward_labels, evaluate_factor
from thesistrace.research_kernel.framework_strategy import FrameworkModules
from thesistrace.research_kernel.portfolio_weighting import PortfolioWeighting
from thesistrace.research_kernel.serialization import canonical_json_bytes
from thesistrace.research_kernel.series_plan import (
    ExecutableAlpha,
    SeriesExecutionPlan,
    build_series_execution_plan,
)
from thesistrace.research_kernel.strategy import (
    transition_columnar_strategy,
    transition_strategy,
)
from thesistrace.research_kernel.terminal_state_schema import (
    DECISION_STATE_ADAPTER,
    DirectDecisionState,
    FrameworkDecisionState,
    FrameworkModulesDecisionState,
)
from thesistrace.research_series import (
    AlignedResearchData,
    ColumnarResearchSeries,
    slice_research_sessions,
)


class KernelRunError(ValueError):
    pass


class InsufficientCalculationWarmupError(KernelRunError):
    pass


@dataclass(frozen=True)
class StrategyRunInput:
    holdings_count: int | None
    selection_interval: int | None
    initial_cash_cny: str
    commission_rate_all_in: str
    commission_min_cny: str
    stamp_duty_sell_rate: str
    transfer_fee_rate: str
    slippage_bps: str
    weighting: PortfolioWeighting | None = None
    volatility_window: int | None = None
    exposure_expression_json: bytes | None = None
    modules_json: bytes | None = field(default=None, repr=False)
    environment_json: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        programs = self.modules_snapshot().programs()
        if programs:
            if (self.environment_json is None
                    or not isinstance(json.loads(self.environment_json), dict)):
                raise ValueError("Framework programs require a frozen execution environment")
        elif self.environment_json is not None:
            raise ValueError("Builtin Framework has no Python execution environment")
        if "portfolio_construction" in programs:
            if any(value is not None for value in (
                self.holdings_count, self.selection_interval, self.weighting,
                self.volatility_window, self.exposure_expression_json,
            )):
                raise ValueError("Python Portfolio cannot contain builtin Portfolio settings")
            return
        if (type(self.holdings_count) is not int or not 1 <= self.holdings_count <= 100
                or type(self.selection_interval) is not int
                or not 1 <= self.selection_interval <= 20):
            raise ValueError("Invalid builtin Portfolio breadth or interval")
        for name, default in (
            ("weighting", "equal_weight"), ("volatility_window", 20),
            ("exposure_expression_json", b'{"kind":"number","value":1}'),
        ):
            if getattr(self, name) is None:
                object.__setattr__(self, name, default)
        if type(self.volatility_window) is not int or not 1 <= self.volatility_window <= 252:
            raise ValueError("Invalid volatility window")
        validate_exposure(self.exposure_expression_snapshot())
        if self.weighting not in {"equal_weight", "rank_weight", "inverse_volatility"}:
            raise ValueError("Unsupported portfolio weighting")

    def exposure_expression_snapshot(self) -> dict[str, object] | None:
        if self.exposure_expression_json is None:
            return None
        value = json.loads(self.exposure_expression_json)
        if not isinstance(value, dict):
            raise ValueError("Exposure expression must be a normalized tree")
        return value

    def modules_snapshot(self) -> FrameworkModules:
        return (FrameworkModules.model_validate_json(self.modules_json)
                if self.modules_json is not None else
                FrameworkModules.model_validate(dict(BUILTIN_FRAMEWORK_MODULES)))

    def contract_snapshot(self) -> dict[str, object]:
        snapshot = {
            "mode": "framework",
            "modules": self.modules_snapshot().model_dump(mode="json"),
            "initial_cash_cny": self.initial_cash_cny,
            "commission_rate_all_in": self.commission_rate_all_in,
            "commission_min_cny": self.commission_min_cny,
            "stamp_duty_sell_rate": self.stamp_duty_sell_rate,
            "transfer_fee_rate": self.transfer_fee_rate,
            "slippage_bps": self.slippage_bps,
        }
        if "portfolio_construction" not in self.modules_snapshot().programs():
            snapshot.update({
                "holdings_count": self.holdings_count,
                "selection_interval": self.selection_interval,
                "weighting": self.weighting, "volatility_window": self.volatility_window,
                "exposure_expression": self.exposure_expression_snapshot(),
            })
        if self.environment_json is not None:
            snapshot["environment"] = json.loads(self.environment_json)
        return snapshot


@dataclass(frozen=True)
class DirectStrategyRunInput:
    program_json: bytes = field(repr=False)
    environment_json: bytes = field(repr=False)
    initial_cash_cny: str
    commission_rate_all_in: str
    commission_min_cny: str
    stamp_duty_sell_rate: str
    transfer_fee_rate: str
    slippage_bps: str

    def __post_init__(self) -> None:
        self.program_snapshot()
        if not isinstance(json.loads(self.environment_json), dict):
            raise ValueError("Python execution environment must be a frozen object")

    def program_snapshot(self) -> PythonProgram:
        return PythonProgram.model_validate_json(self.program_json)

    def contract_snapshot(self) -> dict[str, object]:
        return {
            "mode": "direct", "program": self.program_snapshot().model_dump(mode="json"),
            "environment": json.loads(self.environment_json),
            "initial_cash_cny": self.initial_cash_cny,
            "commission_rate_all_in": self.commission_rate_all_in,
            "commission_min_cny": self.commission_min_cny,
            "stamp_duty_sell_rate": self.stamp_duty_sell_rate,
            "transfer_fee_rate": self.transfer_fee_rate,
            "slippage_bps": self.slippage_bps,
        }


def strategy_input_from_snapshot(
    value: Mapping[str, object],
) -> StrategyRunInput | DirectStrategyRunInput:
    """Restore exactly one current strategy definition, without authoring defaults."""
    cost_names = {
        "initial_cash_cny", "commission_rate_all_in", "commission_min_cny",
        "stamp_duty_sell_rate", "transfer_fee_rate", "slippage_bps",
    }
    costs = {name: value[name] for name in cost_names}
    if value.get("mode") == "direct":
        if set(value) != cost_names | {"mode", "program", "environment"}:
            raise KernelRunError("Direct Strategy snapshot fields are invalid")
        return DirectStrategyRunInput(
            program_json=canonical_json_bytes(value["program"]),
            environment_json=canonical_json_bytes(value["environment"]), **costs,
        )
    programs = FrameworkModules.model_validate(value.get("modules")).programs()
    builtin_portfolio = "portfolio_construction" not in programs
    settings = ({"holdings_count", "selection_interval", "weighting", "volatility_window",
                 "exposure_expression"} if builtin_portfolio else set())
    expected = cost_names | settings | {"mode", "modules"}
    if programs:
        expected.add("environment")
    if value.get("mode") != "framework" or set(value) != expected:
        raise KernelRunError("Framework Strategy snapshot fields are invalid")
    return StrategyRunInput(
        holdings_count=value.get("holdings_count"),
        selection_interval=value.get("selection_interval"),
        weighting=value.get("weighting"), volatility_window=value.get("volatility_window"), **costs,
        exposure_expression_json=(canonical_json_bytes(value["exposure_expression"])
                                  if builtin_portfolio else None),
        modules_json=canonical_json_bytes(value["modules"]),
        environment_json=canonical_json_bytes(value["environment"]) if programs else None,
    )


@dataclass(frozen=True, init=False)
class RunInput:
    _research_data: AlignedResearchData | ColumnarResearchSeries = field(repr=False)
    _alpha_expression_json: bytes | None = field(repr=False)
    _field_bindings: tuple[tuple[str, str], ...] = field(repr=False)
    _effective_lookback: int = field(repr=False)
    universe: str
    neutralization: str | None
    research_kind: Literal["factor_evaluation", "strategy_backtest"]
    strategy: StrategyRunInput | DirectStrategyRunInput | None
    research_start_session: str | None
    research_end_session: str | None

    def __init__(
        self,
        *,
        research_data: AlignedResearchData | ColumnarResearchSeries,
        alpha_expression: AlphaExpression | None,
        field_bindings: Mapping[str, str],
        effective_lookback: int,
        universe: str,
        neutralization: str | None,
        research_kind: Literal["factor_evaluation", "strategy_backtest"],
        strategy: StrategyRunInput | DirectStrategyRunInput | None,
        research_start_session: str | None = None,
        research_end_session: str | None = None,
    ) -> None:
        direct = isinstance(strategy, DirectStrategyRunInput)
        custom_signal = (isinstance(strategy, StrategyRunInput)
                         and "alpha" in strategy.modules_snapshot().programs())
        if (direct or custom_signal) and (
            alpha_expression is not None or neutralization is not None
        ):
            raise KernelRunError(
                "Python Signal or Direct Strategy cannot contain an Alpha Formula or neutralization"
            )
        if not (direct or custom_signal) and not isinstance(alpha_expression, Mapping):
            raise KernelRunError("Alpha expression must be a normalized tree")
        if effective_lookback < 0 or effective_lookback > 252:
            raise KernelRunError("Effective calculation lookback is invalid")
        if research_kind == "factor_evaluation" and strategy is not None:
            raise KernelRunError("Factor Evaluation cannot contain Strategy input")
        if research_kind == "strategy_backtest" and strategy is None:
            raise KernelRunError("Strategy Backtest requires Strategy input")
        object.__setattr__(self, "_research_data", research_data.snapshot())
        object.__setattr__(
            self,
            "_alpha_expression_json",
            canonical_json_bytes(alpha_expression) if alpha_expression is not None else None,
        )
        object.__setattr__(
            self,
            "_field_bindings",
            tuple(sorted((str(key), str(value)) for key, value in field_bindings.items())),
        )
        object.__setattr__(self, "_effective_lookback", effective_lookback)
        object.__setattr__(self, "strategy", strategy)
        if direct:
            requirements = strategy.program_snapshot().data_requirements
            required_fields = set(requirements.field_ids)
            if effective_lookback != requirements.history_sessions - 1:
                raise KernelRunError("Python program history and calculation lookback disagree")
        else:
            required_fields = (set(self.alpha_execution_plan().field_names)
                               if self.has_alpha else set())
        if isinstance(strategy, StrategyRunInput):
            for program in strategy.modules_snapshot().programs().values():
                required_fields.update(program.data_requirements.field_ids)
                if effective_lookback < program.data_requirements.history_sessions - 1:
                    raise KernelRunError("Insufficient Framework program history")
            if "portfolio_construction" not in strategy.modules_snapshot().programs():
                required_fields.update(
                    validate_exposure(strategy.exposure_expression_snapshot()).field_ids,
                )
        if (isinstance(strategy, StrategyRunInput) and strategy.weighting == "inverse_volatility"
                and "portfolio_construction" not in strategy.modules_snapshot().programs()):
            required_fields.add("price.close.adjusted")
            if effective_lookback < strategy.volatility_window:
                raise KernelRunError("Insufficient volatility calculation lookback")
        if not required_fields <= set(field_bindings):
            raise KernelRunError("Research expressions and field bindings disagree")
        object.__setattr__(self, "universe", universe)
        object.__setattr__(self, "neutralization", neutralization)
        object.__setattr__(self, "research_kind", research_kind)
        object.__setattr__(self, "research_start_session", research_start_session)
        object.__setattr__(self, "research_end_session", research_end_session)

    def research_data_snapshot(self) -> AlignedResearchData | ColumnarResearchSeries:
        return self._research_data.snapshot()

    def alpha_expression_snapshot(self) -> AlphaExpression | None:
        if self._alpha_expression_json is None:
            return None
        value = json.loads(self._alpha_expression_json)
        if not isinstance(value, Mapping):
            raise KernelRunError("Alpha expression snapshot is invalid")
        return value

    @property
    def has_alpha(self) -> bool:
        return self._alpha_expression_json is not None

    def field_bindings_snapshot(self) -> dict[str, str]:
        return dict(self._field_bindings)

    def validate_strategy_continuation(self, state: Mapping[str, object]) -> None:
        """Bind resumable decisions to the frozen implementation before restoring it."""
        decision = DECISION_STATE_ADAPTER.validate_python(state["decision_state"])
        checksum = hashlib.sha256(canonical_json_bytes(calculation_definition(self))).hexdigest()
        if state["contract_checksum"] != checksum:
            raise KernelRunError("Strategy continuation differs from the frozen contract")
        if isinstance(self.strategy, DirectStrategyRunInput):
            if (not isinstance(decision, DirectDecisionState)
                    or decision.program_sha256 != self.strategy.program_snapshot().source_sha256):
                raise KernelRunError("Direct continuation differs from the frozen program")
            return
        if not isinstance(self.strategy, StrategyRunInput):
            raise KernelRunError("Strategy continuation requires Strategy input")
        modules = self.strategy.modules_snapshot()
        programs = modules.programs()
        expected_type = (
            FrameworkDecisionState if modules.model_dump(mode="json") == BUILTIN_FRAMEWORK_MODULES
            else FrameworkModulesDecisionState
        )
        interval = (
            None if "portfolio_construction" in programs else self.strategy.selection_interval
        )
        if not isinstance(decision, expected_type) or decision.selection_interval != interval:
            raise KernelRunError("Framework continuation differs from the frozen modules")

    def compiled_alpha_snapshot(self) -> ExecutableAlpha:
        if not self.has_alpha:
            raise KernelRunError("Strategy has no Alpha computation")
        parsed = validate_normalized_alpha(
            self.alpha_expression_snapshot(), field_bindings=self.field_bindings_snapshot(),
        )
        return ExecutableAlpha(
            expression=parsed.expression,
            field_ids_by_identifier=parsed.field_ids_by_identifier,
            effective_lookback=parsed.effective_lookback,
        )

    @property
    def effective_lookback(self) -> int:
        return self._effective_lookback

    def alpha_execution_plan(self) -> SeriesExecutionPlan:
        return build_series_execution_plan(self.compiled_alpha_snapshot())

    def alpha_factor_contract_snapshot(self) -> dict[str, object]:
        """Return the Run-owned inputs that define Alpha-and-Factor computation."""
        if self.research_start_session is None or self.research_end_session is None:
            raise KernelRunError("Alpha-and-Factor Research Period is incomplete")
        if not self.has_alpha:
            return {
                "research_kind": self.research_kind, "alpha": None,
                "research_period": {
                    "first_session": self.research_start_session,
                    "last_session": self.research_end_session,
                },
                "universe": self.universe, "neutralization": None,
            }
        plan = self.alpha_execution_plan()
        return {
            "research_kind": self.research_kind,
            "alpha": {
                "expression": self.alpha_expression_snapshot(),
                "field_bindings": {
                    field_id: identifier for identifier, field_id
                    in self.compiled_alpha_snapshot().field_ids_by_identifier.items()
                },
                "execution_plan": {
                    "nodes": [
                        {
                            "kind": node.kind,
                            "identifier": node.identifier,
                            "inputs": list(node.inputs),
                            "value": node.value,
                        }
                        for node in plan.nodes
                    ],
                    "root": plan.root,
                    "field_names": list(plan.field_names),
                    "effective_lookback": plan.effective_lookback,
                },
            },
            "research_period": {
                "first_session": self.research_start_session,
                "last_session": self.research_end_session,
            },
            "universe": self.universe,
            "neutralization": self.neutralization,
        }

    def strategy_contract_snapshot(self) -> dict[str, object]:
        if self.research_kind != "strategy_backtest" or self.strategy is None:
            raise KernelRunError("Strategy Backtest input is incomplete")
        return self.strategy.contract_snapshot()

    def with_research_data(
        self,
        research_data: AlignedResearchData | ColumnarResearchSeries,
        *,
        research_end_session: str | None = None,
    ) -> RunInput:
        return RunInput(
            research_data=research_data,
            alpha_expression=self.alpha_expression_snapshot(),
            field_bindings=self.field_bindings_snapshot(),
            effective_lookback=self._effective_lookback,
            universe=self.universe,
            neutralization=self.neutralization,
            research_kind=self.research_kind,
            strategy=self.strategy,
            research_start_session=self.research_start_session,
            research_end_session=(
                self.research_end_session if research_end_session is None else research_end_session
            ),
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
        calendar = run_input.research_data_snapshot().sessions
        if not calendar:
            raise KernelRunError("Kernel state requires aligned Research Sessions")
        if run_input.strategy is not None:
            run_input.validate_strategy_continuation(strategy_resume)
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

    def research_data_snapshot(self) -> AlignedResearchData:
        return self._run_input.research_data_snapshot()

    def output_snapshot(self) -> dict[str, dict[str, object]]:
        value = json.loads(self._output_json)
        if not isinstance(value, dict):
            raise KernelRunError("Kernel output snapshot is invalid")
        return value

    def run_input_with_research_data(
        self,
        research_data: AlignedResearchData,
        *,
        research_end_session: str | None = None,
    ) -> RunInput:
        return self._run_input.with_research_data(
            research_data,
            research_end_session=research_end_session,
        )

    def strategy_resume_snapshot(self) -> dict[str, object]:
        value = json.loads(self._strategy_resume_json)
        if not isinstance(value, dict):
            raise KernelRunError("Kernel Strategy resume snapshot is invalid")
        return value


@dataclass(frozen=True, init=False)
class RunOutput:
    _artifacts_json: bytes = field(repr=False)
    _strategy_ledger_json: bytes = field(repr=False)
    track_state: KernelState

    def __init__(
        self,
        *,
        artifacts: dict[str, dict[str, object]],
        strategy_ledger: tuple[dict[str, object], ...],
        track_state: KernelState,
    ) -> None:
        object.__setattr__(self, "_artifacts_json", canonical_json_bytes(artifacts))
        object.__setattr__(
            self,
            "_strategy_ledger_json",
            canonical_json_bytes(strategy_ledger),
        )
        object.__setattr__(self, "track_state", track_state)

    def artifacts_snapshot(self) -> dict[str, dict[str, object]]:
        value = json.loads(self._artifacts_json)
        if not isinstance(value, dict):
            raise KernelRunError("Kernel Run artifacts snapshot is invalid")
        return value

    def strategy_ledger_snapshot(self) -> list[dict[str, object]]:
        value = json.loads(self._strategy_ledger_json)
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise KernelRunError("Kernel Strategy Ledger snapshot is invalid")
        return value


def run(run_input: RunInput) -> RunOutput:
    research_data = run_input.research_data_snapshot()
    if not isinstance(research_data, AlignedResearchData):
        raise KernelRunError("Kernel Run requires row-aligned Research Data")
    calendar = list(research_data.sessions)
    if not calendar:
        raise KernelRunError("Kernel Run requires aligned Research Sessions")
    if run_input.research_start_session is None or run_input.research_end_session is None:
        raise KernelRunError("Research Period requires both first and last Research Sessions")
    return _run_explicit_period(run_input, research_data, calendar)


def run_columnar_chunk(
    run_input: RunInput,
    *,
    cancellation_check: Callable[[], None],
) -> RunOutput:
    cancellation_check()
    research_data = run_input.research_data_snapshot()
    if not isinstance(research_data, ColumnarResearchSeries):
        raise KernelRunError("Research Chunk requires columnar input")
    calendar = list(research_data.sessions)
    if not calendar:
        raise KernelRunError("Research Chunk requires aligned Research Sessions")
    if run_input.research_start_session is None or run_input.research_end_session is None:
        raise KernelRunError("Research Period requires both first and last Research Sessions")
    start_session, period_sessions, calculation_sessions = _period_boundaries(
        run_input,
        calendar,
    )
    calculation_data = research_data.slice_sessions(tuple(calculation_sessions))
    calculation_input = run_input.with_research_data(calculation_data)
    return _calculate_columnar(
        calculation_input,
        calculation_data,
        origin_session=start_session,
        period_sessions=period_sessions,
        cancellation_check=cancellation_check,
    )


def _run_explicit_period(
    run_input: RunInput,
    research_data: AlignedResearchData,
    calendar: list[str],
) -> RunOutput:
    start_session, period_sessions, calculation_sessions = _period_boundaries(
        run_input,
        calendar,
    )
    calculation_data = slice_research_sessions(research_data, calculation_sessions)
    calculation_input = run_input.with_research_data(calculation_data)
    return _calculate(
        calculation_input,
        calculation_data,
        origin_session=start_session,
        period_sessions=period_sessions,
    )


def _period_boundaries(
    run_input: RunInput,
    calendar: list[str],
) -> tuple[str, list[str], list[str]]:
    start_session = str(run_input.research_start_session)
    end_session = str(run_input.research_end_session)
    try:
        start_index = calendar.index(start_session)
        end_index = calendar.index(end_session)
    except ValueError as error:
        raise KernelRunError(
            "Research Period boundary is not a Research Session"
        ) from error
    if start_index > end_index:
        raise KernelRunError("Research Period first session is after its last session")

    warmup_start = start_index - run_input.effective_lookback
    if warmup_start < 0:
        raise InsufficientCalculationWarmupError(
            "insufficient Calculation Warm-up: "
            "requires "
            f"{run_input.effective_lookback} sessions before "
            f"{start_session}"
        )
    period_sessions = calendar[start_index : end_index + 1]
    calculation_sessions = calendar[warmup_start : end_index + 1]
    return start_session, period_sessions, calculation_sessions


def _calculate(
    run_input: RunInput,
    research_data: AlignedResearchData,
    *,
    origin_session: str,
    period_sessions: list[str],
) -> RunOutput:
    matrix = None if not run_input.has_alpha else evaluate_alpha_matrix(
        research_data,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
    )
    return _calculate_from_matrix(
        run_input,
        research_data,
        matrix,
        origin_session=origin_session,
        period_sessions=period_sessions,
    )


def _calculate_columnar(
    run_input: RunInput,
    research_data: ColumnarResearchSeries,
    *,
    origin_session: str,
    period_sessions: list[str],
    cancellation_check: Callable[[], None],
) -> RunOutput:
    matrix = None if not run_input.has_alpha else evaluate_columnar_alpha_matrix(
        research_data,
        compiled_alpha=run_input.compiled_alpha_snapshot(),
        neutralization=run_input.neutralization,
        cancellation_check=cancellation_check,
    )
    return _calculate_from_matrix(
        run_input,
        research_data,
        matrix,
        origin_session=origin_session,
        period_sessions=period_sessions,
        cancellation_check=cancellation_check,
    )


def _calculate_from_matrix(
    run_input: RunInput,
    research_data: AlignedResearchData | ColumnarResearchSeries,
    matrix: dict[str, object] | None,
    *,
    origin_session: str,
    period_sessions: list[str],
    cancellation_check: Callable[[], None] | None = None,
) -> RunOutput:
    if cancellation_check is not None:
        cancellation_check()
    selected = set(period_sessions)
    if matrix is not None:
        matrix["sessions"] = [
            session for session in matrix["sessions"] if str(session["session"]) in selected
        ]
        matrix["checksum"] = alpha_matrix_checksum(matrix["sessions"])
    if run_input.research_kind == "factor_evaluation":
        labels = build_forward_labels(
            research_data,
            matrix,
            signal_sessions=period_sessions,
            cancellation_check=cancellation_check,
        )
        if cancellation_check is not None:
            cancellation_check()
        artifacts = {
            "alpha_matrix": matrix,
            "forward_labels": labels,
            "factor_evaluation": evaluate_factor(labels),
        }
        if cancellation_check is not None:
            cancellation_check()
        return RunOutput(
            artifacts=artifacts,
            strategy_ledger=(),
            track_state=KernelState(
                run_input=run_input,
                output=artifacts,
                strategy_resume={},
                origin_session=origin_session,
            ),
        )
    definition = calculation_definition(run_input)
    exposure_observations = {}
    def observe_common(identifier, code, values):
        record_common_input(
            exposure_observations, tuple(research_data.sessions), identifier, code, values,
        )
    strategy = (
        transition_strategy(
            research_data,
            matrix,
            definition,
            origin_session=origin_session,
            observe_common=observe_common,
        )
        if isinstance(research_data, AlignedResearchData)
        else transition_columnar_strategy(
            research_data,
            matrix,
            definition,
            origin_session=origin_session,
            observe_common=observe_common,
            cancellation_check=cancellation_check,
        )
    )
    if cancellation_check is not None:
        cancellation_check()
    if matrix is not None:
        attach_common_input_evidence(matrix, exposure_observations, tuple(period_sessions))
    artifacts = compose_output(
        matrix, strategy.finalized, exposure_observations, sessions=tuple(period_sessions),
    )
    track_state = KernelState(
        run_input=run_input,
        output=artifacts,
        strategy_resume=strategy.resumable,
        origin_session=origin_session,
    )
    return RunOutput(
        artifacts=artifacts,
        strategy_ledger=strategy.ledger,
        track_state=track_state,
    )


def calculation_definition(
    run_input: RunInput,
    alpha_expression: AlphaExpression | None = None,
) -> dict[str, object]:
    strategy = run_input.strategy
    if run_input.research_kind != "strategy_backtest" or strategy is None:
        raise KernelRunError("Strategy calculation requires Strategy Backtest input")
    strategy_contract = strategy.contract_snapshot()
    costs = {name: strategy_contract.pop(name) for name in (
        "commission_rate_all_in", "commission_min_cny", "stamp_duty_sell_rate", "transfer_fee_rate",
        "slippage_bps",
    )}
    result = {"universe": run_input.universe, "strategy": strategy_contract, "costs": costs}
    if run_input.has_alpha:
        result["alpha"] = {"expression": (
            run_input.alpha_expression_snapshot() if alpha_expression is None else alpha_expression
        )}
        result["neutralization"] = run_input.neutralization
    return result



def compose_output(
    matrix: dict[str, object] | None,
    strategy: dict[str, object],
    exposure_observations: Mapping[str, list[dict[str, object]]],
    *,
    sessions: tuple[str, ...],
    prior_common_inputs: Mapping[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    observed = {row["session"]: row for row in (
        prior_common_inputs["sessions"] if prior_common_inputs is not None else []
    )}
    if observed.keys() & set(sessions):
        raise KernelRunError("Completed Common observations cannot be overwritten")
    common = {
        row["session"]: row for row in merge_common_input_sessions(
            matrix["sessions"] if matrix is not None else [], exposure_observations, sessions,
        )
    }
    observed.update({
        session: common.get(session, {"session": session, "common_inputs": []})
        for session in sessions
    })
    return {
        **({"alpha_matrix": matrix} if matrix is not None else {}),
        "common_inputs": {"sessions": [
            observed[session] for session in sorted(observed)
        ]},
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
                    **({"common_inputs": item["common_inputs"]} if "common_inputs" in item else {}),
                }
                for item in (matrix["sessions"] if matrix is not None else [])
            ],
            "strategy": strategy["diagnostics"],
        },
    }
