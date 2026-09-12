from __future__ import annotations

import numpy as np
import pytest

from thesistrace.research_kernel.common_market import compute_common_market_series

SESSIONS = ("2026-01-05", "2026-01-06", "2026-01-07")
INSTRUMENTS = ("A", "B", "outside")
MEMBERS = {session: ("A", "B") for session in SESSIONS}


def test_universe_return_and_breadth_use_only_current_members_and_prior_close():
    result = compute_common_market_series(
        sessions=SESSIONS,
        instruments=INSTRUMENTS,
        adjusted_close=np.array([[100, 110, 110], [100, 98, 98], [1, 1000, 2000]]),
        universe_members=MEMBERS,
        industries={},
    )
    assert result.equal_weight_return[1] == pytest.approx(0.04)
    assert result.advancing_fraction[1] == 0.5
    assert result.equal_weight_return[2] == 0
    assert result.advancing_fraction[2] == 0
    assert result.member_count == (2, 2, 2)
    assert result.valid_count == (0, 2, 2)
    assert result.exclusions[0] == {"insufficient_history": 2}


def test_industry_is_a_historical_subset_and_empty_is_missing():
    industries = {
        (SESSIONS[0], "A"): "801010",
        (SESSIONS[1], "A"): "801010",
        (SESSIONS[1], "B"): "801780",
        (SESSIONS[2], "A"): "801780",
    }
    result = compute_common_market_series(
        sessions=SESSIONS,
        instruments=INSTRUMENTS,
        adjusted_close=np.array([[100, 110, 110], [100, 98, 98], [1, 1000, 2000]]),
        universe_members=MEMBERS,
        industries=industries,
        industry_code="801010",
    )
    assert result.equal_weight_return[1] == pytest.approx(0.1)
    assert result.advancing_fraction[1] == 1
    assert result.member_count == (1, 1, 0)
    assert np.isnan(result.equal_weight_return[2])
    assert np.isnan(result.advancing_fraction[2])


def test_invalid_observations_are_explained_and_future_changes_preserve_prefix():
    closes = np.array([[100.0, np.nan, 200], [100, 100, 0], [1, 2, 3]])
    args = dict(sessions=SESSIONS, instruments=INSTRUMENTS, universe_members=MEMBERS, industries={})
    result = compute_common_market_series(adjusted_close=closes, **args)
    assert result.valid_count == (0, 1, 0)
    assert result.exclusions[1] == {"invalid_current_close": 1}
    assert result.exclusions[2] == {"invalid_previous_close": 1, "invalid_current_close": 1}
    assert result.equal_weight_return[1] == 0
    closes[:, 2] = [999, 123, 4]
    revised = compute_common_market_series(adjusted_close=closes, **args)
    np.testing.assert_equal(result.equal_weight_return[:2], revised.equal_weight_return[:2])


def test_industry_identity_accepts_only_formal_literal_codes():
    from thesistrace.research_kernel.industry_catalog import SW2021_L1, validate_sw2021_l1

    assert len(SW2021_L1) == 31
    assert validate_sw2021_l1(801010) == "801010"
    for invalid in (801020, 110000, 801011, 801010.0, "801010", True, -1):
        with pytest.raises(ValueError):
            validate_sw2021_l1(invalid)


def test_common_scope_broadcasts_to_stock_without_becoming_stock_implicitly():
    from thesistrace.research_kernel.expression_types import (
        ValueType,
        binary_result_type,
        conditional_result_type,
    )

    common = ValueType.COMMON_NUMERIC_SERIES
    condition = binary_result_type("gt", common, ValueType.NUMBER)
    assert condition is ValueType.COMMON_BOOLEAN_SERIES
    assert conditional_result_type(condition, ValueType.NUMBER, common) is common
    assert (
        conditional_result_type(condition, ValueType.NUMERIC_SERIES, common)
        is ValueType.NUMERIC_SERIES
    )
    with pytest.raises(ValueError):
        binary_result_type("add", condition, ValueType.NUMBER)


