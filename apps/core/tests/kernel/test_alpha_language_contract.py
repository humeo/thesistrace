from __future__ import annotations

import math
from dataclasses import replace
from time import perf_counter

import pytest

from thesistrace.alpha_language import (
    AlphaLanguage,
    AlphaLanguageCatalogError,
    FormulaCompilationError,
    ValueType,
    alpha_language,
)
from thesistrace.data import AlphaFieldCapability, FieldDefinition, alpha_field_catalog
from thesistrace.research_kernel.alpha_builtins import (
    BUILTIN_DEFINITIONS,
    BuiltinWorkDefinition,
)


def test_catalog_composes_only_capable_fields_and_public_builtins() -> None:
    catalog = alpha_language.catalog().model_dump(mode="json")

    assert catalog["fields"] == [
        {
            "identifier": field.alpha.identifier,
            "field_id": field.field_id,
            "value_type": "numeric_series",
            "description": field.description,
            "unit": field.unit,
            "family_id": field.family_id,
            "research_category": field.research_category,
            "display_name": field.display_name,
            "research_purpose": field.research_purpose,
            "source_unit": field.source_unit,
            "source_endpoint": field.source_endpoint,
            "source_column": field.source_column,
            "source_lineage": field.source_lineage,
            "reporting_scope": field.reporting_scope,
            "availability": field.availability,
            "report_period_selection": field.report_period_selection,
            "applicable_company_types": list(field.applicable_company_types),
            "missingness": field.missingness,
            "example": field.authoring_example,
        }
        for field in alpha_field_catalog()
        if field.alpha is not None
    ]
    assert [builtin["identifier"] for builtin in catalog["builtins"]] == [
        "universe_return",
        "universe_advancing_fraction",
        "industry_return",
        "industry_advancing_fraction",
        "if_else",
        "abs",
        "log",
        "sign",
        "rank",
        "lag",
        "delta",
        "pct_change",
        "ts_mean",
        "ts_sum",
        "ts_std",
        "ts_min",
        "ts_max",
    ]
    assert "release" not in str(catalog).lower()
    assert "evaluator" not in str(catalog).lower()
    for builtin in catalog["builtins"]:
        assert builtin["missing_value_behavior"]
        assert builtin["numeric_behavior"]
        assert builtin["work_estimate"]["base_operations"] >= 1
    ts_mean = next(builtin for builtin in catalog["builtins"] if builtin["identifier"] == "ts_mean")
    assert ts_mean["work_estimate"] == {
        "base_operations": 1,
        "per_window_operations": 1,
    }


def test_catalog_rejects_cross_catalog_identifier_collisions() -> None:
    conflicting_field = FieldDefinition(
        field_id="test.abs",
        family_id="test.family",
        description="conflicting test field",
        unit="count",
        physical_type="float64",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_source_absent",
        alpha=AlphaFieldCapability(identifier="abs", value_type="numeric_series"),
        alpha_series_reader=lambda _rows: (),
    )

    with pytest.raises(AlphaLanguageCatalogError, match="duplicate Alpha identifier: abs"):
        AlphaLanguage(fields=(*alpha_field_catalog(), conflicting_field))


def test_catalog_rejects_invalid_identifiers_and_ignores_internal_fields() -> None:
    internal = FieldDefinition(
        field_id="test.internal",
        family_id="test.family",
        description="internal test field",
        unit="count",
        physical_type="int64",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="never",
    )
    invalid = FieldDefinition(
        field_id="test.invalid",
        family_id="test.family",
        description="invalid test field",
        unit="count",
        physical_type="int64",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="never",
        alpha=AlphaFieldCapability(identifier="Not_Snake_Case"),
        alpha_series_reader=lambda _rows: (),
    )

    catalog = AlphaLanguage(fields=(*alpha_field_catalog(), internal)).catalog()
    assert "test.internal" not in {field.field_id for field in catalog.fields}
    with pytest.raises(AlphaLanguageCatalogError, match="invalid Alpha identifier"):
        AlphaLanguage(fields=(*alpha_field_catalog(), invalid))


