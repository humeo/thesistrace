from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from thesistrace._postgres import PostgresDatabase
from thesistrace.data.financial_candidate import FinancialCandidateStore
from thesistrace.data.lifecycle import DatasetLifecycle


@dataclass(frozen=True)
class DatasetAdmissionSnapshot:
    generation_manifest_sha256: str
    data_identity: str
    coverage_start: date
    coverage_end: date
    research_sessions: tuple[date, ...]
    available_field_ids: frozenset[str]
    financial_coverage_start: date | None = None
    financial_coverage_end: date | None = None

    def research_period(self, start: date, end: date) -> tuple[date, ...]:
        if start > end:
            raise ValueError("Research Period dates are reversed")
        return tuple(session for session in self.research_sessions if start <= session <= end)


class DatasetAdmissionService:
    """Project current Data into the identity-free facts needed by Run admission."""

    def __init__(self, database: PostgresDatabase, mount_root: Path | str) -> None:
        self._lifecycle = DatasetLifecycle(database, mount_root)
        self._financial = FinancialCandidateStore(mount_root)

    def current(self) -> DatasetAdmissionSnapshot | None:
        admission = self._lifecycle.current_admission()
        if admission is None:
            return None
        sessions = tuple(
            date.fromisoformat(value) for value in admission.research_calendar
        )
        financial_start: date | None = None
        financial_end: date | None = None
        if admission.generation.financial_candidate_manifest_sha256 is not None:
            financial = self._financial.reopen(
                admission.generation.financial_candidate_manifest_sha256
            )
            financial_start = date.fromisoformat(financial.coverage_start)
            financial_end = date.fromisoformat(financial.observation_through_session)
        return DatasetAdmissionSnapshot(
            generation_manifest_sha256=admission.generation.manifest_sha256,
            data_identity=admission.generation.data_identity,
            coverage_start=sessions[0],
            coverage_end=sessions[-1],
            research_sessions=sessions,
            available_field_ids=frozenset(admission.generation.field_availability),
            financial_coverage_start=financial_start,
            financial_coverage_end=financial_end,
        )
