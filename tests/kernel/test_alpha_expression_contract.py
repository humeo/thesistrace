import math

import pytest
from contracts import FIELD_BINDINGS, field, literal, operation

from thesistrace.fixture import build_fixture
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix,
    evaluate_series,
    validate_alpha,
)
from thesistrace.research_kernel.alpha_expression import AlphaValidationError, operator_catalog


def test_operator_catalog_is_closed_stable_and_descriptive() -> None:
    catalog = operator_catalog()
    assert catalog["semantic_version"] == "1.0.0"
    operators = catalog["operators"]
    assert [item["operator_id"] for item in operators] == [
        "add",
        "subtract",
        "multiply",
        "divide",
        "negate",
        "abs",
        "log",
        "sign",
        "lag",
        "delta",
        "pct_change",
        "ts_mean",
        "ts_sum",
        "ts_std",
        "ts_min",
        "ts_max",
    ]
    assert all(
        set(item)
        == {
            "operator_id",
            "kind",
            "arity",
            "operand_rules",
            "result_type",
            "rolling_bounds",
        }
        for item in operators
    )
    assert all(item["result_type"] == "numeric" for item in operators)
    assert {
        item["operator_id"]: item["rolling_bounds"]
        for item in operators
        if item["rolling_bounds"] is not None
    } == {
        operator_id: {"minimum": 1, "maximum": 252}
        for operator_id in (
            "lag",
            "delta",
            "pct_change",
            "ts_mean",
            "ts_sum",
            "ts_std",
            "ts_min",
            "ts_max",
        )
    }


def test_normalized_input_has_one_bounded_semantics() -> None:
    normalized = operation(
        "add",
        operation(
            "ts_mean",
            operation("pct_change", field("price.close.adjusted"), literal(5)),
            literal(20),
        ),
        operation("abs", field("market.volume.shares")),
    )
    values = {
        "close_adj": [float(index + 1) for index in range(40)],
        "volume_shares": [10.0] * 40,
    }

    parsed = validate_alpha(normalized, field_bindings=FIELD_BINDINGS)
    assert parsed.field_names == ("close_adj", "volume_shares")
    assert parsed.field_ids == (
        "market.volume.shares",
        "price.close.adjusted",
    )
    assert parsed.effective_lookback == 24
    assert len(evaluate_series(normalized, values, field_bindings=FIELD_BINDINGS)) == 40


@pytest.mark.parametrize(
    "normalized",
    [
        operation("add", field("price.close.adjusted"), literal(2)),
        operation("subtract", field("price.close.adjusted"), literal(2)),
        operation("multiply", field("price.close.adjusted"), literal(2)),
        operation("divide", field("price.close.adjusted"), literal(2)),
        operation("negate", field("price.close.adjusted")),
        operation("abs", operation("negate", field("price.close.adjusted"))),
        operation("log", field("price.close.adjusted")),
        operation("sign", field("price.close.adjusted")),
        operation("lag", field("price.close.adjusted"), literal(2)),
        operation("delta", field("price.close.adjusted"), literal(2)),
        operation("pct_change", field("price.close.adjusted"), literal(2)),
        operation("ts_mean", field("price.close.adjusted"), literal(2)),
        operation("ts_sum", field("price.close.adjusted"), literal(2)),
        operation("ts_std", field("price.close.adjusted"), literal(2)),
        operation("ts_min", field("price.close.adjusted"), literal(2)),
        operation("ts_max", field("price.close.adjusted"), literal(2)),
    ],
)
def test_every_normalized_operator_executes(normalized: dict[str, object]) -> None:
    values = {"close_adj": [1.0, 2.0, 4.0, 8.0, 16.0]}
    assert len(evaluate_series(normalized, values, field_bindings=FIELD_BINDINGS)) == 5


def test_normalized_matrix_matches_characterized_kernel_matrix() -> None:
    _, canonical = build_fixture()
    normalized = operation("pct_change", field("price.close.adjusted"), literal(20))
    matrix = evaluate_alpha_matrix(
        canonical,
        expression=normalized,
        field_bindings=FIELD_BINDINGS,
        universe_name="top300",
        neutralization="none",
    )
    assert matrix["checksum"] == (
        "c002b936f6e730c3a3e4a98161a4ec1f805beb9d509f96d053cf131c5927be6f"
    )
    assert matrix["effective_lookback"] == 20


@pytest.mark.parametrize(
    ("expression", "reason_code"),
    [
        (field("price.close.raw"), "UNKNOWN_FIELD"),
        (field("close_adj"), "UNKNOWN_FIELD"),
        (operation("python_eval", literal(1)), "UNKNOWN_OPERATOR"),
        (operation("add", literal(1)), "INVALID_ARITY"),
        (
            operation(
                "lag",
                field("price.close.adjusted"),
                field("market.volume.shares"),
            ),
            "INVALID_OPERAND",
        ),
        (
            operation("lag", field("price.close.adjusted"), literal(0)),
            "WINDOW_OUT_OF_RANGE",
        ),
        (
            operation("lag", field("price.close.adjusted"), literal(253)),
            "WINDOW_OUT_OF_RANGE",
        ),
        (
            operation(
                "ts_mean",
                operation("pct_change", field("price.close.adjusted"), literal(5)),
                literal(250),
            ),
            "LOOKBACK_EXCEEDS_LIMIT",
        ),
        ({"literal": math.inf}, "NON_FINITE_LITERAL"),
        ({"literal": 10**400}, "NON_FINITE_LITERAL"),
        ({"field_id": "price.close.adjusted", "unexpected": True}, "MALFORMED_NODE"),
    ],
)
def test_normalized_tree_rejects_invalid_nodes_deterministically(
    expression: dict[str, object],
    reason_code: str,
) -> None:
    with pytest.raises(AlphaValidationError) as captured:
        validate_alpha(expression, field_bindings=FIELD_BINDINGS)
    assert [issue.reason_code for issue in captured.value.issues] == [reason_code]