def test_catalog_rejects_capable_field_without_data_series_reader() -> None:
    missing_reader = FieldDefinition(
        field_id="test.missing_reader",
        family_id="test.family",
        description="invalid test field",
        unit="count",
        physical_type="int64",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="never",
        alpha=AlphaFieldCapability(identifier="missing_reader"),
    )

    with pytest.raises(AlphaLanguageCatalogError, match="no Data Series reader"):
        AlphaLanguage(fields=(*alpha_field_catalog(), missing_reader))


def test_alpha_fields_own_their_canonical_series_readers() -> None:
    rows = [
        {"close_adj": "10.5", "turnover_cny": "200"},
        None,
    ]
    fields = {
        field.alpha.identifier: field for field in alpha_field_catalog() if field.alpha is not None
    }

    close_reader = fields["close"].alpha_series_reader
    turnover_reader = fields["amount"].alpha_series_reader
    assert close_reader is not None
    assert turnover_reader is not None
    assert close_reader(rows) == (10.5, None)
    assert turnover_reader(rows) == (200.0, None)


@pytest.mark.parametrize(
    ("source", "expression"),
    [
        (
            "close",
            {"kind": "field", "field_id": "price.close.adjusted"},
        ),
        (
            "ts_mean(close, 20)",
            {
                "kind": "call",
                "identifier": "ts_mean",
                "arguments": [
                    {"kind": "field", "field_id": "price.close.adjusted"},
                    {"kind": "number", "value": 20},
                ],
            },
        ),
        (
            "-(close + 2) / ts_std(volume, 5)",
            {
                "kind": "binary",
                "operator": "divide",
                "left": {
                    "kind": "unary",
                    "operator": "negate",
                    "operand": {
                        "kind": "binary",
                        "operator": "add",
                        "left": {"kind": "field", "field_id": "price.close.adjusted"},
                        "right": {"kind": "number", "value": 2},
                    },
                },
                "right": {
                    "kind": "call",
                    "identifier": "ts_std",
                    "arguments": [
                        {"kind": "field", "field_id": "market.volume.shares"},
                        {"kind": "number", "value": 5},
                    ],
                },
            },
        ),
    ],
)
def test_compile_accepts_the_documented_expression_language(
    source: str,
    expression: dict[str, object],
) -> None:
    compiled = alpha_language.compile(source)

    assert compiled.expression == expression
    assert compiled.result_type is ValueType.NUMERIC_SERIES
    assert compiled.effective_lookback <= 252
    assert compiled.field_ids_by_identifier


def test_market_identifiers_map_without_legacy_storage_aliases() -> None:
    current = {
        "open": "price.open.adjusted",
        "high": "price.high.adjusted",
        "low": "price.low.adjusted",
        "close": "price.close.adjusted",
        "volume": "market.volume.shares",
        "amount": "market.turnover.cny",
    }
    for identifier, field_id in current.items():
        compiled = alpha_language.compile(identifier)
        assert compiled.field_ids_by_identifier == {identifier: field_id}

    for legacy in (
        "open_adj",
        "high_adj",
        "low_adj",
        "close_adj",
        "volume_shares",
        "turnover_amount_cny",
    ):
        diagnostic = alpha_language.diagnose(legacy).diagnostics[0]
        assert diagnostic.code == "UNKNOWN_IDENTIFIER"


def test_financial_identifiers_hide_selection_policy_and_reject_obsolete_names() -> None:
    current = {
        "revenue": "financial.income.total_revenue.latest_fy",
        "net_profit": "financial.income.net_profit_parent.latest_fy",
        "operating_cash_flow": "financial.cashflow.operating_cash_flow.latest_fy",
        "assets": "financial.balance_sheet.total_assets.latest_reported",
        "liabilities": "financial.balance_sheet.total_liabilities.latest_reported",
        "equity": "financial.balance_sheet.equity_parent.latest_reported",
    }
    for identifier, field_id in current.items():
        compiled = alpha_language.compile(identifier)
        assert compiled.field_ids_by_identifier == {identifier: field_id}

    for obsolete in (
        "total_revenue_latest_fy",
        "net_profit_parent_latest_fy",
        "operating_cash_flow_latest_fy",
        "total_assets_latest_reported",
        "total_liabilities_latest_reported",
        "equity_parent_latest_reported",
    ):
        diagnostic = alpha_language.diagnose(obsolete).diagnostics[0]
        assert diagnostic.code == "UNKNOWN_IDENTIFIER"


