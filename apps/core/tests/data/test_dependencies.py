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

    assert market.required_families == frozenset({"market"})
    assert financial.required_families == frozenset({"market", "financial"})
    assert industry.required_families == frozenset({"market", "industry"})
    assert combined.required_families == frozenset(
        {"market", "financial", "industry"}
    )


def test_industry_conditions_require_industry_without_neutralization() -> None:
    dependencies = resolve_data_dependencies(
        field_ids={"price.close.adjusted"},
        neutralization="none",
        require_industry=True,
    )
    assert dependencies.required_families == frozenset({"market", "industry"})
