from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from thesistrace.alpha_language.language import MAX_FORMULA_LENGTH
from thesistrace.alpha_language.models import DiagnosticDetails, SourceRange
from thesistrace.benchmark import StrategyComparison, StrategyComparisonSummary
from thesistrace.daily_track.models import DailyTrackSummary
from thesistrace.data.models import FinancialResearchReadiness
from thesistrace.research_run.result_schema import StrategyMetrics


def _normalized_request_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("request_id must not be blank")
    return normalized


RequestId = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=200),
    AfterValidator(_normalized_request_id),
]
FolderId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
ResearchName = Annotated[str, Field(strict=True, max_length=200)]
ResearchHypothesis = Annotated[str, Field(strict=True, max_length=1024)]
Formula = Annotated[str, Field(strict=True, max_length=MAX_FORMULA_LENGTH)]
MIN_HOLDINGS_COUNT = 1
MAX_HOLDINGS_COUNT = 100
MIN_REBALANCE_INTERVAL = 1
MAX_REBALANCE_INTERVAL = 20
HoldingsCount = Annotated[
    int,
    Field(strict=True, ge=MIN_HOLDINGS_COUNT, le=MAX_HOLDINGS_COUNT),
]
RebalanceInterval = Annotated[
    int,
    Field(strict=True, ge=MIN_REBALANCE_INTERVAL, le=MAX_REBALANCE_INTERVAL),
]
type ResearchKind = Literal["factor_evaluation", "strategy_backtest"]
type ResearchRunStatus = Literal[
    "queued", "running", "cancelling", "succeeded", "failed", "cancelled"
]
type ResearchRunResultSection = Literal[
    "factor",
    "strategy_summary",
    "strategy_observations",
    "terminal_strategy_state",
    "terminal_positions",
    "provenance",
]
type ResearchUniverse = Literal["top300", "top1000", "top2000", "top3000"]
type ResearchNeutralization = Literal["none", "industry"]
RESEARCH_RUN_ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})
RESEARCH_RUN_POLL_RETRY_SECONDS = 2
FACTOR_RESULT_SECTIONS: tuple[ResearchRunResultSection, ...] = (
    "factor",
    "provenance",
)
STRATEGY_RESULT_SECTIONS: tuple[ResearchRunResultSection, ...] = (
    "factor",
    "strategy_summary",
    "strategy_observations",
    "terminal_strategy_state",
    "terminal_positions",
    "provenance",
)
RESEARCH_KINDS: tuple[ResearchKind, ...] = (
    "factor_evaluation",
    "strategy_backtest",
)
RESEARCH_UNIVERSES: tuple[ResearchUniverse, ...] = (
    "top300",
    "top1000",
    "top2000",
    "top3000",
)
RESEARCH_NEUTRALIZATIONS: tuple[ResearchNeutralization, ...] = (
    "none",
    "industry",
)


def research_run_retry_after_seconds(status: ResearchRunStatus) -> int | None:
    return RESEARCH_RUN_POLL_RETRY_SECONDS if status in RESEARCH_RUN_ACTIVE_STATUSES else None


def research_run_result_sections(
    status: ResearchRunStatus,
    research_kind: ResearchKind,
) -> tuple[ResearchRunResultSection, ...]:
    if status != "succeeded":
        return ()
    if research_kind == "factor_evaluation":
        return FACTOR_RESULT_SECTIONS
    return STRATEGY_RESULT_SECTIONS