def test_compile_maps_financial_identifier_to_namespaced_field_reference() -> None:
    compiled = alpha_language.compile("rank(close) + rank(revenue)")

    assert compiled.field_ids_by_identifier == {
        "close": "price.close.adjusted",
        "revenue": "financial.income.total_revenue.latest_fy",
    }
    assert compiled.expression == {
        "kind": "binary",
        "operator": "add",
        "left": {
            "kind": "call",
            "identifier": "rank",
            "arguments": [{"kind": "field", "field_id": "price.close.adjusted"}],
        },
        "right": {
            "kind": "call",
            "identifier": "rank",
            "arguments": [
                {
                    "kind": "field",
                    "field_id": "financial.income.total_revenue.latest_fy",
                }
            ],
        },
    }


def test_compile_estimates_builtin_work_from_its_definition() -> None:
    short = alpha_language.compile("ts_mean(close, 2)")
    long = alpha_language.compile("ts_mean(close, 20)")

    assert short.estimated_work == 5
    assert long.estimated_work == 23
    assert long.estimated_work > long.node_count


def test_research_kernel_builtin_definitions_own_their_evaluators() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}

    assert builtins["abs"].evaluator(((-2.0, None, 3.0),)) == (2.0, None, 3.0)
    assert builtins["ts_mean"].evaluator(((1.0, 2.0, None, 4.0), 2)) == (
        None,
        1.5,
        None,
        None,
    )


def test_builtin_evaluators_strictly_propagate_non_finite_values() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    invalid = (math.nan, math.inf, -math.inf, 2.0)

    assert builtins["sign"].evaluator((invalid,)) == (None, None, None, 1.0)
    assert builtins["lag"].evaluator((invalid, 1)) == (None, None, None, None)
    with pytest.raises(TypeError, match="complete cross-section"):
        builtins["rank"].evaluator((invalid,))
    for builtin in (
        item
        for name, item in builtins.items()
        if name != "rank" and item.result_rule != "common_series"
    ):
        arguments = (
            (invalid, invalid, invalid)
            if builtin.identifier == "if_else"
            else (invalid,)
            if len(builtin.parameters) == 1
            else (invalid, 1)
        )
        result = builtin.evaluator(arguments)
        assert isinstance(result, tuple)
        assert all(value is None or math.isfinite(value) for value in result)


def test_rolling_builtin_evaluators_are_linear_for_large_windows() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    series = tuple(float(index % 97) for index in range(20_000))

    started = perf_counter()
    for identifier in ("ts_sum", "ts_mean", "ts_std", "ts_min", "ts_max"):
        result = builtins[identifier].evaluator((series, 10_000))
        assert isinstance(result, tuple)
        assert len(result) == len(series)
    elapsed = perf_counter() - started

    assert elapsed < 2.0


def test_rolling_sum_and_mean_do_not_rebuild_a_descending_window() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    series = tuple(float(20_000 - index) for index in range(20_000))

    started = perf_counter()
    for identifier in ("ts_sum", "ts_mean"):
        result = builtins[identifier].evaluator((series, 10_000))
        assert isinstance(result, tuple)
        assert len(result) == len(series)
        assert result[-1] is not None
    elapsed = perf_counter() - started

    assert elapsed < 2.0


def test_rolling_totals_recover_after_a_finite_overflow_window_expires() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    series = (1e308, 1e308, -1e308, 1.0, 1.0)

    assert builtins["ts_sum"].evaluator((series, 2)) == (
        None,
        None,
        0.0,
        -1e308,
        2.0,
    )
    assert builtins["ts_mean"].evaluator((series, 2)) == (
        None,
        1e308,
        0.0,
        -5e307,
        1.0,
    )


def test_rolling_totals_preserve_small_values_after_a_large_value_expires() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    series = (1e308, 1e-100, 1e-100)

    assert builtins["ts_sum"].evaluator((series, 2))[-1] == 2e-100
    assert builtins["ts_mean"].evaluator((series, 2))[-1] == 1e-100


def test_rolling_population_std_is_stable_for_large_finite_bases() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    std = builtins["ts_std"]

    assert std.evaluator(((1e16, 1e16 + 2.0), 2)) == (None, 1.0)
    assert std.evaluator(((1e200, 1e200), 2)) == (None, 0.0)
    assert std.evaluator(((1e308, 1e308, 1.0, 1.0), 2))[-1] == 0.0


