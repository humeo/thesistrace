from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from thesistrace.alpha_language.models import DiagnosticDetails, SourceRange

RequestId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
FolderId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
ResearchName = Annotated[str, Field(strict=True, max_length=200)]
Formula = Annotated[str, Field(strict=True)]
HoldingsCount = Annotated[int, Field(strict=True, ge=1, le=100)]
RebalanceInterval = Annotated[int, Field(strict=True, ge=1, le=20)]


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


class ResearchRunAdmissionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId
    folder_id: FolderId
    name: ResearchName | None = None
    formula: Formula
    hypothesis: str | None = None
    start_date: NaturalDate
    end_date: NaturalDate
    universe: Literal["top300", "top1000", "top2000", "top3000"]
    neutralization: Literal["none", "industry"]
    holdings_count: HoldingsCount
    rebalance_every_sessions: RebalanceInterval

    @model_validator(mode="after")
    def validate_research_period(self) -> ResearchRunAdmissionCommand:
        if self.start_date > self.end_date:
            raise ValueError("Research end date must not precede start date")
        return self


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


class ImmutableRunInput(BaseModel):
    """Private, complete value input owned by one ResearchRun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_source: str
    alpha_expression: dict[str, object]
    hypothesis: str | None
    requested_start_date: date
    requested_end_date: date
    field_bindings: dict[str, str]
    universe: Literal["top300", "top1000", "top2000", "top3000"]
    neutralization: Literal["none", "industry"]
    strategy: dict[str, object]
    costs: dict[str, str]
    risk_free_rate: str
    numeric_execution_contract: str
    semantic_versions: dict[str, str]
    alpha_admission: AlphaAdmissionFacts
    data_admission: DataAdmissionFacts


class ResearchRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal[
        "queued", "running", "cancelling", "succeeded", "failed", "cancelled"
    ]
    name: str
    folder_id: str
    created_at: datetime
    start_date: date
    end_date: date
    formula_summary: str
    failure_reason: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ResearchRunAuthorableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: str
    hypothesis: str | None
    start_date: date
    end_date: date
    universe: Literal["top300", "top1000", "top2000", "top3000"]
    neutralization: Literal["none", "industry"]
    holdings_count: int
    rebalance_every_sessions: int


class ResearchRunCancelCommand(BaseModel):
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
    input: ResearchRunAuthorableInput
    result: ResearchRunResult | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
