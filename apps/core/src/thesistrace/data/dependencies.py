from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.generation_family import MountedFamilyGenerationDescriptor
from thesistrace.data.models import DatasetCoverage


@dataclass(frozen=True)
class DataDependencies:
    field_ids: frozenset[str]
    required_families: frozenset[str]
    financial_families: frozenset[str]
    field_ids_by_family: Mapping[str, frozenset[str]]

    def unavailable_families(
        self, coverage: Mapping[str, DatasetCoverage], *, start: date, end: date,
        calculation_start: date,
    ) -> frozenset[str]:
        return frozenset(
            family_id for family_id in self.required_families
            if family_id not in coverage
            or coverage[family_id].start > (
                start if family_id == "equity.industry_membership" else calculation_start
            )
            or coverage[family_id].end < end
        )


    def unavailable_for_sessions(
        self, coverage: Mapping[str, DatasetCoverage], *, calendar: Sequence[str],
        sessions: Sequence[str], lookback: int, available_field_ids: frozenset[str],
    ) -> frozenset[str]:
        missing_fields = frozenset(
            family_id for family_id, field_ids in self.field_ids_by_family.items()
            if not field_ids <= available_field_ids
        )
        first_index = calendar.index(sessions[0])
        unavailable = self.unavailable_families(
            coverage, start=date.fromisoformat(sessions[0]), end=date.fromisoformat(sessions[-1]),
            calculation_start=date.fromisoformat(calendar[max(0, first_index - lookback)]),
        )
        unavailable |= missing_fields
        if first_index < lookback:
            return unavailable | (self.required_families - {"equity.industry_membership"})
        return unavailable


def resolve_data_dependencies(
    *,
    field_ids: set[str] | frozenset[str],
    neutralization: str,
) -> DataDependencies:
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization is invalid")
    fields = {field.field_id: field for field in alpha_field_catalog()}
    unknown = field_ids - fields.keys()
    if unknown:
        raise ValueError(f"unknown Canonical Field: {', '.join(sorted(unknown))}")
    selected = tuple(fields[field_id] for field_id in sorted(field_ids))
    return DataDependencies(
        field_ids=frozenset(field_ids),
        required_families=frozenset({
            "equity.eod_price",
            *(field.family_id for field in selected),
            *({"equity.industry_membership"} if neutralization == "industry" else set()),
        }),
        field_ids_by_family={
            family_id: frozenset(
                field.field_id for field in selected if field.family_id == family_id
            )
            for family_id in dict.fromkeys(field.family_id for field in selected)
        },
        financial_families=frozenset(
            field.family_id for field in selected if field.research_category == "financial"
        ),
    )


__all__ = ("DataDependencies", "resolve_data_dependencies")


def generation_family_coverage(
    generation: MountedFamilyGenerationDescriptor,
) -> dict[str, DatasetCoverage]:
    required = {field.family_id for field in alpha_field_catalog()} | {
        "equity.industry_membership",
    }
    end_keys = {
        "research-session-range": "end",
        "membership-range": "end",
        "financial-observation-range": "observation_through_session",
        "financial-announcement-observation-range": "discovery_attempted_through_session",
    }
    result = {}
    for family in generation.families:
        if family.family_id not in required:
            continue
        coverage = family.dataset_coverage
        end_key = end_keys.get(str(coverage["kind"]))
        if end_key is None:
            raise ValueError(f"Unsupported research coverage for {family.family_id}")
        result[family.family_id] = DatasetCoverage(
            start=date.fromisoformat(str(coverage["start"])),
            end=date.fromisoformat(str(coverage[end_key])),
        )
    return result