def test_one_pass_rolling_matches_fixed_binary64_window_references() -> None:
    builtins = {builtin.identifier: builtin for builtin in BUILTIN_DEFINITIONS}
    series = (1e12, -3.0, 7.0, 9.0, -2.0, 4.0, 11.0)
    window = 4

    expected_sum: list[float | None] = []
    expected_std: list[float | None] = []
    for end in range(1, len(series) + 1):
        values = series[max(0, end - window) : end]
        if len(values) < window:
            expected_sum.append(None)
            expected_std.append(None)
            continue
        total = math.fsum(values)
        mean = total / window
        expected_sum.append(total)
        expected_std.append(math.sqrt(math.fsum((value - mean) ** 2 for value in values) / window))

    assert builtins["ts_sum"].evaluator((series, window)) == pytest.approx(expected_sum)
    assert builtins["ts_std"].evaluator((series, window)) == pytest.approx(expected_std)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("cs_rank(close)", "UNKNOWN_IDENTIFIER"),
        ("value = close", "SYNTAX_ERROR"),
        ("close; volume", "SYNTAX_ERROR"),
        ("close.real", "UNSUPPORTED_SYNTAX"),
        ("close[0]", "UNSUPPORTED_SYNTAX"),
        ("[close]", "UNSUPPORTED_SYNTAX"),
        ("{close}", "UNSUPPORTED_SYNTAX"),
        ("(x for x in [close])", "UNSUPPORTED_SYNTAX"),
        ("lambda: close", "UNSUPPORTED_SYNTAX"),
        ("close if 1 else volume", "UNSUPPORTED_SYNTAX"),
        ("close > volume", "ROOT_MUST_BE_SERIES"),
        ("ts_mean(series=close, window=20)", "KEYWORD_ARGUMENT_NOT_ALLOWED"),
        ("ts_mean(*(close, 20))", "STARRED_ARGUMENT_NOT_ALLOWED"),
        ("+close", "UNSUPPORTED_OPERATOR"),
        ("close ** 2", "UNSUPPORTED_OPERATOR"),
        ("True", "BOOLEAN_NOT_ALLOWED"),
        ("1e309 + close", "NON_FINITE_LITERAL"),
    ],
)
def test_compile_rejects_every_non_allowlisted_language_form(source: str, code: str) -> None:
    diagnostics = alpha_language.diagnose(source)

    assert diagnostics.valid is False
    assert diagnostics.diagnostics[0].code == code
    assert diagnostics.diagnostics[0].details is not None
    with pytest.raises(FormulaCompilationError):
        alpha_language.compile(source)


@pytest.mark.parametrize(
    ("source", "code", "start_offset", "end_offset"),
    [
        ("closes + 1", "UNKNOWN_IDENTIFIER", 0, 6),
        ("close(1)", "NOT_CALLABLE", 0, 5),
        ("ts_mean", "EXPECTED_FIELD", 0, 7),
        ("ts_mean(close)", "INVALID_ARITY", 0, 14),
        ("ts_mean(close, 0)", "WINDOW_OUT_OF_RANGE", 15, 16),
        ("ts_mean(close, 2.5)", "WINDOW_MUST_BE_INTEGER", 15, 18),
        ("abs(close, 2)", "INVALID_ARITY", 0, 13),
        ("20", "ROOT_MUST_BE_SERIES", 0, 2),
    ],
)
def test_diagnostics_are_stable_and_source_ranged(
    source: str,
    code: str,
    start_offset: int,
    end_offset: int,
) -> None:
    outcome = alpha_language.diagnose(source)

    assert outcome.valid is False
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.severity == "error"
    assert diagnostic.message
    assert diagnostic.range.start.offset == start_offset
    assert diagnostic.range.end.offset == end_offset
    assert diagnostic.range.start.line == 1
    assert diagnostic.range.end.line == 1


def test_incomplete_formula_diagnostic_points_to_end_of_source() -> None:
    source = "close +"

    diagnostic = alpha_language.diagnose(source).diagnostics[0]

    assert diagnostic.code == "SYNTAX_ERROR"
    assert diagnostic.range.start.offset == len(source)
    assert diagnostic.range.end.offset == len(source)
    assert diagnostic.range.start.line == 1
    assert diagnostic.range.start.column == 8
    assert diagnostic.details is not None
    assert diagnostic.details.model_dump(mode="json") == {
        "kind": "syntax",
        "expected": "one_complete_expression",
        "actual": "incomplete_expression",
    }


