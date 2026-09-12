from dataclasses import replace

from thesistrace.data.fields import alpha_field_catalog
from thesistrace.data.generation_family import (
    MountedDatasetFamilyDescriptor,
    MountedFamilyGenerationDescriptor,
)
from thesistrace.data.overview import describe_family_fields


def _generation(*, fields: tuple[str, ...], end: str = "2026-09-09"):
    return MountedFamilyGenerationDescriptor(
        manifest_sha256="a" * 64,
        data_identity="b" * 64,
        schema_contract="canonical-research",
        data_through_session="2026-09-09",
        research_sessions=("2026-09-08", "2026-09-09"),
        field_availability=fields,
        preparation={},
        families=(MountedDatasetFamilyDescriptor(
            family_id="equity.eod_price",
            schema_contract="equity-eod-price",
            dataset_coverage={"kind": "research-session-range", "start": "2026-09-08", "end": end},
            validation_summary={}, manifest_sha256="c" * 64, table_names=("eod_prices",),
        ),),
    )


def test_partial_family_reports_actual_fields_without_claiming_all_ready() -> None:
    generation = _generation(fields=("price.close.adjusted",))
    families = {family.family_id: family for family in describe_family_fields(generation)}

    market = families["equity.eod_price"]
    assert market.readiness == "partial"
    assert market.available_field_ids == ["price.close.adjusted"]
    assert len(market.supported_field_ids) == 6
    assert market.research_category == "market"
    assert families["equity.financial_pit"].readiness == "not_ready"
    assert families["equity.financial_pit"].available_field_ids == []


def test_field_availability_requires_its_family_and_preserves_lagging_coverage() -> None:
    fields = tuple(field.field_id for field in alpha_field_catalog())
    generation = _generation(fields=fields, end="2026-09-08")
    families = {family.family_id: family for family in describe_family_fields(generation)}

    assert families["equity.eod_price"].readiness == "partial"
    assert str(families["equity.eod_price"].coverage_end) == "2026-09-08"
    assert len(families["equity.eod_price"].available_field_ids) == 6
    assert families["equity.financial_pit"].available_field_ids == []
    absent = describe_family_fields(replace(generation, families=()))
    assert all(family.readiness == "not_ready" for family in absent)


def test_empty_head_has_no_available_fields() -> None:
    families = describe_family_fields(None)

    assert len(families) == 2
    assert all(family.readiness == "not_ready" for family in families)
    assert all(family.available_field_ids == [] for family in families)
