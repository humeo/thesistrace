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
        }
        for field in alpha_field_catalog()
        if field.alpha is not None
    ]
    assert [builtin["identifier"] for builtin in catalog["builtins"]] == [
        "abs",
        "log",
        "sign",
        "cs_rank",
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

    close_reader = fields["close_adj"].alpha_series_reader
    turnover_reader = fields["turnover_amount_cny"].alpha_series_reader
    assert close_reader is not None
    assert turnover_reader is not None
    assert close_reader(rows) == (10.5, None)
    assert turnover_reader(rows) == (200.0, None)


@pytest.mark.parametrize(
    ("source", "expression"),
    [
        (
            "close_adj",
            {"kind": "field", "field_id": "price.close.adjusted"},
        ),
        (
            "ts_mean(close_adj, 20)",
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
            "-(close_adj + 2) / ts_std(volume_shares, 5)",
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


def test_compile_estimates_builtin_work_from_its_definition() -> None:
    short = alpha_language.compile("ts_mean(close_adj, 2)")
    long = alpha_language.compile("ts_mean(close_adj, 20)")

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
        builtins["cs_rank"].evaluator((invalid,))
    for builtin in (item for name, item in builtins.items() if name != "cs_rank"):
        arguments = (invalid,) if len(builtin.parameters) == 1 else (invalid, 1)
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
        ("value = close_adj", "SYNTAX_ERROR"),
        ("close_adj; volume_shares", "SYNTAX_ERROR"),
        ("close_adj.real", "UNSUPPORTED_SYNTAX"),
        ("close_adj[0]", "UNSUPPORTED_SYNTAX"),
        ("[close_adj]", "UNSUPPORTED_SYNTAX"),
        ("{close_adj}", "UNSUPPORTED_SYNTAX"),
        ("(x for x in [close_adj])", "UNSUPPORTED_SYNTAX"),
        ("lambda: close_adj", "UNSUPPORTED_SYNTAX"),
        ("close_adj if 1 else volume_shares", "UNSUPPORTED_SYNTAX"),
        ("close_adj > volume_shares", "UNSUPPORTED_SYNTAX"),
        ("ts_mean(series=close_adj, window=20)", "KEYWORD_ARGUMENT_NOT_ALLOWED"),
        ("ts_mean(*(close_adj, 20))", "STARRED_ARGUMENT_NOT_ALLOWED"),
        ("+close_adj", "UNSUPPORTED_OPERATOR"),
        ("close_adj ** 2", "UNSUPPORTED_OPERATOR"),
        ("True", "BOOLEAN_NOT_ALLOWED"),
        ("1e309 + close_adj", "NON_FINITE_LITERAL"),
    ],
)
def test_compile_rejects_every_non_allowlisted_language_form(source: str, code: str) -> None:
    diagnostics = alpha_language.diagnose(source)

    assert diagnostics.valid is False
    assert diagnostics.diagnostics[0].code == code
    with pytest.raises(FormulaCompilationError):
        alpha_language.compile(source)


@pytest.mark.parametrize(
    ("source", "code", "start_offset", "end_offset"),
    [
        ("closes + 1", "UNKNOWN_IDENTIFIER", 0, 6),
        ("close_adj(1)", "NOT_CALLABLE", 0, 9),
        ("ts_mean", "EXPECTED_FIELD", 0, 7),
        ("ts_mean(close_adj)", "INVALID_ARITY", 0, 18),
        ("ts_mean(close_adj, 0)", "WINDOW_OUT_OF_RANGE", 19, 20),
        ("ts_mean(close_adj, 2.5)", "WINDOW_MUST_BE_INTEGER", 19, 22),
        ("abs(close_adj, 2)", "INVALID_ARITY", 0, 17),
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
    source = "close_adj +"

    diagnostic = alpha_language.diagnose(source).diagnostics[0]

    assert diagnostic.code == "SYNTAX_ERROR"
    assert diagnostic.range.start.offset == len(source)
    assert diagnostic.range.end.offset == len(source)
    assert diagnostic.range.start.line == 1
    assert diagnostic.range.start.column == 12
    assert diagnostic.details is not None
    assert diagnostic.details.model_dump(mode="json") == {
        "kind": "syntax",
        "expected": "one_complete_expression",
        "actual": "incomplete_expression",
    }


def test_relevant_diagnostics_include_typed_expected_and_actual_details() -> None:
    arity = alpha_language.diagnose("ts_mean(close_adj)").diagnostics[0]
    value_type = alpha_language.diagnose("ts_mean(1, 2)").diagnostics[0]
    window = alpha_language.diagnose("ts_mean(close_adj, 0)").diagnostics[0]

    assert arity.details is not None
    assert arity.details.model_dump(mode="json") == {
        "kind": "arity",
        "expected": 2,
        "actual": 1,
    }
    assert value_type.details is not None
    assert value_type.details.model_dump(mode="json") == {
        "kind": "value_type",
        "expected": "numeric_series",
        "actual": "number",
    }
    assert window.details is not None
    assert window.details.model_dump(mode="json") == {
        "kind": "window",
        "expected": "integer_literal_1_to_252",
        "actual": 0,
    }


def test_multiline_unicode_identifier_has_character_accurate_range() -> None:
    source = "(close_adj +\n收盘)"

    diagnostic = alpha_language.diagnose(source).diagnostics[0]

    assert diagnostic.code == "UNKNOWN_IDENTIFIER"
    assert diagnostic.range.start.offset == 13
    assert diagnostic.range.end.offset == 15
    assert diagnostic.range.start.line == 2
    assert diagnostic.range.start.column == 1
    assert diagnostic.range.end.column == 3


def test_effective_lookback_is_composed_and_bounded() -> None:
    accepted = alpha_language.compile("ts_mean(lag(close_adj, 3), 20)")
    rejected = alpha_language.diagnose("lag(ts_mean(close_adj, 252), 2)")

    assert accepted.effective_lookback == 22
    assert rejected.diagnostics[0].code == "LOOKBACK_EXCEEDS_LIMIT"


def test_formula_limits_reject_before_compilation() -> None:
    too_long = "close_adj + " + "1" * 4090
    too_deep = "close_adj"
    for _ in range(33):
        too_deep = f"abs({too_deep})"

    assert alpha_language.diagnose(too_long).diagnostics[0].code == "FORMULA_TOO_LONG"
    assert alpha_language.diagnose(too_deep).diagnostics[0].code == "EXPRESSION_TOO_DEEP"


def test_formula_node_limit_is_independent_of_depth_limit() -> None:
    parts = ["close_adj", *("1" for _ in range(128))]
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

    assert boundary.compile("abs(close_adj)").estimated_work == 4096
    diagnostic = one_over.diagnose("abs(close_adj)").diagnostics[0]
    assert diagnostic.code == "WORK_EXCEEDS_LIMIT"
    assert diagnostic.details is not None
    assert diagnostic.details.expected == 4096
    assert diagnostic.details.actual == 4097


def test_source_limit_accepts_boundary_and_rejects_one_over() -> None:
    boundary = "close_adj".ljust(4096)

    assert alpha_language.compile(boundary).source == boundary
    assert alpha_language.diagnose(f"{boundary} ").diagnostics[0].code == "FORMULA_TOO_LONG"


def test_depth_limit_accepts_boundary_and_rejects_one_over() -> None:
    boundary = "close_adj"
    for _ in range(31):
        boundary = f"abs({boundary})"

    assert alpha_language.compile(boundary).depth == 32
    assert alpha_language.diagnose(f"abs({boundary})").diagnostics[0].code == (
        "EXPRESSION_TOO_DEEP"
    )


def test_lookback_limit_accepts_boundary_and_rejects_one_over() -> None:
    assert alpha_language.compile("lag(close_adj, 252)").effective_lookback == 252
    assert alpha_language.diagnose("lag(lag(close_adj, 252), 1)").diagnostics[0].code == (
        "LOOKBACK_EXCEEDS_LIMIT"
    )


def test_node_limit_accepts_boundary_and_rejects_one_over() -> None:
    boundary = _balanced_node_formula(node_count=256)
    one_over = _balanced_node_formula(node_count=257)

    assert alpha_language.compile(boundary).node_count == 256
    assert alpha_language.diagnose(one_over).diagnostics[0].code == "TOO_MANY_EXPRESSION_NODES"


def _balanced_node_formula(*, node_count: int) -> str:
    leaves = ["close_adj" for _ in range(65)]
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
