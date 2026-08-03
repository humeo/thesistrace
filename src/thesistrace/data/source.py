from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

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


class DataSource(Protocol):
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch: ...
