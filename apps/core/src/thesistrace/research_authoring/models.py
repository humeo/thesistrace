from typing import Literal

from pydantic import BaseModel, ConfigDict

from thesistrace.research_batch.models import ResearchBatchKind
from thesistrace.research_definition import SimulationCosts
from thesistrace.research_kernel.portfolio_weighting import PortfolioWeighting
from thesistrace.research_run.models import (
    ResearchKind,
    ResearchNeutralization,
    ResearchUniverse,
)


class IntegerRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    minimum: int
    maximum: int


class FormulaAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    maximum_length: int
    maximum_expression_nodes: int
    maximum_expression_depth: int
    maximum_effective_lookback: int
    maximum_estimated_work: int


class InitialCashConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    currency: Literal["CNY"] = "CNY"
    encoding: Literal["decimal_string"] = "decimal_string"
    exclusive_minimum: str = "0"
    maximum: str
    maximum_decimal_places: int = 2
    required: Literal[True] = True


class ExposureAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context: Literal["exposure"] = "exposure"
    mode: Literal["daily_expression"] = "daily_expression"
    default_expression: Literal["1"] = "1"
    minimum: Literal[0] = 0
    maximum: Literal[1] = 1
    data_series_allowed: Literal[True] = True
    result_types: tuple[Literal["number", "common_numeric_series"], ...] = (
        "number", "common_numeric_series",
    )
    stock_fields_allowed: Literal[False] = False
    decision_time: Literal["session_close"] = "session_close"
    execution_time: Literal["next_session_open"] = "next_session_open"


class PythonProgramConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    callback: str = "decide(context, state, parameters)"
    decision_time: Literal["session_close"] = "session_close"
    execution_time: Literal["next_session_open"] = "next_session_open"
    maximum_source_bytes: int
    maximum_parameter_bytes: int
    maximum_state_bytes: int
    maximum_input_bytes: int
    maximum_output_bytes: int
    maximum_memory_bytes: int
    maximum_bootstrap_wall_seconds: int
    maximum_wall_seconds: int
    maximum_fields: int
    history_sessions: IntegerRange
    python_version: str
    modules: tuple[str, ...]
    output: str = (
        'Return {"output": null or {"reason": string, "allocation": object or null, '
        '"position_limits": object}, "state": object}. Null output is NoUpdate. '
        "An optional maximum_stock_exposure number in [0, 1] caps stock targets "
        "without raising them. "
        "Only explicit JSON state survives. No filesystem or network access."
    )


class FrameworkStageConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stage: Literal[
        "universe_selection", "alpha", "portfolio_construction", "risk_management",
    ]
    builtin_identity: str
    output_contract: str


class FrameworkAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stages: tuple[FrameworkStageConstraints, ...]
    builtin_risk_schema: dict[str, object]
    builtin_portfolio_schema: dict[str, object]
    account_observation: str
    maximum_active_signals: int
    signal_validity_sessions: IntegerRange
    maximum_state_bytes: int


class ResearchAuthoringConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_kinds: tuple[ResearchKind, ...]
    strategy_modes: tuple[Literal["framework", "direct"], ...]
    simulation_cost_defaults: SimulationCosts
    simulation_cost_rules: str = (
        "All costs are finite non-negative decimal strings. Slippage must be below "
        "10000 basis points. Commission minimum applies separately to each filled "
        "child order. Slippage changes buy/sell execution prices and is not a second fee. "
        "These are simulation assumptions, frozen for the Run and its DailyTrack."
    )
    python_program: PythonProgramConstraints
    framework: FrameworkAuthoringConstraints
    universes: tuple[ResearchUniverse, ...]
    neutralizations: tuple[ResearchNeutralization, ...]
    initial_cash_cny: InitialCashConstraints
    holdings_count: IntegerRange
    selection_every_sessions: IntegerRange
    batch_items: IntegerRange
    batch_kinds: tuple[ResearchBatchKind, ...]
    exposure: ExposureAuthoringConstraints
    weighting: tuple[PortfolioWeighting, ...]
    volatility_window: IntegerRange
    volatility_window_default: int = 20
    weighting_eligibility: str = (
        "Inverse volatility uses population standard deviation of adjusted Close returns; "
        "zero volatility, insufficient history and unavailable returns "
        "are excluded in signal order."
    )
    formula: FormulaAuthoringConstraints
