from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DatasetCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date


class DataOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_coverage: DatasetCoverage | None
    data_through_session: date | None
    last_refresh_at: datetime | None
    readiness: bool
