from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from thesistrace.benchmark import StrategyComparison, StrategyComparisonSummary
from thesistrace.daily_holding_queries import (
    HoldingDetailsPage,
    HoldingDetailsQuery,
    HoldingStatusPage,
    HoldingStatusQuery,
)
from thesistrace.daily_track.observation_state import TrackingObservationState
from thesistrace.research_kernel.common_inputs import common_input_references
from thesistrace.research_kernel.common_observations import CommonInputObservation
from thesistrace.research_kernel.portfolio_weighting import PortfolioWeighting, VolatilityWindow
from thesistrace.research_kernel.terminal_state_schema import PendingTarget, TargetSelection
from thesistrace.strategy_evidence import (
    StrategyAdjustmentsPage,
    StrategyAdjustmentsQuery,
    StrategyChildOrdersPage,
    StrategyChildOrdersQuery,
    StrategyFillsPage,
    StrategyFillsQuery,
    StrategyOrdersPage,
    StrategyOrdersQuery,
    StrategyTargetsPage,
    StrategyTargetsQuery,
)

RequestId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
type DailyTrackResultSection = Literal[
    "strategy_targets", "strategy_orders", "strategy_child_orders",
    "strategy_fills", "strategy_adjustments", "daily_holdings_status", "daily_holdings",
    "strategy_summary",
    "strategy_observations",
    "origin",
    "provenance",
    "common_input_observations",
]
DAILY_TRACK_RESULT_SECTIONS: tuple[DailyTrackResultSection, ...] = (
    "strategy_targets", "strategy_orders", "strategy_child_orders",
    "strategy_fills", "strategy_adjustments", "daily_holdings_status", "daily_holdings",
    "strategy_summary",
    "strategy_observations",
    "origin",
    "provenance",
    "common_input_observations",
)
DailyTrackResultCursor = Annotated[str, Field(strict=True, min_length=1, max_length=1024)]
DailyTrackResultPageLimit = Annotated[int, Field(strict=True, ge=1, le=50)]


class _DailyTrackResultSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track_id: Annotated[str, Field(strict=True, min_length=1, max_length=200)]




class DailyTrackStrategySummaryResultSectionInput(_DailyTrackResultSectionInput):
    section: Literal["strategy_summary"]


class DailyTrackStrategyObservationsResultSectionInput(_DailyTrackResultSectionInput):
    section: Literal["strategy_observations"]
    cursor: DailyTrackResultCursor | None = None
    limit: DailyTrackResultPageLimit = 20


class DailyTrackCommonInputObservationsResultSectionInput(_DailyTrackResultSectionInput):
    section: Literal["common_input_observations"]
    cursor: DailyTrackResultCursor | None = None
    limit: DailyTrackResultPageLimit = 20


class DailyTrackOriginResultSectionInput(_DailyTrackResultSectionInput):
    section: Literal["origin"]
    cursor: DailyTrackResultCursor | None = None
    limit: DailyTrackResultPageLimit = 20


class DailyTrackProvenanceResultSectionInput(_DailyTrackResultSectionInput):
    section: Literal["provenance"]


class TrackStrategyTargetsInput(_DailyTrackResultSectionInput, StrategyTargetsQuery):
    pass


class TrackStrategyOrdersInput(_DailyTrackResultSectionInput, StrategyOrdersQuery):
    pass


class TrackStrategyChildOrdersInput(_DailyTrackResultSectionInput, StrategyChildOrdersQuery):
    pass


class TrackStrategyFillsInput(_DailyTrackResultSectionInput, StrategyFillsQuery):
    pass


class TrackStrategyAdjustmentsInput(_DailyTrackResultSectionInput, StrategyAdjustmentsQuery):
    pass


class TrackHoldingStatusInput(_DailyTrackResultSectionInput, HoldingStatusQuery):
    pass


class TrackHoldingDetailsInput(_DailyTrackResultSectionInput, HoldingDetailsQuery):
    pass


