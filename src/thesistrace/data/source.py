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


def bootstrap_collection_plan(as_of: datetime) -> BootstrapCollectionPlan:
    if as_of.tzinfo is None:
        raise ValueError("Bootstrap as-of instant must include a timezone")
    shanghai = as_of.astimezone(ZoneInfo("Asia/Shanghai"))
    local_date = shanghai.date()
    try:
        start_date = local_date.replace(year=local_date.year - 1)
    except ValueError:
        start_date = local_date.replace(year=local_date.year - 1, day=28)
    completed_through = (
        local_date if shanghai.time() >= time(16) else local_date - timedelta(days=1)
    )
    return BootstrapCollectionPlan(
        as_of=as_of,
        start_date=start_date,
        completed_through_date=completed_through,
    )


class DataSource(Protocol):
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch: ...


class BootstrapDataSource(Protocol):
    def collect_bootstrap(self, plan: BootstrapCollectionPlan) -> CanonicalSourceBatch: ...
