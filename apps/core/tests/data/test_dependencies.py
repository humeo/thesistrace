from thesistrace.data.dependencies import resolve_data_dependencies


def test_data_dependencies_are_derived_from_fields_and_neutralization() -> None:
    market = resolve_data_dependencies(
        field_ids={"price.close.adjusted"},
        neutralization="none",
    )
    financial = resolve_data_dependencies(
        field_ids={"financial.income.total_revenue.latest_fy"},
        neutralization="none",
    )
    industry = resolve_data_dependencies(
        field_ids={"price.close.adjusted"},
        neutralization="industry",
    )
    combined = resolve_data_dependencies(
        field_ids={"financial.income.total_revenue.latest_fy"},
        neutralization="industry",
    )

    assert market.required_families == frozenset({"equity.eod_price"})
    assert financial.required_families == frozenset({"equity.eod_price", "equity.financial_pit"})
    assert industry.required_families == frozenset(
        {"equity.eod_price", "equity.industry_membership"}
    )
    assert combined.required_families == frozenset(
        {"equity.eod_price", "equity.financial_pit", "equity.industry_membership"}
    )


def test_dependencies_keep_exact_fields_and_canonical_families() -> None:
    dependencies = resolve_data_dependencies(
        field_ids={"financial.balance_sheet.total_assets.latest_reported"},
        neutralization="industry",
    )

    assert dependencies.field_ids == frozenset({
        "financial.balance_sheet.total_assets.latest_reported",
    })
    assert dependencies.required_families == frozenset({
        "equity.eod_price", "equity.financial_pit", "equity.industry_membership",
    })


def test_dependencies_reject_unknown_canonical_fields() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown Canonical Field"):
        resolve_data_dependencies(field_ids={"financial.unknown"}, neutralization="none")


def test_dependency_coverage_checks_each_required_family_and_ignores_others() -> None:
    from datetime import date

    from thesistrace.data.models import DatasetCoverage

    dependencies = resolve_data_dependencies(
        field_ids={"price.close.adjusted"}, neutralization="industry",
    )
    coverage = {
        "equity.eod_price": DatasetCoverage(start=date(2026, 8, 3), end=date(2026, 8, 7)),
        "equity.industry_membership": DatasetCoverage(
            start=date(2026, 8, 5), end=date(2026, 8, 6),
        ),
    }
    assert dependencies.unavailable_families(
        coverage, start=date(2026, 8, 5), end=date(2026, 8, 7),
        calculation_start=date(2026, 8, 3),
    ) == frozenset({"equity.industry_membership"})
    assert dependencies.unavailable_families(
        coverage, start=date(2026, 8, 5), end=date(2026, 8, 6),
        calculation_start=date(2026, 8, 3),
    ) == frozenset()
    financial = resolve_data_dependencies(
        field_ids={"financial.income.total_revenue.latest_fy"}, neutralization="none",
    )
    assert financial.unavailable_families(
        coverage, start=date(2026, 8, 5), end=date(2026, 8, 6),
        calculation_start=date(2026, 8, 3),
    ) == frozenset({"equity.financial_pit"})


def test_dependencies_group_only_requested_fields_and_require_complete_warmup() -> None:
    from datetime import date

    from thesistrace.data.models import DatasetCoverage

    dependencies = resolve_data_dependencies(
        field_ids={"price.close.adjusted", "financial.income.total_revenue.latest_fy"},
        neutralization="none",
    )
    assert dependencies.field_ids_by_family == {
        "equity.eod_price": frozenset({"price.close.adjusted"}),
        "equity.financial_pit": frozenset({"financial.income.total_revenue.latest_fy"}),
    }
    coverage = {
        family: DatasetCoverage(start=date(2026, 8, 3), end=date(2026, 8, 5))
        for family in dependencies.required_families
    }
    assert dependencies.unavailable_for_sessions(
        coverage, calendar=("2026-08-03", "2026-08-04", "2026-08-05"),
        sessions=("2026-08-04",), lookback=2, available_field_ids=dependencies.field_ids,
    ) == dependencies.required_families
    assert dependencies.unavailable_for_sessions(
        coverage, calendar=("2026-08-03", "2026-08-04", "2026-08-05"),
        sessions=("2026-08-05",), lookback=2, available_field_ids=dependencies.field_ids,
    ) == frozenset()

    assert dependencies.unavailable_for_sessions(
        coverage, calendar=("2026-08-03", "2026-08-04", "2026-08-05"),
        sessions=("2026-08-05",), lookback=2,
        available_field_ids=frozenset({"price.close.adjusted"}),
    ) == frozenset({"equity.financial_pit"})


def test_industry_conditions_require_industry_without_neutralization() -> None:
    dependencies = resolve_data_dependencies(
        field_ids={"price.close.adjusted"},
        neutralization="none",
        require_industry=True,
    )
    assert dependencies.required_families == frozenset({
        "equity.eod_price", "equity.industry_membership",
    })
