from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

DATA_SOURCE_ERROR_CATEGORIES = (
    "authorization",
    "invalid_source_data",
    "unavailable",
)


class DataSourceError(RuntimeError):
    def __init__(self, category: str, *, detail_code: str) -> None:
        if category not in DATA_SOURCE_ERROR_CATEGORIES:
            raise ValueError("DataSource error category is invalid")
        super().__init__(category)
        self.category = category
        self.detail_code = detail_code


@dataclass(frozen=True)
class CollectionPlan:
    kind: str
    after_session: str | None = None
    overlap_start_session: str | None = None
    completed_through_date: date | None = None
    previous_canonical: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if (
            self.kind == "bootstrap"
            and self.after_session is None
            and self.previous_canonical is None
        ):
            return
        if self.kind == "incremental" and self.after_session:
            return
        if (
            self.kind == "refresh"
            and self.after_session
            and self.overlap_start_session
            and self.completed_through_date is not None
            and self.previous_canonical is not None
            and self.overlap_start_session <= self.after_session
        ):
            return
        raise ValueError("CollectionPlan state is invalid")

    @classmethod
    def bootstrap(cls) -> CollectionPlan:
        return cls(kind="bootstrap")

    @classmethod
    def incremental(
        cls,
        after_session: str,
        previous_canonical: Mapping[str, object] | None = None,
    ) -> CollectionPlan:
        return cls(
            kind="incremental",
            after_session=after_session,
            previous_canonical=previous_canonical,
        )

    @classmethod
    def refresh(
        cls,
        *,
        current_data_through: str,
        overlap_start_session: str,
        completed_through_date: date,
        previous_canonical: Mapping[str, object],
    ) -> CollectionPlan:
        return cls(
            kind="refresh",
            after_session=current_data_through,
            overlap_start_session=overlap_start_session,
            completed_through_date=completed_through_date,
            previous_canonical=previous_canonical,
        )


@dataclass(frozen=True)
class CanonicalSourceBatch:
    source_name: str
    collection_kind: str
    source_lineage: dict[str, object]
    canonical: dict[str, object]
    covered_session_range: tuple[str, str]


@dataclass(frozen=True)
class BootstrapCollectionPlan:
    as_of: datetime
    start_date: date
    completed_through_date: date


def bootstrap_collection_plan(
    as_of: datetime,
    *,
    start_date: date | None = None,
) -> BootstrapCollectionPlan:
    if as_of.tzinfo is None:
        raise ValueError("Bootstrap as-of instant must include a timezone")
    shanghai = as_of.astimezone(ZoneInfo("Asia/Shanghai"))
    local_date = shanghai.date()
    completed_through = _completed_through_date(shanghai)
    if start_date is None:
        try:
            start_date = local_date.replace(year=local_date.year - 1)
        except ValueError:
            start_date = local_date.replace(year=local_date.year - 1, day=28)
    if start_date > completed_through:
        raise ValueError("Bootstrap start date must not be after the completed market day")
    return BootstrapCollectionPlan(
        as_of=as_of,
        start_date=start_date,
        completed_through_date=completed_through,
    )


def refresh_collection_plan(
    as_of: datetime,
    previous_canonical: Mapping[str, object],
) -> CollectionPlan:
    if as_of.tzinfo is None:
        raise ValueError("Refresh as-of instant must include a timezone")
    calendar = previous_canonical.get("research_calendar")
    if not isinstance(calendar, list) or not calendar:
        raise ValueError("Refresh requires current Research Calendar")
    sessions = [str(value) for value in calendar]
    if sessions != sorted(set(sessions)):
        raise ValueError("Refresh current Research Calendar is invalid")
    shanghai = as_of.astimezone(ZoneInfo("Asia/Shanghai"))
    return CollectionPlan.refresh(
        current_data_through=sessions[-1],
        overlap_start_session=sessions[max(0, len(sessions) - 20)],
        completed_through_date=_completed_through_date(shanghai),
        previous_canonical=previous_canonical,
    )


def _completed_through_date(shanghai: datetime) -> date:
    local_date = shanghai.date()
    return local_date if shanghai.time() >= time(16) else local_date - timedelta(days=1)


class DataSource(Protocol):
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch: ...


class BootstrapDataSource(Protocol):
    def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch: ...
