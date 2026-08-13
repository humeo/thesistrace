from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DatasetCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date


class FinancialCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    observation_through_session: date
    reconciliation_status: str
    historical_reconciliation_watermark: date
    revision_coverage: str
    seed_policy: str
    sparse_facts: bool = True


class DataOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    market_coverage: DatasetCoverage | None
    financial_coverage: FinancialCoverage | None
    data_through_session: date | None
    last_market_refresh_at: datetime | None
    last_financial_refresh_at: datetime | None
    market_research_readiness: bool
    financial_research_readiness: bool