def test_common_references_freeze_close_dependency_and_nested_window():
    from thesistrace.alpha_language import alpha_language

    formula = "if_else(ts_mean(universe_return(), 5) > 0, close, -close)"
    compiled = alpha_language.compile(formula)
    assert compiled.effective_lookback == 5
    assert compiled.field_ids_by_identifier == {"close": "price.close.adjusted"}
    industry = alpha_language.compile("close * industry_advancing_fraction(801010)")
    assert industry.expression["right"] == {
        "kind": "common",
        "identifier": "industry_advancing_fraction",
        "industry_code": "801010",
    }


@pytest.mark.parametrize(
    "source",
    [
        "close * industry_return(801020)",
        "close * industry_return(close)",
        "close * industry_return(801010.0)",
        "close * universe_return(801010)",
        "rank(universe_return())",
        "universe_return()",
    ],
)
def test_common_references_reject_invalid_parameters_and_stock_scope(source):
    from thesistrace.alpha_language import FormulaCompilationError, alpha_language

    with pytest.raises(FormulaCompilationError):
        alpha_language.compile(source)


def test_common_reference_survives_frozen_ir_with_full_lookback():
    from thesistrace.alpha_language import alpha_language
    from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha

    compiled = alpha_language.compile(
        "if_else(ts_mean(industry_return(801010), 5) > 0, close, -close)"
    )
    parsed = validate_normalized_alpha(
        compiled.expression,
        field_bindings={field: name for name, field in compiled.field_ids_by_identifier.items()},
    )
    assert parsed.expression == compiled.expression
    assert parsed.effective_lookback == 5
    assert parsed.estimated_work == compiled.estimated_work


def test_common_values_broadcast_identically_in_row_and_columnar_execution():
    from thesistrace.alpha_language import alpha_language
    from thesistrace.research_kernel.series_plan import (
        build_series_execution_plan,
        evaluate_columnar_execution_matrix,
        evaluate_series_execution_matrix,
    )

    compiled = alpha_language.compile("close * universe_return()")
    plan = build_series_execution_plan(compiled)
    closes = np.array([[100.0, 110, 110], [100, 98, 98], [1, 1000, 2000]])
    fields = {"price.close.adjusted": closes}
    row = evaluate_series_execution_matrix(
        plan,
        INSTRUMENTS,
        lambda instrument: {"price.close.adjusted": closes[INSTRUMENTS.index(instrument)].tolist()},
        length=3,
        universe_members=MEMBERS,
        historical_universe_members=MEMBERS,
        sessions=SESSIONS,
    )
    assert row["A"][0] is None
    assert row["A"][1] == pytest.approx(4.4)
    assert row["B"][1] == pytest.approx(3.92)
    columnar = evaluate_columnar_execution_matrix(
        plan,
        INSTRUMENTS,
        SESSIONS,
        fields,
        MEMBERS,
        historical_universe_members=MEMBERS,
        cancellation_check=lambda: None,
    )
    np.testing.assert_allclose(columnar, np.array(list(row.values()), dtype=float), equal_nan=True)


def test_nested_common_industry_dependency_does_not_depend_on_neutralization():
    from thesistrace.alpha_language import alpha_language
    from thesistrace.research_kernel.common_inputs import requires_common_industry

    industry = alpha_language.compile(
        "if_else(ts_mean(industry_return(801010), 5) > 0, close, -close)"
    )
    assert requires_common_industry(industry.expression)
    assert not requires_common_industry(
        alpha_language.compile("close * universe_return()").expression
    )
    assert not requires_common_industry(alpha_language.compile("close").expression)


