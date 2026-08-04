from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

RequestId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class StartTrackingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: RequestId


class VerifiedResultOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["research.result"]
    research_run_id: str
    schema_version: str
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
    seed_release_id: str
    verified_result: VerifiedResultOrigin
    initial_strategy_state: InitialStrategyState
    calculation_contracts: dict[str, object]


class DailyTrackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: Literal["active"]
    seed_run_id: str
    seed_release_id: str
    definition_id: str
    definition_revision: int
    result_checksum_sha256: str
    strategy_session: str


class DailyTrackList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[DailyTrackSummary]
    next_cursor: str | None
