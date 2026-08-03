from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CollectionPlan:
    kind: str
    after_session: str | None = None

    @classmethod
    def bootstrap(cls) -> CollectionPlan:
        return cls(kind="bootstrap")

    @classmethod
    def incremental(cls, after_session: str) -> CollectionPlan:
        return cls(kind="incremental", after_session=after_session)


@dataclass(frozen=True)
class CanonicalSourceBatch:
    source_name: str
    collection_kind: str
    source_lineage: dict[str, object]
    canonical: dict[str, object]
    covered_session_range: tuple[str, str]


class DataSource(Protocol):
    def collect(self, plan: CollectionPlan) -> CanonicalSourceBatch: ...
