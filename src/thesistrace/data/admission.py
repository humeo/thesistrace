from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.lifecycle import DatasetLifecycle

type UniverseInstrumentCounter = Callable[[str, date, date], int]


@dataclass(frozen=True)
class DatasetAdmissionSnapshot:
    coverage_start: date
    coverage_end: date
    research_sessions: tuple[date, ...]
    available_field_ids: frozenset[str]
    count_universe_instruments: UniverseInstrumentCounter

    def research_period(self, start: date, end: date) -> tuple[date, ...]:
        if start > end:
            raise ValueError("Research Period dates are reversed")
        return tuple(session for session in self.research_sessions if start <= session <= end)

    def calculation_shape(
        self,
        *,
        start: date,
        end: date,
        lookback: int,
        universe: str,
    ) -> tuple[int, int]:
        start_index = self.research_sessions.index(start)
        end_index = self.research_sessions.index(end)
        calculation_sessions = self.research_sessions[
            max(0, start_index - lookback) : end_index + 1
        ]
        instrument_count = self.count_universe_instruments(
            universe,
            calculation_sessions[0],
            calculation_sessions[-1],
        )
        return len(calculation_sessions), instrument_count


class DatasetAdmissionService:
    """Project current Data into the identity-free facts needed by Run admission."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._generations = MountedGenerationStore(mount_root)

    def current(self) -> DatasetAdmissionSnapshot | None:
        admission = self._lifecycle.current_admission()
        if admission is None:
            return None
        sessions = tuple(date.fromisoformat(value) for value in admission.research_calendar)
        return DatasetAdmissionSnapshot(
            coverage_start=sessions[0],
            coverage_end=sessions[-1],
            research_sessions=sessions,
            available_field_ids=frozenset(admission.generation.field_availability),
            count_universe_instruments=lambda universe, start, end: (
                self._generations.count_universe_instruments(
                    admission.generation.manifest_sha256,
                    universe=universe,
                    start_session=start.isoformat(),
                    end_session=end.isoformat(),
                )
            ),
        )
