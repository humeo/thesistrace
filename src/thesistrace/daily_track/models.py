from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class RetryDailyTrackCommand(BaseModel):
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
    benchmark_nav: str
    cumulative_transaction_cost: str
    positions: list[dict[str, object]]
    rebalance_phase: dict[str, object]
    pending_signal: dict[str, object] | None
    last_daily_observation: dict[str, object]
    metric_state: dict[str, object]


class TrackingOrigin(BaseModel):
    """Complete private value origin copied into one independent DailyTrack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_run_id: str
    definition_id: str
    definition_revision: int
    immutable_input: dict[str, object]
    seed_release_id: str | None = None
    seed_data_generation_id: str | None = None
    seed_data_through_session: str | None = None
    verified_result: VerifiedResultOrigin
    initial_strategy_state: InitialStrategyState
    calculation_contracts: dict[str, object]

    @model_validator(mode="after")
    def one_seed_data_coordinate(self) -> TrackingOrigin:
        if (self.seed_release_id is None) == (self.seed_data_generation_id is None):
            raise ValueError("Tracking Origin requires one seed data coordinate")
        if (self.seed_data_generation_id is None) != (
            self.seed_data_through_session is None
        ):
            raise ValueError("current-data Tracking Origin is incomplete")
        return self


class DailyTrackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["active", "blocked", "stopped"]
    seed_run_id: str
    definition_id: str
    definition_revision: int
    result_checksum_sha256: str
    origin_session: str
    strategy_session: str


class DailyTrackList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[DailyTrackSummary]
    next_cursor: str | None


class DailyTrackOriginView(BaseModel):
    """Stable product identity of the value state from which Tracking started."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed_run_id: str
    definition_id: str
    definition_revision: int
    result_checksum_sha256: str
    strategy_session: str


class DailyTrackFactorCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_session_count: int
    ic_valid_session_count: int
    rank_ic_valid_session_count: int
    quantile_valid_session_count: int


class DailyTrackFactorHorizon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizon: Literal[1, 5, 20]
    summary: dict[str, object]
    coverage: DailyTrackFactorCoverage


class DailyTrackFactorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizons: dict[str, DailyTrackFactorHorizon]


class DailyTrackStrategyObservation(BaseModel):
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


class DailyTrackBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    universe: str
    methodology: Literal["selected_universe_equal_weight"]


class DailyTrackStrategyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: dict[str, object]
    benchmark: DailyTrackBenchmark
    observations: list[DailyTrackStrategyObservation]


class DailyTrackDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["active", "blocked", "stopped"]
    origin: DailyTrackOriginView
    strategy_session: str
    data_through_session: str
    lag_sessions: int
    blocked_reason: str | None
    factor: DailyTrackFactorResult
    strategy: DailyTrackStrategyResult


class KernelRunInputSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alpha_expression: dict[str, object]
    field_bindings: dict[str, str]
    universe: str
    neutralization: str
    holdings_count: int
    rebalance_interval: int
    initial_cash_cny: str
    commission_rate_all_in: str
    commission_min_cny: str
    stamp_duty_sell_rate: str
    transfer_fee_rate: str


class KernelStateCheckpoint(BaseModel):
    """Compact immutable product truth; transient continuation stays in cache."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["daily-track-checkpoint-v1"]
    origin_session: str
    session_count: int
    boundary_session: str
    run_input: KernelRunInputSnapshot
    alpha_state: dict[str, object]
    factor_summary: dict[str, object]
    strategy_state: dict[str, object]
    continuation_sha256: str
    pending_alpha_sessions: int
    rolling_factor_rows: int