def test_industry_condition_broadcast_uses_historical_members_in_both_engines():
    from thesistrace.alpha_language import alpha_language
    from thesistrace.research_kernel.series_plan import (
        build_series_execution_plan,
        evaluate_columnar_execution_matrix,
        evaluate_series_execution_matrix,
    )

    plan = build_series_execution_plan(
        alpha_language.compile("if_else(industry_return(801010) > 0, close, -close)")
    )
    closes = np.array([[100.0, 110, 110], [100, 98, 98], [1, 1000, 2000]])
    industries = {
        (SESSIONS[0], "A"): "801010",
        (SESSIONS[1], "A"): "801010",
        (SESSIONS[2], "A"): "801780",
    }
    row = evaluate_series_execution_matrix(
        plan,
        INSTRUMENTS,
        lambda instrument: {"price.close.adjusted": closes[INSTRUMENTS.index(instrument)].tolist()},
        length=3,
        universe_members=MEMBERS,
        historical_universe_members=MEMBERS,
        sessions=SESSIONS,
        industries=industries,
    )
    assert row["A"] == [None, 110, None]
    assert row["B"] == [None, 98, None]
    columnar = evaluate_columnar_execution_matrix(
        plan,
        INSTRUMENTS,
        SESSIONS,
        {"price.close.adjusted": closes},
        MEMBERS,
        industries=industries,
        historical_universe_members=MEMBERS,
        cancellation_check=lambda: None,
    )
    np.testing.assert_allclose(columnar, np.array(list(row.values()), dtype=float), equal_nan=True)


def test_authoring_catalog_exposes_formal_industry_choices_for_common_inputs():
    from thesistrace.alpha_language import alpha_language

    catalog = alpha_language.catalog().model_dump(mode="json")
    assert len(catalog["industries"]) == 31
    assert {item["code"] for item in catalog["industries"]} >= {801010, 801780, 801980}
    assert (
        next(item for item in catalog["industries"] if item["code"] == 801010)["name"] == "农林牧渔"
    )
    common = [item for item in catalog["builtins"] if item["result_type"] == "common_series"]
    assert len(common) == 4
    assert all("Universe" in item["description"] for item in common)


@pytest.mark.parametrize("wrappers,valid", [(29, True), (30, False)])
def test_industry_literal_counts_toward_source_and_frozen_depth(wrappers, valid):
    from thesistrace.alpha_language import FormulaCompilationError, alpha_language
    from thesistrace.research_kernel.alpha_expression import (
        AlphaValidationError,
        validate_normalized_alpha,
    )
    from thesistrace.research_kernel.common_inputs import common_reference

    source = "industry_return(801010)"
    expression = common_reference("industry_return", [801010])
    for _ in range(wrappers):
        source = f"abs({source})"
        expression = {"kind": "call", "identifier": "abs", "arguments": [expression]}
    source = "close + " + source
    expression = {
        "kind": "binary",
        "operator": "add",
        "left": {"kind": "field", "field_id": "price.close.adjusted"},
        "right": expression,
    }
    if valid:
        assert alpha_language.compile(source).depth == 32
        validate_normalized_alpha(expression, field_bindings={"price.close.adjusted": "close"})
    else:
        with pytest.raises(FormulaCompilationError):
            alpha_language.compile(source)
        with pytest.raises(AlphaValidationError):
            validate_normalized_alpha(expression, field_bindings={"price.close.adjusted": "close"})


@pytest.mark.parametrize("leaves,valid", [(85, True), (86, False)])
def test_industry_literal_counts_toward_source_and_frozen_node_budget(leaves, valid):
    from thesistrace.alpha_language import FormulaCompilationError, alpha_language
    from thesistrace.research_kernel.alpha_expression import (
        AlphaValidationError,
        validate_normalized_alpha,
    )
    from thesistrace.research_kernel.common_inputs import common_reference

    def tree(count):
        if count == 1:
            return "industry_return(801010)", common_reference("industry_return", [801010])
        left_source, left = tree(count // 2)
        right_source, right = tree(count - count // 2)
        return f"({left_source}+{right_source})", {
            "kind": "binary",
            "operator": "add",
            "left": left,
            "right": right,
        }

    source, expression = tree(leaves)
    source = "close + " + source
    expression = {
        "kind": "binary",
        "operator": "add",
        "left": {"kind": "field", "field_id": "price.close.adjusted"},
        "right": expression,
    }
    if valid:
        assert alpha_language.compile(source).node_count == 256
        validate_normalized_alpha(expression, field_bindings={"price.close.adjusted": "close"})
    else:
        with pytest.raises(FormulaCompilationError):
            alpha_language.compile(source)
        with pytest.raises(AlphaValidationError):
            validate_normalized_alpha(expression, field_bindings={"price.close.adjusted": "close"})
