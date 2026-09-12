from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FinancialAvailableReadiness = Literal[
    "ready",
    "ready_with_pending",
    "ready_with_gaps",
]
FinancialResearchReadiness = Literal[
    "ready",
    "ready_with_pending",
    "ready_with_gaps",
    "not_ready",
]


class DatasetCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date


class FinancialCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    discovery_baseline_session: date
    discovery_attempted_through_session: date
    discovery_complete_through_session: date
    historical_reconciliation_watermark: date
    revision_coverage: str
    seed_policy: str
    readiness_status: FinancialAvailableReadiness
    pending_instrument_count: int
    discovery_gap_count: int
    earliest_unresolved_date: date | None
    sparse_facts: bool = True


class IndustryCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    observation_through_session: date
    classification_version: Literal["SW2021"] = "SW2021"


class FieldFamilyAvailability(BaseModel):
    model_config = ConfigDict(frozen=True)

    family_id: str
    research_category: Literal["market", "financial"]
    source_endpoints: list[str]
    supported_field_ids: list[str]
    available_field_ids: list[str]
    coverage_start: date | None
    coverage_end: date | None
    readiness: Literal[
        "ready", "partial", "not_ready", "ready_with_pending", "ready_with_gaps"
    ]


class DataOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    generation_manifest_sha256: str | None = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    available_field_ids: list[str]
    field_families: list[FieldFamilyAvailability]
    market_coverage: DatasetCoverage | None
    financial_coverage: FinancialCoverage | None
    industry_coverage: IndustryCoverage | None
    benchmark_coverage: DatasetCoverage | None
    benchmark_snapshot_sha256: str | None
    benchmark_last_published_at: datetime | None
    data_through_session: date | None
    last_market_refresh_at: datetime | None
    last_financial_refresh_at: datetime | None
    last_industry_refresh_at: datetime | None
    industry_refresh_status: Literal["running", "succeeded", "failed"] | None
    industry_refresh_failure_code: str | None
    market_research_readiness: bool
    benchmark_research_readiness: bool
    financial_research_readiness: FinancialResearchReadiness
    industry_research_readiness: bool