def test_relevant_diagnostics_include_typed_expected_and_actual_details() -> None:
    arity = alpha_language.diagnose("ts_mean(close)").diagnostics[0]
    value_type = alpha_language.diagnose("ts_mean(1, 2)").diagnostics[0]
    window = alpha_language.diagnose("ts_mean(close, 0)").diagnostics[0]

    assert arity.details is not None
    assert arity.details.model_dump(mode="json") == {
        "kind": "arity",
        "expected": 2,
        "actual": 1,
    }
    assert value_type.details is not None
    assert value_type.details.model_dump(mode="json") == {
        "kind": "value_type",
        "expected": ["numeric_series", "common_numeric_series"],
        "actual": "number",
    }
    assert window.details is not None
    assert window.details.model_dump(mode="json") == {
        "kind": "window",
        "expected": [1, 252],
        "actual": "0",
    }


@pytest.mark.parametrize(
    ("source", "code", "kind", "expected", "actual", "start", "end"),
    [
        ("not close", "TYPE_MISMATCH", "value_type",
         ["boolean", "boolean_series", "common_boolean_series"], "numeric_series", 0, 9),
        ("close + (close > open)", "TYPE_MISMATCH", "value_type",
         ["common_numeric_series", "number", "numeric_series"],
         ["numeric_series", "boolean_series"], 0, 22),
        ("log(close > 0)", "TYPE_MISMATCH", "value_type",
         ["common_numeric_series", "number", "numeric_series"], "boolean_series", 4, 13),
        ("if_else(close > 0, close, close > 0)", "TYPE_MISMATCH", "value_type",
         "matching_branch_types", ["numeric_series", "boolean_series"], 0, 36),
        ("industry_return(123456)", "INVALID_COMMON_INPUT", "common_input",
         "sw2021_l1_integer_literal", "123456", 0, 23),
        ("industry_return(close)", "INVALID_COMMON_INPUT", "common_input",
         "sw2021_l1_integer_literal", "Name", 0, 22),
    ],
)
def test_diagnostic_details_preserve_specific_reasons_for_localized_clients(
    source, code, kind, expected, actual, start, end,
) -> None:
    diagnostic = alpha_language.diagnose(source).diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.range.start.offset == start
    assert diagnostic.range.end.offset == end
    assert diagnostic.details is not None
    assert diagnostic.details.model_dump(mode="json") == {
        "kind": kind, "expected": expected, "actual": actual,
    }


def test_multiline_unicode_identifier_has_character_accurate_range() -> None:
    source = "(close +\n收盘)"

    diagnostic = alpha_language.diagnose(source).diagnostics[0]

    assert diagnostic.code == "UNKNOWN_IDENTIFIER"
    assert diagnostic.range.start.offset == 9
    assert diagnostic.range.end.offset == 11
    assert diagnostic.range.start.line == 2
    assert diagnostic.range.start.column == 1
    assert diagnostic.range.end.column == 3


def test_effective_lookback_is_composed_and_bounded() -> None:
    accepted = alpha_language.compile("ts_mean(lag(close, 3), 20)")
    rejected = alpha_language.diagnose("lag(ts_mean(close, 252), 2)")

    assert accepted.effective_lookback == 22
    assert rejected.diagnostics[0].code == "LOOKBACK_EXCEEDS_LIMIT"


def test_formula_limits_reject_before_compilation() -> None:
    too_long = "close + " + "1" * 4090
    too_deep = "close"
    for _ in range(33):
        too_deep = f"abs({too_deep})"

    assert alpha_language.diagnose(too_long).diagnostics[0].code == "FORMULA_TOO_LONG"
    assert alpha_language.diagnose(too_deep).diagnostics[0].code == "EXPRESSION_TOO_DEEP"


def test_formula_node_limit_is_independent_of_depth_limit() -> None:
    parts = ["close", *("1" for _ in range(128))]
    while len(parts) > 1:
        parts = [
            f"({parts[index]} + {parts[index + 1]})" if index + 1 < len(parts) else parts[index]
            for index in range(0, len(parts), 2)
        ]

    outcome = alpha_language.diagnose(parts[0])

    assert outcome.diagnostics[0].code == "TOO_MANY_EXPRESSION_NODES"


