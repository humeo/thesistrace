from __future__ import annotations

import pytest

from thesistrace.alpha_language import FormulaCompilationError, alpha_language
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_series_execution_plan,
)


def evaluate(formula: str, **inputs: list[float | None]) -> list[float | None]:
    compiled = alpha_language.compile(formula)
    return evaluate_series_execution_plan(
        build_series_execution_plan(compiled),
        {compiled.field_ids_by_identifier[name]: values for name, values in inputs.items()},
    )


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        (">", [0, 0, 1]),
        (">=", [0, 1, 1]),
        ("<", [1, 0, 0]),
        ("<=", [1, 1, 0]),
        ("==", [0, 1, 0]),
        ("!=", [1, 0, 1]),
    ],
)
def test_comparison_selects_numeric_branch(operator, expected):
    assert evaluate(f"if_else(close {operator} 2, 1, 0)", close=[1, 2, 3]) == expected


@pytest.mark.parametrize("operator", ["and", "or"])
def test_boolean_unknown_propagates_from_either_operand(operator):
    assert evaluate(
        f"if_else((close > 0) {operator} (open > 0), 10, 20)",
        close=[None, 1, -1],
        open=[1, None, None],
    ) == [None, None, None]


def test_if_else_ignores_missing_unselected_branch_and_not_preserves_unknown():
    assert evaluate(
        "if_else(not (close > 0), open, 1 / open)",
        close=[-1, 1, None, -1],
        open=[0, 2, 2, None],
    ) == [0, 0.5, None, None]


def test_nested_window_and_dependencies_include_both_branches():
    compiled = alpha_language.compile("if_else(close > 0, close, ts_mean(lag(open, 3), 5))")
    assert compiled.effective_lookback == 7
    assert set(compiled.field_ids_by_identifier) == {"close", "open"}
    assert evaluate(
        "if_else(close > 0, close, ts_mean(open, 2))", close=[1, -1, -1], open=[None, 4, 6]
    ) == [1, None, 5]


@pytest.mark.parametrize(
    "formula",
    [
        "close > 0",
        "(close > 0) + close",
        "close and open",
        "if_else(close, open, close)",
        "if_else(close > 0, close, open > 0)",
        "abs(close > 0)",
        "if_else(close > 0, close, ts_mean(open, 253))",
    ],
)
def test_invalid_condition_types_and_unselected_branch_are_rejected(formula):
    with pytest.raises(FormulaCompilationError):
        alpha_language.compile(formula)


def test_conditional_columnar_and_rank_matrix_match_independent_values():
    import numpy as np

    from thesistrace.research_kernel.series_plan import (
        evaluate_columnar_execution_matrix,
        evaluate_series_execution_matrix,
    )

    compiled = alpha_language.compile("if_else(not (close > open), rank(close) + 10, 0)")
    plan = build_series_execution_plan(compiled)
    instruments = ("A", "B")
    sessions = ("2026-01-05", "2026-01-06", "2026-01-07")
    members = {date: instruments for date in sessions}
    inputs = {
        "A": {"close": [1, None, 3], "open": [2, 1, 2]},
        "B": {"close": [2, 2, 1], "open": [1, None, 2]},
    }
    fields = compiled.field_ids_by_identifier
    row = evaluate_series_execution_matrix(
        plan,
        instruments,
        lambda instrument: {fields[name]: values for name, values in inputs[instrument].items()},
        length=3,
        universe_members=members,
        sessions=sessions,
    )
    expected = {"A": [10, None, 0], "B": [0, None, 10]}
    assert row == expected
    columnar = evaluate_columnar_execution_matrix(
        plan,
        instruments,
        sessions,
        {
            field: np.array([inputs[instrument][name] for instrument in instruments], dtype=float)
            for name, field in fields.items()
        },
        members,
        cancellation_check=lambda: None,
    )
    np.testing.assert_allclose(
        columnar, np.array(list(expected.values()), dtype=float), equal_nan=True
    )


def test_frozen_ir_keeps_types_dependencies_and_resource_accounting():
    from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha

    compiled = alpha_language.compile("if_else(close > open, close, ts_mean(lag(open, 3), 5))")
    restored = validate_normalized_alpha(
        compiled.expression,
        field_bindings={field: name for name, field in compiled.field_ids_by_identifier.items()},
    )
    assert restored.effective_lookback == compiled.effective_lookback
    assert restored.estimated_work == compiled.estimated_work


def test_frozen_ir_rejects_depth_and_work_before_execution():
    from thesistrace.research_kernel.alpha_expression import (
        AlphaValidationError,
        validate_normalized_alpha,
    )

    field = {"kind": "field", "field_id": "price.close.adjusted"}
    expression = field
    for _ in range(33):
        expression = {"kind": "unary", "operator": "negate", "operand": expression}
    with pytest.raises(AlphaValidationError) as error:
        validate_normalized_alpha(expression, field_bindings={"price.close.adjusted": "close"})
    assert error.value.issues[0].reason_code == "EXPRESSION_TOO_DEEP"


def test_future_prices_do_not_change_prior_conditional_signals():
    formula = "if_else(close > ts_mean(close, 2), close, -close)"
    assert evaluate(formula, close=[1, 3, 2, 4]) == [None, 3, -2, 4]
    assert evaluate(formula, close=[1, 3, 2, 400])[:3] == [None, 3, -2]


def test_frozen_ir_rejects_work_in_an_unselected_branch():
    from thesistrace.research_kernel.alpha_expression import (
        AlphaValidationError,
        validate_normalized_alpha,
    )

    field = {"kind": "field", "field_id": "price.close.adjusted"}
    window = {
        "kind": "call",
        "identifier": "ts_sum",
        "arguments": [field, {"kind": "number", "value": 252}],
    }
    expensive = window
    for _ in range(17):
        expensive = {"kind": "binary", "operator": "add", "left": expensive, "right": window}
    expression = {
        "kind": "call",
        "identifier": "if_else",
        "arguments": [
            {
                "kind": "binary",
                "operator": "gt",
                "left": field,
                "right": {"kind": "number", "value": 0},
            },
            field,
            expensive,
        ],
    }
    with pytest.raises(AlphaValidationError) as error:
        validate_normalized_alpha(expression, field_bindings={"price.close.adjusted": "close"})
    assert error.value.issues[0].reason_code == "WORK_EXCEEDS_LIMIT"
