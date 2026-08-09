from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.lifecycle import DatasetLifecycle


@dataclass(frozen=True)
class DatasetAdmissionSnapshot:
    coverage_start: date
    coverage_end: date
    research_sessions: tuple[date, ...]
    available_field_ids: frozenset[str]

    def research_period(self, start: date, end: date) -> tuple[date, ...]:
        if start > end:
            raise ValueError("Research Period dates are reversed")
        return tuple(session for session in self.research_sessions if start <= session <= end)


class DatasetAdmissionService:
    """Project current Data into the identity-free facts needed by Run admission."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._lifecycle = DatasetLifecycle(database, mount_root)

    def current(self) -> DatasetAdmissionSnapshot | None:
        head = self._lifecycle.current_head()
        if head is None:
            return None
        calendar = head.generation.canonical["research_calendar"]
        assert isinstance(calendar, list)
        sessions = tuple(date.fromisoformat(str(value)) for value in calendar)
        return DatasetAdmissionSnapshot(
            coverage_start=sessions[0],
            coverage_end=sessions[-1],
            research_sessions=sessions,
            available_field_ids=frozenset(head.generation.field_availability),
        )