def _natural_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError("natural date must be an ISO YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("natural date must be an ISO YYYY-MM-DD string") from error
    if parsed.isoformat() != value:
        raise ValueError("natural date must be an ISO YYYY-MM-DD string")
    return parsed


NaturalDate = Annotated[date, BeforeValidator(_natural_date)]


class _ResearchRunAdmissionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId
    folder_id: FolderId
    name: ResearchName | None = None
    formula: Formula
    hypothesis: ResearchHypothesis | None = None
    start_date: NaturalDate
    end_date: NaturalDate
    universe: ResearchUniverse
    neutralization: ResearchNeutralization

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_research_period(self) -> _ResearchRunAdmissionBase:
        if self.start_date > self.end_date:
            raise ValueError("Research end date must not precede start date")
        return self


class FactorEvaluationAdmissionCommand(_ResearchRunAdmissionBase):
    research_kind: Literal["factor_evaluation"]


class StrategyBacktestAdmissionCommand(_ResearchRunAdmissionBase):
    research_kind: Literal["strategy_backtest"]
    holdings_count: HoldingsCount
    rebalance_every_sessions: RebalanceInterval


type ResearchRunAdmissionCommand = Annotated[
    FactorEvaluationAdmissionCommand | StrategyBacktestAdmissionCommand,
    Field(discriminator="research_kind"),
]


class ResearchRunAdmissionIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    field: str
    message: str
    severity: Literal["error"] = "error"
    range: SourceRange | None = None
    details: DiagnosticDetails | None = None


class ResearchRunAdmissionRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issues: list[ResearchRunAdmissionIssue]


class OrganizeResearchRunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: ResearchName | None = None
    folder_id: FolderId | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Research name must not be blank")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> OrganizeResearchRunCommand:
        if self.name is None and self.folder_id is None:
            raise ValueError("Research organization change is required")
        return self


class AlphaAdmissionFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effective_lookback: int
    node_count: int
    depth: int
    formula_work: int
    estimated_run_work: int


class DataAdmissionFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_manifest_sha256: str
    data_through_session: NaturalDate
    coverage_start: NaturalDate
    coverage_end: NaturalDate
    first_research_session: NaturalDate
    last_research_session: NaturalDate
    calculation_session_count: int
    universe_instrument_count: int
    financial_research_readiness: FinancialResearchReadiness


class ResearchExecutionChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int
    first_session: NaturalDate
    last_session: NaturalDate
    session_count: int
    warmup_session_count: int
    research_session_count: int


class ResearchExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_memory_bytes: int
    chunk_time_target_seconds: int
    chunk_session_count: int
    time_target_exceeded: bool
    estimated_peak_bytes: int
    estimated_chunk_work: int
    maximum_universe_cardinality: int
    calculation_sessions: tuple[NaturalDate, ...]
    research_session_offset: int
    research_session_count: int
    chunks: tuple[ResearchExecutionChunk, ...]


class ImmutableRunInput(BaseModel):
    """Private, complete value input owned by one ResearchRun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_source: str
    alpha_expression: dict[str, object]
    hypothesis: ResearchHypothesis | None
    requested_start_date: date
    requested_end_date: date
    field_bindings: dict[str, str]
    universe: ResearchUniverse
    neutralization: ResearchNeutralization
    research_kind: ResearchKind
    strategy: dict[str, object] | None = None
    costs: dict[str, str] | None = None
    risk_free_rate: str | None = None
    numeric_execution_contract: str
    semantic_versions: dict[str, str]
    alpha_admission: AlphaAdmissionFacts
    data_admission: DataAdmissionFacts
    execution_plan: ResearchExecutionPlan

    @model_validator(mode="after")
    def validate_research_kind_contract(self) -> ImmutableRunInput:
        strategy_values = (self.strategy, self.costs, self.risk_free_rate)
        if self.research_kind == "factor_evaluation" and any(
            value is not None for value in strategy_values
        ):
            raise ValueError("Factor Evaluation immutable input cannot contain Strategy values")
        if self.research_kind == "strategy_backtest" and any(
            value is None for value in strategy_values
        ):
            raise ValueError("Strategy Backtest immutable input requires Strategy values")
        return self

    def canonical_value(self) -> dict[str, object]:
        value = self.model_dump(mode="json")
        if self.research_kind == "factor_evaluation":
            for name in ("strategy", "costs", "risk_free_rate"):
                value.pop(name)
        return value


class FactorEvaluationResearchRunKeyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_kind: Literal["factor_evaluation"]
    one_session_rank_ic: StrictFloat | StrictInt | None
    five_session_rank_ic: StrictFloat | StrictInt | None
    twenty_session_rank_ic: StrictFloat | StrictInt | None


class StrategyBacktestResearchRunKeyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_kind: Literal["strategy_backtest"]
    annualized_excess_return: StrictFloat | StrictInt | None
    sharpe: StrictFloat | StrictInt | None
    maximum_drawdown: StrictFloat | StrictInt


type ResearchRunKeyMetrics = Annotated[
    FactorEvaluationResearchRunKeyMetrics | StrategyBacktestResearchRunKeyMetrics,
    Field(discriminator="research_kind"),
]


class ResearchRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(max_length=200)]
    status: ResearchRunStatus
    name: ResearchName
    folder_id: FolderId
    created_at: datetime
    start_date: date
    end_date: date
    formula_summary: Annotated[str, Field(max_length=120)]
    research_kind: ResearchKind
    key_metrics: ResearchRunKeyMetrics | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    failure_reason: Annotated[str, Field(max_length=512)] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_key_metrics_kind(self) -> ResearchRunSummary:
        if self.key_metrics is not None and self.key_metrics.research_kind != self.research_kind:
            raise ValueError("ResearchRun key metrics must match its Research Kind")
        return self


class ResearchRunCancelOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["accepted"] = "accepted"
    run: ResearchRunSummary
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class ResearchRunAdmissionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["accepted"] = "accepted"
    run: ResearchRunSummary
    replayed: bool
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class ResearchRunAdmissionRejectedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["rejected"] = "rejected"
    issues: Annotated[list[ResearchRunAdmissionIssue], Field(min_length=1)]
    replayed: bool


type ResearchRunAdmissionOutcome = Annotated[
    ResearchRunAdmissionAccepted | ResearchRunAdmissionRejectedOutcome,
    Field(discriminator="outcome"),
]


class ResearchRunAuthorableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: Formula
    hypothesis: ResearchHypothesis | None
    start_date: date
    end_date: date
    universe: ResearchUniverse
    neutralization: ResearchNeutralization
    research_kind: ResearchKind
    holdings_count: int | None = Field(default=None, exclude_if=lambda value: value is None)
    rebalance_every_sessions: int | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_research_kind_contract(self) -> ResearchRunAuthorableInput:
        strategy_values = (self.holdings_count, self.rebalance_every_sessions)
        if self.research_kind == "factor_evaluation" and any(
            value is not None for value in strategy_values
        ):
            raise ValueError("Factor Evaluation authorable input cannot contain Strategy values")
        if self.research_kind == "strategy_backtest" and any(
            value is None for value in strategy_values
        ):
            raise ValueError("Strategy Backtest authorable input requires Strategy values")
        return self


class ResearchRunCancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class StartTrackingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class ResearchRunStartTrackingOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track: DailyTrackSummary
    status: Literal["active"] = "active"
    replayed: bool
    retry_after_seconds: Literal[30] = 30


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
    net_cash: str
    transaction_cost_cny: str
    holdings_count: int
    maximum_single_name_weight: float
    upper_limit_buy_rejections: int
    lower_limit_sell_rejections: int
    suspension_rejections: int


class StrategyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: dict[str, object]
    observations: list[StrategyDailyObservation]
    comparison: StrategyComparison


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
    cumulative_transaction_cost: str
    positions: list[TerminalStrategyPosition]
    rebalance_phase: TerminalRebalancePhase
    pending_signal: TerminalPendingSignal | None


class _ResultProvenanceBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    research_run_id: str
    immutable_input_sha256: str
    calculation_contracts: dict[str, object]
    semantic_versions: dict[str, str]


class FactorEvaluationResultProvenance(_ResultProvenanceBase):
    research_kind: Literal["factor_evaluation"]


class StrategyBacktestResultProvenance(_ResultProvenanceBase):
    research_kind: Literal["strategy_backtest"]


class FactorEvaluationResearchRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: FactorResult
    provenance: FactorEvaluationResultProvenance


class StrategyBacktestResearchRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: FactorResult
    strategy: StrategyResult
    terminal_strategy_state: TerminalStrategyStateView
    provenance: StrategyBacktestResultProvenance


type ResearchRunResult = FactorEvaluationResearchRunResult | StrategyBacktestResearchRunResult


ResultCursor = Annotated[str, Field(strict=True, min_length=1, max_length=1024)]
ResultPageLimit = Annotated[int, Field(strict=True, ge=1, le=50)]


class _ResearchRunResultSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: Annotated[str, Field(min_length=1, max_length=200)]


class FactorResultSectionInput(_ResearchRunResultSectionInput):
    section: Literal["factor"]


class StrategySummaryResultSectionInput(_ResearchRunResultSectionInput):
    section: Literal["strategy_summary"]


class StrategyObservationsResultSectionInput(_ResearchRunResultSectionInput):
    section: Literal["strategy_observations"]
    cursor: ResultCursor | None = None
    limit: ResultPageLimit = 20


class TerminalStrategyStateResultSectionInput(_ResearchRunResultSectionInput):
    section: Literal["terminal_strategy_state"]


class TerminalPositionsResultSectionInput(_ResearchRunResultSectionInput):
    section: Literal["terminal_positions"]
    cursor: ResultCursor | None = None
    limit: ResultPageLimit = 20


class ProvenanceResultSectionInput(_ResearchRunResultSectionInput):
    section: Literal["provenance"]


type ResearchRunResultSectionInput = Annotated[
    FactorResultSectionInput
    | StrategySummaryResultSectionInput
    | StrategyObservationsResultSectionInput
    | TerminalStrategyStateResultSectionInput
    | TerminalPositionsResultSectionInput
    | ProvenanceResultSectionInput,
    Field(discriminator="section"),
]


class FactorMetricUnits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    horizon: Literal["research_sessions"] = "research_sessions"
    ic: Literal["correlation"] = "correlation"
    rank_ic: Literal["rank_correlation"] = "rank_correlation"
    quantile_returns: Literal["decimal_return"] = "decimal_return"
    top_bottom_return: Literal["decimal_return"] = "decimal_return"


class FactorMissingValueSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    unavailable_optional_metric: Literal["null"] = "null"
    observed_zero_is_missing: Literal[False] = False


class FactorResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    section: Literal["factor"] = "factor"
    run_id: str
    research_kind: ResearchKind
    factor: FactorResult
    units: FactorMetricUnits = FactorMetricUnits()
    missing_values: FactorMissingValueSemantics = FactorMissingValueSemantics()


class StrategySummaryResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["strategy_summary"] = "strategy_summary"
    run_id: str
    research_kind: Literal["strategy_backtest"] = "strategy_backtest"
    entry_session: str
    initial_cash_cny: str
    metrics: StrategyMetrics
    comparison: StrategyComparisonSummary


class StrategyObservationsResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["strategy_observations"] = "strategy_observations"
    run_id: str
    research_kind: Literal["strategy_backtest"] = "strategy_backtest"
    items: list[StrategyDailyObservation]
    next_cursor: str | None


class TerminalStrategyStateResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["terminal_strategy_state"] = "terminal_strategy_state"
    run_id: str
    research_kind: Literal["strategy_backtest"] = "strategy_backtest"
    session: str
    gross_cash: str
    net_cash: str
    gross_nav: str
    net_nav: str
    cumulative_transaction_cost: str
    rebalance_phase: TerminalRebalancePhase
    pending_signal: TerminalPendingSignal | None


class TerminalPositionsResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["terminal_positions"] = "terminal_positions"
    run_id: str
    research_kind: Literal["strategy_backtest"] = "strategy_backtest"
    items: list[TerminalStrategyPosition]
    next_cursor: str | None


class ResultDataProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_id: str
    data_through_session: date
    financial_research_readiness: FinancialResearchReadiness


class ResultExecutionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calculation_contracts: dict[str, object]
    semantic_versions: dict[str, str]


class ProvenanceResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["provenance"] = "provenance"
    run_id: str
    research_kind: ResearchKind
    schema_version: str
    immutable_input_sha256: str
    authoring_input: ResearchRunAuthorableInput
    data: ResultDataProvenance
    execution: ResultExecutionProvenance


type ResearchRunResultSectionResponse = Annotated[
    FactorResultSection
    | StrategySummaryResultSection
    | StrategyObservationsResultSection
    | TerminalStrategyStateResultSection
    | TerminalPositionsResultSection
    | ProvenanceResultSection,
    Field(discriminator="section"),
]


class ResearchRunProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: Literal[
        "queued", "preparing_data", "shared_alpha_factor", "waiting_for_execution",
        "warmup", "research", "strategy", "finalizing", "recovering", "succeeded",
    ]
    completed_warmup_sessions: int
    total_warmup_sessions: int
    completed_research_sessions: int
    total_research_sessions: int
    committed_chunk_count: int
    last_completed_warmup_session: date | None = None
    last_completed_research_session: date | None = None
    remaining_duration_estimate_seconds: int | None = None
    duration_is_estimate: bool = True


class ResearchRunExecutionTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    started_at: datetime | None
    finished_at: datetime | None
    elapsed_seconds: float | None
    is_final: bool


class ResearchRunPollingDetail(ResearchRunSummary):
    input: ResearchRunAuthorableInput
    progress: ResearchRunProgress
    execution_timing: ResearchRunExecutionTiming
    result_available: bool
    available_result_sections: tuple[ResearchRunResultSection, ...]
    retry_after_seconds: int | None

    @model_validator(mode="after")
    def validate_polling_projection(self) -> ResearchRunPollingDetail:
        expected_retry = research_run_retry_after_seconds(self.status)
        if self.retry_after_seconds != expected_retry:
            raise ValueError("ResearchRun retry guidance must match active lifecycle state")
        expected_sections = research_run_result_sections(self.status, self.research_kind)
        if self.available_result_sections != expected_sections:
            raise ValueError("ResearchRun Result sections must match lifecycle and Research Kind")
        if self.result_available != bool(expected_sections):
            raise ValueError("ResearchRun Result availability must match its public sections")
        return self


class ResearchRunDetail(ResearchRunSummary):
    input: ResearchRunAuthorableInput
    progress: ResearchRunProgress
    execution_timing: ResearchRunExecutionTiming
    result: ResearchRunResult | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