def test_work_limit_accepts_boundary_and_rejects_one_over() -> None:
    abs_definition = next(
        definition for definition in BUILTIN_DEFINITIONS if definition.identifier == "abs"
    )
    others = tuple(
        definition for definition in BUILTIN_DEFINITIONS if definition.identifier != "abs"
    )
    boundary = AlphaLanguage(
        fields=alpha_field_catalog(),
        builtins=(
            replace(abs_definition, work=BuiltinWorkDefinition(base_operations=4095)),
            *others,
        ),
    )
    one_over = AlphaLanguage(
        fields=alpha_field_catalog(),
        builtins=(
            replace(abs_definition, work=BuiltinWorkDefinition(base_operations=4096)),
            *others,
        ),
    )

    assert boundary.compile("abs(close)").estimated_work == 4096
    diagnostic = one_over.diagnose("abs(close)").diagnostics[0]
    assert diagnostic.code == "WORK_EXCEEDS_LIMIT"
    assert diagnostic.details is not None
    assert diagnostic.details.expected == 4096
    assert diagnostic.details.actual == 4097


def test_source_limit_accepts_boundary_and_rejects_one_over() -> None:
    boundary = "close".ljust(4096)

    assert alpha_language.compile(boundary).source == boundary
    assert alpha_language.diagnose(f"{boundary} ").diagnostics[0].code == "FORMULA_TOO_LONG"


def test_depth_limit_accepts_boundary_and_rejects_one_over() -> None:
    boundary = "close"
    for _ in range(31):
        boundary = f"abs({boundary})"

    assert alpha_language.compile(boundary).depth == 32
    assert alpha_language.diagnose(f"abs({boundary})").diagnostics[0].code == (
        "EXPRESSION_TOO_DEEP"
    )


def test_lookback_limit_accepts_boundary_and_rejects_one_over() -> None:
    assert alpha_language.compile("lag(close, 252)").effective_lookback == 252
    assert alpha_language.diagnose("lag(lag(close, 252), 1)").diagnostics[0].code == (
        "LOOKBACK_EXCEEDS_LIMIT"
    )


def test_node_limit_accepts_boundary_and_rejects_one_over() -> None:
    boundary = _balanced_node_formula(node_count=256)
    one_over = _balanced_node_formula(node_count=257)

    assert alpha_language.compile(boundary).node_count == 256
    assert alpha_language.diagnose(one_over).diagnostics[0].code == "TOO_MANY_EXPRESSION_NODES"


def _balanced_node_formula(*, node_count: int) -> str:
    leaves = ["close" for _ in range(65)]
    unary_count = node_count - (len(leaves) * 2 - 1)
    assert 0 <= unary_count <= len(leaves) * 2
    for index in range(unary_count):
        leaf_index = index % len(leaves)
        leaves[leaf_index] = f"abs({leaves[leaf_index]})"
    while len(leaves) > 1:
        leaves = [
            (
                f"({leaves[index]} + {leaves[index + 1]})"
                if index + 1 < len(leaves)
                else leaves[index]
            )
            for index in range(0, len(leaves), 2)
        ]
    return leaves[0]


def test_catalog_uses_actual_fields_from_one_generation() -> None:
    catalog = alpha_language.catalog(
        available_field_ids=frozenset({
            "price.close.adjusted",
            "financial.balance_sheet.total_assets.latest_reported",
        }),
        generation_manifest_sha256="a" * 64,
    )

    assert {field.identifier for field in catalog.fields} == {"close", "assets"}
    assert catalog.generation_manifest_sha256 == "a" * 64
    assert catalog.builtins == alpha_language.catalog().builtins
    assert alpha_language.catalog(available_field_ids=frozenset()).fields == []


def test_catalog_rejects_duplicate_canonical_field_identities() -> None:
    close = next(field for field in alpha_field_catalog() if field.alpha.identifier == "close")
    duplicate = replace(close, alpha=AlphaFieldCapability(identifier="another_close"))

    with pytest.raises(AlphaLanguageCatalogError, match="duplicate Canonical Field"):
        AlphaLanguage(fields=(*alpha_field_catalog(), duplicate))


