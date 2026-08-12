from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class FamilyManifestError(ValueError):
    pass


class CoverageContract(Protocol):
    kind: str

    def build(
        self,
        canonical: Mapping[str, object],
        calendar: list[object],
    ) -> dict[str, object]: ...

    def validate(self, coverage: Mapping[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True)
class ResearchSessionRangeCoverage:
    kind: str = "research-session-range"

    def build(
        self,
        canonical: Mapping[str, object],
        calendar: list[object],
    ) -> dict[str, object]:
        del canonical
        return {
            "kind": self.kind,
            "start": str(calendar[0]),
            "end": str(calendar[-1]),
            "session_count": len(calendar),
        }

    def validate(self, coverage: Mapping[str, object]) -> dict[str, object]:
        return _validated_range_coverage(coverage, self.kind, "session_count")


@dataclass(frozen=True)
class InstrumentSetCoverage:
    kind: str = "instrument-set"

    def build(
        self,
        canonical: Mapping[str, object],
        calendar: list[object],
    ) -> dict[str, object]:
        del calendar
        return {
            "kind": self.kind,
            "instrument_count": _row_count(canonical, "instruments"),
        }

    def validate(self, coverage: Mapping[str, object]) -> dict[str, object]:
        return _validated_count_coverage(coverage, self.kind, "instrument_count")


@dataclass(frozen=True)
class MembershipRangeCoverage:
    kind: str = "membership-range"

    def build(
        self,
        canonical: Mapping[str, object],
        calendar: list[object],
    ) -> dict[str, object]:
        return {
            "kind": self.kind,
            "start": str(calendar[0]),
            "end": str(calendar[-1]),
            "membership_count": _row_count(canonical, "industry_membership"),
        }

    def validate(self, coverage: Mapping[str, object]) -> dict[str, object]:
        return _validated_range_coverage(coverage, self.kind, "membership_count")


@dataclass(frozen=True)
class FieldSetCoverage:
    kind: str = "field-set"

    def build(
        self,
        canonical: Mapping[str, object],
        calendar: list[object],
    ) -> dict[str, object]:
        del calendar
        return {
            "kind": self.kind,
            "field_count": _row_count(canonical, "field_catalog"),
        }

    def validate(self, coverage: Mapping[str, object]) -> dict[str, object]:
        return _validated_count_coverage(coverage, self.kind, "field_count")


@dataclass(frozen=True)
class DatasetFamilySpec:
    family_id: str
    schema_contract: str
    table_names: tuple[str, ...]
    coverage: CoverageContract


@dataclass(frozen=True)
class MountedDatasetFamilyDescriptor:
    family_id: str
    schema_contract: str
    dataset_coverage: dict[str, object]
    validation_summary: dict[str, int | str]
    manifest_sha256: str
    table_names: tuple[str, ...]


@dataclass(frozen=True)
class MountedFamilyGenerationDescriptor:
    manifest_sha256: str
    data_identity: str
    schema_contract: str
    data_through_session: str
    field_availability: tuple[str, ...]
    preparation: dict[str, str]
    families: tuple[MountedDatasetFamilyDescriptor, ...]


_SESSION_COVERAGE = ResearchSessionRangeCoverage()
MARKET_FAMILY_SPECS = (
    DatasetFamilySpec(
        "market.research_calendar",
        "research-calendar",
        ("research_calendar",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "market.instrument_identity",
        "instrument-identity",
        ("instruments",),
        InstrumentSetCoverage(),
    ),
    DatasetFamilySpec(
        "equity.eod_price",
        "equity-eod-price",
        ("eod_prices",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "equity.adjustment_factor",
        "equity-adjustment-factor",
        ("adjustment_factors",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "equity.trading_state",
        "equity-trading-state",
        ("trading_states",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "equity.price_limit",
        "equity-price-limit",
        ("price_limits",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "equity.base_pool",
        "equity-base-pool",
        ("base_pool",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "equity.liquidity_universe",
        "equity-liquidity-universe",
        ("liquidity_universes",),
        _SESSION_COVERAGE,
    ),
    DatasetFamilySpec(
        "equity.industry_membership",
        "equity-industry-membership",
        ("industry_membership",),
        MembershipRangeCoverage(),
    ),
    DatasetFamilySpec(
        "data.field_catalog",
        "field-catalog",
        ("field_catalog",),
        FieldSetCoverage(),
    ),
)


def build_family_coverage(
    family_spec: DatasetFamilySpec,
    *,
    canonical: Mapping[str, object],
    calendar: list[object],
) -> dict[str, object]:
    return family_spec.coverage.build(canonical, calendar)


def validate_family_coverage(
    family_spec: DatasetFamilySpec,
    coverage: Mapping[str, object],
) -> dict[str, object]:
    return family_spec.coverage.validate(coverage)


def validation_summary(
    table_references: list[Mapping[str, object]],
) -> dict[str, int | str]:
    return {
        "status": "validated",
        "table_count": len(table_references),
        "row_count": sum(_positive_or_zero(ref.get("row_count")) for ref in table_references),
        "object_count": sum(_positive_or_zero(ref.get("object_count")) for ref in table_references),
    }


def validate_summary(
    summary: object,
    table_references: list[Mapping[str, object]],
) -> dict[str, int | str]:
    expected = validation_summary(table_references)
    if summary != expected:
        raise FamilyManifestError("Dataset Family validation summary is incompatible")
    return expected


def validate_preparation(preparation: object) -> dict[str, str]:
    if not isinstance(preparation, Mapping) or set(preparation) != {
        "prepared_at",
        "source_name",
        "source_lineage_sha256",
    }:
        raise FamilyManifestError("Family Generation preparation is incompatible")
    try:
        prepared_at = datetime.fromisoformat(str(preparation["prepared_at"]))
    except (TypeError, ValueError) as error:
        raise FamilyManifestError("Family Generation preparation is incompatible") from error
    source_name = preparation["source_name"]
    source_lineage_sha256 = preparation["source_lineage_sha256"]
    if (
        prepared_at.tzinfo is None
        or not isinstance(source_name, str)
        or not source_name.strip()
        or not _is_sha256(source_lineage_sha256)
    ):
        raise FamilyManifestError("Family Generation preparation is incompatible")
    return {
        "prepared_at": str(preparation["prepared_at"]),
        "source_name": source_name,
        "source_lineage_sha256": str(source_lineage_sha256),
    }


def validate_synchronized_coverages(
    families: tuple[MountedDatasetFamilyDescriptor, ...],
    *,
    data_through_session: str,
) -> None:
    calendar = families[0].dataset_coverage
    if (
        calendar.get("kind") != _SESSION_COVERAGE.kind
        or calendar.get("end") != data_through_session
    ):
        raise FamilyManifestError("Family Generation calendar projection is incompatible")
    expected_range = {
        "kind": calendar["kind"],
        "start": calendar["start"],
        "end": calendar["end"],
        "session_count": calendar["session_count"],
    }
    for family, spec in zip(families, MARKET_FAMILY_SPECS, strict=True):
        if isinstance(spec.coverage, ResearchSessionRangeCoverage) and (
            family.dataset_coverage != expected_range
        ):
            raise FamilyManifestError("Dataset Family session Coverage is not synchronized")
        if isinstance(spec.coverage, MembershipRangeCoverage) and (
            family.dataset_coverage["start"] != calendar["start"]
            or family.dataset_coverage["end"] != calendar["end"]
        ):
            raise FamilyManifestError("Dataset Family membership Coverage is not synchronized")


def _validated_count_coverage(
    coverage: Mapping[str, object],
    kind: str,
    count_key: str,
) -> dict[str, object]:
    count = coverage.get(count_key)
    if (
        set(coverage) != {"kind", count_key}
        or coverage.get("kind") != kind
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
    ):
        raise FamilyManifestError("Dataset Family Coverage is incompatible")
    return dict(coverage)


def _validated_range_coverage(
    coverage: Mapping[str, object],
    kind: str,
    count_key: str,
) -> dict[str, object]:
    count = coverage.get(count_key)
    if (
        set(coverage) != {"kind", "start", "end", count_key}
        or coverage.get("kind") != kind
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
    ):
        raise FamilyManifestError("Dataset Family Coverage is incompatible")
    try:
        start = date.fromisoformat(str(coverage["start"]))
        end = date.fromisoformat(str(coverage["end"]))
    except (TypeError, ValueError) as error:
        raise FamilyManifestError("Dataset Family Coverage is invalid") from error
    if start > end:
        raise FamilyManifestError("Dataset Family Coverage is invalid")
    return dict(coverage)


def _row_count(canonical: Mapping[str, object], table_name: str) -> int:
    rows = canonical.get(table_name)
    if not isinstance(rows, list) or not rows:
        raise FamilyManifestError("Dataset Family source rows are incompatible")
    return len(rows)


def _positive_or_zero(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FamilyManifestError("Dataset Family validation summary is incompatible")
    return value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = (
    "DatasetFamilySpec",
    "FamilyManifestError",
    "MARKET_FAMILY_SPECS",
    "MountedDatasetFamilyDescriptor",
    "MountedFamilyGenerationDescriptor",
    "build_family_coverage",
    "validate_family_coverage",
    "validate_preparation",
    "validate_summary",
    "validate_synchronized_coverages",
    "validation_summary",
)