type DailyTrackResultSectionInput = Annotated[
    DailyTrackStrategySummaryResultSectionInput
    | DailyTrackStrategyObservationsResultSectionInput
    | DailyTrackOriginResultSectionInput
    | DailyTrackProvenanceResultSectionInput
    | DailyTrackCommonInputObservationsResultSectionInput
    | TrackStrategyTargetsInput
    | TrackStrategyOrdersInput
    | TrackStrategyChildOrdersInput
    | TrackStrategyFillsInput
    | TrackStrategyAdjustmentsInput
    | TrackHoldingStatusInput
    | TrackHoldingDetailsInput,
    Field(discriminator="section"),
]


class RetryDailyTrackCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class RefreshDailyTrackCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class StopDailyTrackCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class VerifiedResultOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["research.result"]
    research_run_id: str
    schema_version: str
    result_manifest_sha256: str
    result_checksum_sha256: str


class InitialStrategyState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str
    gross_cash: str
    net_cash: str
    gross_nav: str
    net_nav: str
    cumulative_transaction_cost: str
    positions: list[dict[str, object]]
    selection_phase: dict[str, object]
    target_selection: TargetSelection
    target_exposure: float = Field(ge=0, le=1, allow_inf_nan=False)
    pending_target: dict[str, object] | None
    last_daily_observation: dict[str, object]
    metric_state: dict[str, object]


class TrackingOrigin(BaseModel):
    """Complete private value origin copied into one independent DailyTrack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_run_id: str
    immutable_input: dict[str, object]
    seed_data_generation_id: str
    seed_data_through_session: str
    verified_result: VerifiedResultOrigin
    strategy_entry_session: str | None
    strategy_initial_cash_cny: str
    initial_strategy_state: InitialStrategyState
    calculation_contracts: dict[str, object]

    @property
    def expression_trees(self) -> tuple[dict[str, object], ...]:
        return (
            self.immutable_input["alpha_expression"],
            self.immutable_input["strategy"]["exposure_expression"],
        )


class DailyTrackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["active", "blocked", "stopping", "stopped"]
    seed_run_id: str
    result_checksum_sha256: str
    origin_session: str
    strategy_session: str


class DailyTrackRetryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track: DailyTrackSummary
    replayed: bool
    retry_after_seconds: Literal[2] | None

    @model_validator(mode="after")
    def validate_polling_guidance(self) -> DailyTrackRetryOutcome:
        if self.track.status not in {"active", "blocked"}:
            raise ValueError("DailyTrack Retry outcome has an illegal status")
        expected = daily_track_polling_retry_after_seconds(
            status=self.track.status,
            phase="queued" if self.track.status == "active" else "blocked",
        )
        if self.retry_after_seconds != expected:
            raise ValueError("DailyTrack Retry polling guidance does not match its outcome")
        return self


class DailyTrackRefreshOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track: DailyTrackSummary
    replayed: bool
    retry_after_seconds: Literal[2]

    @model_validator(mode="after")
    def validate_polling_guidance(self) -> DailyTrackRefreshOutcome:
        if self.track.status != "active":
            raise ValueError("DailyTrack Refresh outcome has an illegal status")
        expected = daily_track_polling_retry_after_seconds(
            status=self.track.status,
            phase="queued",
        )
        if self.retry_after_seconds != expected:
            raise ValueError("DailyTrack Refresh polling guidance does not match its outcome")
        return self


class DailyTrackStopOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    track: DailyTrackSummary
    replayed: bool
    retry_after_seconds: Literal[2] | None

    @model_validator(mode="after")
    def validate_polling_guidance(self) -> DailyTrackStopOutcome:
        if self.track.status not in {"stopping", "stopped"}:
            raise ValueError("DailyTrack Stop outcome has an illegal status")
        expected = daily_track_polling_retry_after_seconds(
            status=self.track.status,
            phase=self.track.status,
        )
        if self.retry_after_seconds != expected:
            raise ValueError("DailyTrack Stop polling guidance does not match its outcome")
        return self


def daily_track_polling_retry_after_seconds(*, status: str, phase: str) -> int | None:
    """Return the one public polling cadence for a DailyTrack lifecycle state."""

    if status in {"blocked", "stopped"}:
        return None
    if status == "stopping" or phase in {
        "queued",
        "retry_wait",
        "starting",
        "calculating",
        "result_ready",
        "staging",
    }:
        return 2
    return 30


class DailyTrackList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[DailyTrackSummary]
    next_cursor: str | None


class DailyTrackPollingOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    research_run_id: str
    origin_session: str
    result_checksum_sha256: str


class DailyTrackPollingProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    head_session: str
    data_through_session: str
    lag_sessions: int
    phase: Literal[
        "waiting",
        "queued",
        "retry_wait",
        "starting",
        "calculating",
        "result_ready",
        "staging",
        "stopping",
        "blocked",
        "up_to_date",
        "stopped",
    ]
    target_start_session: str | None
    target_end_session: str | None
    target_session_count: int
    current_session: str | None
    retry_wait: bool
    next_retry_eligible_at: str | None


class DailyTrackPollingTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    activated_at: datetime
    state_updated_at: datetime
    current_action_started_at: datetime | None
    current_action_finished_at: datetime | None
    observed_at: datetime


class DailyTrackActionEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    refresh: bool
    retry: bool
    stop: bool


class DailyTrackPollingDetail(BaseModel):
    """Compact public lifecycle view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["active", "blocked", "stopping", "stopped"]
    origin: DailyTrackPollingOrigin
    progress: DailyTrackPollingProgress
    timing: DailyTrackPollingTiming
    blocked_reason: str | None
    action_eligibility: DailyTrackActionEligibility
    available_result_sections: list[DailyTrackResultSection]
    retry_after_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] | None


class DailyTrackOriginPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    execution_shares: int
    adjusted_units: str
    last_adjusted_price: str


class DailyTrackOriginSelectionPhase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    origin_session: str
    report_session_count: int
    selection_interval: int
    completed_intervals: int


class DailyTrackOriginAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str
    gross_cash: str
    net_cash: str
    gross_nav: str
    net_nav: str
    cumulative_transaction_cost: str
    positions: list[DailyTrackOriginPosition]
    selection_phase: DailyTrackOriginSelectionPhase
    target_selection: TargetSelection
    target_exposure: float = Field(ge=0, le=1, allow_inf_nan=False)
    pending_target: PendingTarget | None


class DailyTrackOriginView(BaseModel):
    """Stable product identity of the value state from which Tracking started."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_run_id: str
    seed_research_available: bool
    result_checksum_sha256: str
    strategy_session: str
    terminal_account: DailyTrackOriginAccount




type DailyTrackStrictNumber = StrictInt | StrictFloat
type DailyTrackOptionalNumber = DailyTrackStrictNumber | None












class DailyTrackStrategyObservation(BaseModel):
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


class DailyTrackStrategyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: dict[str, object]
    observations: list[DailyTrackStrategyObservation]
    comparison: StrategyComparison




class DailyTrackMissingValueSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    unavailable_optional_metric: Literal["null"] = "null"
    observed_zero_is_missing: Literal[False] = False




class DailyTrackStrategyMetricUnits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    nav: Literal["normalized_value"] = "normalized_value"
    cash: Literal["cny"] = "cny"
    transaction_cost: Literal["cny"] = "cny"
    return_value: Literal["decimal_return"] = "decimal_return"
    drawdown: Literal["fraction"] = "fraction"
    weight: Literal["fraction"] = "fraction"


class DailyTrackCashRatioMaximum(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session: str
    value: DailyTrackStrictNumber


class DailyTrackCashRatio(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ending: DailyTrackStrictNumber
    maximum: DailyTrackCashRatioMaximum
    mean: DailyTrackStrictNumber


class DailyTrackHoldingsCount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ending: StrictInt
    maximum: StrictInt
    mean: DailyTrackStrictNumber
    minimum: StrictInt


class DailyTrackMarketRejections(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    lower_limit_sell: StrictInt
    suspension: StrictInt
    upper_limit_buy: StrictInt


class DailyTrackMaximumDrawdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    peak_session: str
    recovery_session: str | None
    trough_session: str
    unrecovered: StrictBool
    value: DailyTrackStrictNumber


class DailyTrackMaximumWeightPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session: str
    value: DailyTrackStrictNumber


class DailyTrackMaximumSingleNameWeight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ending: DailyTrackStrictNumber
    period_maximum: DailyTrackMaximumWeightPoint


class DailyTrackTransactionCosts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cumulative_amount: DailyTrackStrictNumber
    ratio: DailyTrackStrictNumber
    return_drag: DailyTrackStrictNumber


class DailyTrackTurnover(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    annualized: DailyTrackOptionalNumber
    average_rebalance: DailyTrackOptionalNumber


class DailyTrackStrategyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    annualized_volatility: DailyTrackOptionalNumber
    calmar: DailyTrackOptionalNumber
    cash_ratio: DailyTrackCashRatio
    gross_cagr: DailyTrackOptionalNumber
    gross_cumulative_return: DailyTrackOptionalNumber
    holdings_count: DailyTrackHoldingsCount
    market_rejections: DailyTrackMarketRejections
    maximum_drawdown: DailyTrackMaximumDrawdown
    maximum_single_name_weight: DailyTrackMaximumSingleNameWeight
    net_cagr: DailyTrackOptionalNumber
    net_cumulative_return: DailyTrackOptionalNumber
    risk_free_rate: DailyTrackOptionalNumber
    sharpe: DailyTrackOptionalNumber
    transaction_costs: DailyTrackTransactionCosts
    turnover: DailyTrackTurnover


class DailyTrackStrategySummaryResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["strategy_summary"] = "strategy_summary"
    track_id: str
    origin_session: date
    strategy_session: date
    summary: DailyTrackStrategyMetrics
    comparison: StrategyComparisonSummary
    units: DailyTrackStrategyMetricUnits = DailyTrackStrategyMetricUnits()
    missing_values: DailyTrackMissingValueSemantics = DailyTrackMissingValueSemantics()


class DailyTrackStrategyObservationsResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["strategy_observations"] = "strategy_observations"
    track_id: str
    items: list[DailyTrackStrategyObservation]
    next_cursor: str | None


class DailyTrackCommonInputObservationsResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["common_input_observations"] = "common_input_observations"
    track_id: str
    items: list[CommonInputObservation]
    next_cursor: str | None


class DailyTrackOriginAccountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: date
    gross_cash: str
    net_cash: str
    gross_nav: str
    net_nav: str
    cumulative_transaction_cost: str
    selection_phase: DailyTrackOriginSelectionPhase
    target_selection: TargetSelection
    target_exposure: float = Field(ge=0, le=1, allow_inf_nan=False)
    pending_target: PendingTarget | None


class DailyTrackOriginResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["origin"] = "origin"
    track_id: str
    seed_run_id: str
    seed_research_available: bool
    result_checksum_sha256: str
    terminal_account: DailyTrackOriginAccountSummary
    positions: list[DailyTrackOriginPosition]
    next_cursor: str | None


class DailyTrackFrozenResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: Annotated[str, Field(max_length=4096)]
    hypothesis: Annotated[str, Field(max_length=1024)] | None
    start_date: date
    end_date: date
    universe: str
    neutralization: str
    initial_cash_cny: str
    holdings_count: int
    selection_every_sessions: int
    exposure_expression: str
    weighting: PortfolioWeighting
    volatility_window: VolatilityWindow


class DailyTrackProvenanceResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: Literal["provenance"] = "provenance"
    track_id: str
    origin_research_run_id: str
    origin_result_checksum_sha256: str
    origin_result_schema_version: str
    immutable_input_sha256: str
    frozen_research_input: DailyTrackFrozenResearchInput
    origin_data_through_session: date
    tracking_strategy_session: date
    calculation_contracts: dict[str, object]
    semantic_versions: dict[str, str]


type DailyTrackResultSectionResponse = Annotated[
    DailyTrackStrategySummaryResultSection
    | DailyTrackStrategyObservationsResultSection
    | DailyTrackOriginResultSection
    | DailyTrackProvenanceResultSection
    | DailyTrackCommonInputObservationsResultSection
    | StrategyTargetsPage
    | StrategyOrdersPage
    | StrategyChildOrdersPage
    | StrategyFillsPage
    | StrategyAdjustmentsPage
    | HoldingStatusPage
    | HoldingDetailsPage,
    Field(discriminator="section"),
]


class DailyTrackProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    head_session: str
    lag_sessions: int
    phase: Literal[
        "waiting",
        "queued",
        "retry_wait",
        "starting",
        "calculating",
        "result_ready",
        "staging",
        "stopping",
        "blocked",
        "up_to_date",
        "stopped",
    ]
    target_start_session: str | None
    target_end_session: str | None
    target_session_count: int
    completed_target_sessions: int
    current_session: str | None
    cycle_attempt: int | None
    cycle_attempt_limit: int
    retry_wait: bool
    next_attempt_eligible_at: str | None


class DailyTrackHolding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    shares: int
    market_value_cny: str
    weight: float


class DailyTrackObservationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str
    net_return: float


class DailyTrackObservation(BaseModel):
    """The published account and performance since the immutable Tracking Origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session: str
    net_asset_value_cny: str
    cash_cny: str
    net_change_cny: str
    net_return: float
    maximum_drawdown: float
    transaction_cost_cny: str
    session_count: int
    holdings: list[DailyTrackHolding]
    target_exposure: float = Field(ge=0, le=1)
    target_selection: TargetSelection
    selection_interval: int
    pending_target_session: str | None
    sessions_until_next_signal: int
    returns: list[DailyTrackObservationPoint]


class DailyTrackDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["active", "blocked", "stopping", "stopped"]
    origin: DailyTrackOriginView
    strategy_session: str
    data_through_session: str
    lag_sessions: int
    progress: DailyTrackProgress
    blocked_reason: str | None
    observation: DailyTrackObservation
    strategy: DailyTrackStrategyResult


class KernelRunInputSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    research_kind: Literal["strategy_backtest"]
    alpha_expression: dict[str, object]
    field_bindings: dict[str, str]
    effective_lookback: int
    universe: str
    neutralization: str
    holdings_count: int
    selection_interval: int
    exposure_expression: dict[str, object]
    weighting: PortfolioWeighting
    volatility_window: VolatilityWindow
    initial_cash_cny: str
    commission_rate_all_in: str
    commission_min_cny: str
    stamp_duty_sell_rate: str
    transfer_fee_rate: str


class KernelStateCheckpoint(BaseModel):
    """Compact immutable product truth; transient continuation stays in cache."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["daily-track-checkpoint-v3"]
    tracking_observation_state: TrackingObservationState
    origin_session: str
    boundary_session: str
    run_input: KernelRunInputSnapshot
    alpha_state: dict[str, object]
    strategy_state: dict[str, object]
    common_input_observations: list[CommonInputObservation]
    continuation_sha256: str
    pending_alpha_sessions: int


    @model_validator(mode="after")
    def observation_boundary_matches(self) -> KernelStateCheckpoint:
        if self.tracking_observation_state.boundary_session != self.boundary_session:
            raise ValueError("Checkpoint observation boundary differs")
        references = common_input_references(
            self.run_input.alpha_expression, self.run_input.exposure_expression,
        )
        delta = self.strategy_state.get("retained_delta")
        if not isinstance(delta, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("session"), str) for row in delta
        ):
            raise ValueError("Checkpoint retained Sessions are invalid")
        expected = {
            (row["session"], identifier, code or "")
            for row in delta
            for identifier, code in references
        }
        actual = [
            (row.session, row.identifier, row.industry_code or "")
            for row in self.common_input_observations
        ]
        if actual != sorted(expected):
            raise ValueError(
                "Checkpoint common observations do not cover its frozen inputs and delta"
            )
        return self