def test_catalog_describes_research_category_and_source_without_changing_units() -> None:
    fields = {field.identifier: field for field in alpha_language.catalog().fields}

    assert fields["close"].research_category == "market"
    assert fields["close"].display_name == "复权收盘价"
    assert fields["amount"].source_column == "amount"
    assert fields["amount"].source_unit == "thousand CNY"
    assert fields["amount"].unit == "CNY"
    assert fields["revenue"].research_category == "financial"
    assert fields["revenue"].source_column == "total_revenue"
    assert fields["revenue"].reporting_scope == "report_type_1_consolidated"
    assert all(field.display_name and field.research_purpose for field in fields.values())


def test_daily_basic_fields_bind_to_current_data_families_and_decimal_units() -> None:
    compiled = alpha_language.compile("close_raw / pe + turnover_rate")
    assert compiled.field_ids_by_identifier == {
        "close_raw": "price.close.raw",
        "pe": "market.valuation.pe",
        "turnover_rate": "market.turnover.float_ratio",
    }
    catalog = alpha_language.catalog(
        available_field_ids=frozenset(compiled.field_ids_by_identifier.values()),
        generation_manifest_sha256="d" * 64,
    )
    fields = {field.identifier: field for field in catalog.fields}
    assert set(fields) == {"close_raw", "pe", "turnover_rate"}
    assert fields["close_raw"].family_id == "equity.eod_price"
    assert fields["close_raw"].source_endpoint == "daily"
    assert fields["pe"].family_id == "equity.daily_basic"
    assert fields["pe"].unit == "multiple"
    assert fields["turnover_rate"].unit == "ratio"
    assert fields["turnover_rate"].source_unit == "percent"
    price_only = alpha_language.catalog(available_field_ids=frozenset({"price.close.raw"}))
    assert [field.identifier for field in price_only.fields] == ["close_raw"]


def test_browser_field_fixture_matches_the_current_public_catalog() -> None:
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[4] / (
        "apps/web/browser/fixtures/data-field-catalog.json"
    )
    expected = alpha_language.catalog(generation_manifest_sha256="a" * 64).model_dump(mode="json")
    assert json.loads(fixture.read_text()) == expected
    assert len(expected["fields"]) == 226


def test_bilingual_display_metadata_covers_the_authoritative_catalog() -> None:
    import json
    from pathlib import Path

    from thesistrace.benchmark import BENCHMARK_ID

    messages = Path(__file__).resolve().parents[4] / "apps/web/src/i18n/messages"
    fields = json.loads((messages / "catalog-fields.json").read_text())
    metadata = json.loads((messages / "catalog-meta.json").read_text())
    # No availability filter: temporarily unavailable fields also require reviewed translations.
    catalog = alpha_language.catalog()
    for locale in ("en", "zh-CN"):
        assert set(fields[locale]) == {field.field_id for field in catalog.fields}
        assert set(metadata[locale]["builtins"]) == {
            builtin.identifier for builtin in catalog.builtins
        }
        assert set(metadata[locale]["industries"]) == {
            str(industry.code) for industry in catalog.industries
        }
        assert set(metadata[locale]["benchmarks"]) == {BENCHMARK_ID}
        for display_key, authority_key in (
            ("purposes", "research_purpose"), ("units", "unit"),
            ("availability", "availability"), ("reportPeriods", "report_period_selection"),
            ("missingness", "missingness"), ("reportingScopes", "reporting_scope"),
        ):
            assert set(metadata[locale][display_key]) == {
                getattr(field, authority_key) for field in catalog.fields
            }, display_key

    # Authority changes require revisiting the translations, not merely keeping the same IDs.
    for field in catalog.fields:
        assert fields["zh-CN"][field.field_id]["name"] == field.display_name
        source_locale = (
            "zh-CN" if any("\u4e00" <= c <= "\u9fff" for c in field.description) else "en"
        )
        assert fields[source_locale][field.field_id]["description"] == field.description.strip()
    for builtin in catalog.builtins:
        assert metadata["en"]["builtins"][builtin.identifier] == {
            "description": builtin.description,
            "missing": builtin.missing_value_behavior,
            "numeric": builtin.numeric_behavior,
        }
    for industry in catalog.industries:
        assert metadata["zh-CN"]["industries"][str(industry.code)] == industry.name
