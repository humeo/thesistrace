from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

RequestId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class ImmutableRunInput(BaseModel):
    """Private, complete value input owned by one ResearchRun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: dict[str, object]
    requested_start_date: date
    requested_end_date: date
    field_bindings: dict[str, str]
    strategy: dict[str, object]
    costs: dict[str, str]
    risk_free_rate: str
    numeric_execution_contract: str
    semantic_versions: dict[str, str]


class ResearchRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    definition_id: str
    definition_revision: int
    start_date: date
    end_date: date
    rerun_of_id: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    failure_reason: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ResearchRunCancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class ResearchRunRerunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class StartTrackingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class ResearchRunList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ResearchRunSummary]
    next_cursor: str | None


class FactorCorrelationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mean: float | None
    sample_deviation: float | None
    icir: float | None
    positive_fraction: float | None
    valid_session_count: int


class FactorQuantileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    q1: float | None
    q2: float | None
    q3: float | None
    q4: float | None
    q5: float | None


class FactorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ic: FactorCorrelationSummary
    rank_ic: FactorCorrelationSummary
    quantile_returns: FactorQuantileSummary
    top_bottom_return: float | None


class FactorCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_session_count: int
    ic_valid_session_count: int
    rank_ic_valid_session_count: int
    quantile_valid_session_count: int


class FactorHorizonResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizon: Literal[1, 5, 20]
    summary: FactorSummary
    coverage: FactorCoverage


class FactorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizons: dict[str, FactorHorizonResult]


class StrategyDailyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str
    gross_nav: str
    net_nav: str
    benchmark_nav: str
    net_cash: str
    transaction_cost_cny: str
    holdings_count: int
    maximum_single_name_weight: float
    upper_limit_buy_rejections: int
    lower_limit_sell_rejections: int
    suspension_rejections: int


class StrategyBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    universe: str
    methodology: Literal["selected_universe_equal_weight"]


class StrategyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: dict[str, object]
    benchmark: StrategyBenchmark
    observations: list[StrategyDailyObservation]


class TerminalStrategyPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    execution_shares: int
    adjusted_units: str
    last_adjusted_price: str


class TerminalRebalancePhase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    origin_session: str
    report_session_count: int
    rebalance_interval: int
    completed_intervals: int


class TerminalPendingSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_session: str
    execution: Literal["next_research_session_open"]


class TerminalStrategyStateView(BaseModel):
    """Product account boundary; continuation accumulators remain private."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str
    gross_cash: str
    net_cash: str
    gross_nav: str
    net_nav: str
    benchmark_nav: str
    cumulative_transaction_cost: str
    positions: list[TerminalStrategyPosition]
    rebalance_phase: TerminalRebalancePhase
    pending_signal: TerminalPendingSignal | None


class ResultProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    research_run_id: str
    immutable_input_sha256: str
    calculation_contracts: dict[str, object]
    semantic_versions: dict[str, str]


class ResearchRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: FactorResult
    strategy: StrategyResult
    terminal_strategy_state: TerminalStrategyStateView
    provenance: ResultProvenance


class ResearchRunDetail(ResearchRunSummary):
    result: ResearchRunResult | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
