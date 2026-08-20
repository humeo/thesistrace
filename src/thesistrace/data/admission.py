from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.generation_store import MountedGenerationStore
from thesistrace.data.lifecycle import DatasetLifecycle

type MaximumUniverseCardinality = Callable[[str, date, date], int]


class DatasetWarmupUnavailable(ValueError):
    """The selected Research Period cannot provide its complete lookback window."""


@dataclass(frozen=True)
class DatasetAdmissionSnapshot:
    generation_manifest_sha256: str
    data_through_session: date
    coverage_start: date
    coverage_end: date
    research_sessions: tuple[date, ...]
    available_field_ids: frozenset[str]
    maximum_universe_cardinality: MaximumUniverseCardinality
    financial_coverage_start: date | None = None
    financial_coverage_end: date | None = None
    industry_coverage_start: date | None = None
    industry_coverage_end: date | None = None

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
        if start_index < lookback:
            raise DatasetWarmupUnavailable(
                f"Research Period requires {lookback} sessions before {start.isoformat()}"
            )
        calculation_sessions = self.research_sessions[
            start_index - lookback : end_index + 1
        ]
        instrument_count = self.maximum_universe_cardinality(
            universe,
            calculation_sessions[0],
            calculation_sessions[-1],
        )
        return len(calculation_sessions), instrument_count


class DatasetAdmissionService:
    """Project current Data into the facts needed by Run admission."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._generations = MountedGenerationStore(mount_root)

    def current(self) -> DatasetAdmissionSnapshot | None:
        admission = self._lifecycle.current_admission()
        if admission is None:
            return None
        sessions = tuple(date.fromisoformat(value) for value in admission.research_calendar)
        financial_start: date | None = None
        if admission.financial_observation_through_session is not None:
            financial_family = next(
                family
                for family in admission.generation.families
                if family.family_id == "equity.financial_pit"
            )
            financial_start = date.fromisoformat(str(financial_family.dataset_coverage["start"]))
        industry_family = next(
            (
                family
                for family in admission.generation.families
                if family.family_id == "equity.industry_membership"
            ),
            None,
        )
        return DatasetAdmissionSnapshot(
            generation_manifest_sha256=admission.generation.manifest_sha256,
            data_through_session=date.fromisoformat(
                admission.generation.data_through_session
            ),
            coverage_start=sessions[0],
            coverage_end=sessions[-1],
            research_sessions=sessions,
            available_field_ids=frozenset(admission.generation.field_availability),
            maximum_universe_cardinality=lambda universe, start, end: (
                self._generations.maximum_universe_cardinality(
                    admission.generation.manifest_sha256,
                    universe=universe,
                    start_session=start.isoformat(),
                    end_session=end.isoformat(),
                )
            ),
            financial_coverage_start=financial_start,
            financial_coverage_end=(
                None
                if admission.financial_observation_through_session is None
                else date.fromisoformat(admission.financial_observation_through_session)
            ),
            industry_coverage_start=(
                None
                if industry_family is None
                else date.fromisoformat(str(industry_family.dataset_coverage["start"]))
            ),
            industry_coverage_end=(
                None
                if industry_family is None
                else date.fromisoformat(str(industry_family.dataset_coverage["end"]))
            ),
        )
