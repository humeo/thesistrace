import math

import pytest

from thesistrace.alpha import (
    AlphaValidationError,
    evaluate_alpha_matrix,
    evaluate_series,
    validate_alpha,
)
from thesistrace.fixture import build_fixture
from thesistrace.research_kernel.alpha_expression import operator_catalog


def field(field_id: str) -> dict[str, object]:
    return {"field_id": field_id}


def literal(value: int | float) -> dict[str, object]:
    return {"literal": value}


def operation(operator_id: str, *operands: dict[str, object]) -> dict[str, object]:
    return {"operator_id": operator_id, "operands": list(operands)}


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


def test_normalized_and_legacy_inputs_share_one_accepted_semantics() -> None:
    normalized = operation(
        "add",
        operation("ts_mean", operation("pct_change", field("close_adj"), literal(5)), literal(20)),
        operation("abs", field("volume_shares")),
    )
    legacy = "ts_mean(pct_change($close_adj, 5), 20) + abs($volume_shares)"
    values = {
        "close_adj": [float(index + 1) for index in range(40)],
        "volume_shares": [10.0] * 40,
    }

    normalized_parsed = validate_alpha(normalized)
    legacy_parsed = validate_alpha(legacy)
    assert normalized_parsed.field_names == legacy_parsed.field_names == (
        "close_adj",
        "volume_shares",
    )
    assert normalized_parsed.effective_lookback == legacy_parsed.effective_lookback == 24
    assert evaluate_series(normalized, values) == evaluate_series(legacy, values)


@pytest.mark.parametrize(
    ("normalized", "legacy"),
    [
        (operation("add", field("close_adj"), literal(2)), "$close_adj + 2"),
        (operation("subtract", field("close_adj"), literal(2)), "$close_adj - 2"),
        (operation("multiply", field("close_adj"), literal(2)), "$close_adj * 2"),
        (operation("divide", field("close_adj"), literal(2)), "$close_adj / 2"),
        (operation("negate", field("close_adj")), "-$close_adj"),
        (operation("abs", operation("negate", field("close_adj"))), "abs(-$close_adj)"),
        (operation("log", field("close_adj")), "log($close_adj)"),
        (operation("sign", field("close_adj")), "sign($close_adj)"),
        (operation("lag", field("close_adj"), literal(2)), "lag($close_adj, 2)"),
        (operation("delta", field("close_adj"), literal(2)), "delta($close_adj, 2)"),
        (
            operation("pct_change", field("close_adj"), literal(2)),
            "pct_change($close_adj, 2)",
        ),
        (operation("ts_mean", field("close_adj"), literal(2)), "ts_mean($close_adj, 2)"),
        (operation("ts_sum", field("close_adj"), literal(2)), "ts_sum($close_adj, 2)"),
        (operation("ts_std", field("close_adj"), literal(2)), "ts_std($close_adj, 2)"),
        (operation("ts_min", field("close_adj"), literal(2)), "ts_min($close_adj, 2)"),
        (operation("ts_max", field("close_adj"), literal(2)), "ts_max($close_adj, 2)"),
    ],
)
def test_every_normalized_operator_matches_legacy_behavior(
    normalized: dict[str, object],
    legacy: str,
) -> None:
    values = {"close_adj": [1.0, 2.0, 4.0, 8.0, 16.0]}
    assert evaluate_series(normalized, values) == evaluate_series(legacy, values)


def test_normalized_matrix_matches_characterized_legacy_matrix() -> None:
    _, canonical = build_fixture()
    normalized = operation("pct_change", field("close_adj"), literal(20))
    legacy = "pct_change($close_adj, 20)"

    normalized_matrix = evaluate_alpha_matrix(
        canonical,
        expression=normalized,
        universe_name="top300",
        neutralization="none",
    )
    legacy_matrix = evaluate_alpha_matrix(
        canonical,
        expression=legacy,
        universe_name="top300",
        neutralization="none",
    )
    assert normalized_matrix["checksum"] == legacy_matrix["checksum"]
    assert normalized_matrix["sessions"] == legacy_matrix["sessions"]
    assert normalized_matrix["effective_lookback"] == legacy_matrix["effective_lookback"]


@pytest.mark.parametrize(
    ("expression", "reason_code"),
    [
        (field("close_raw"), "UNKNOWN_FIELD"),
        (operation("python_eval", literal(1)), "UNKNOWN_OPERATOR"),
        (operation("add", literal(1)), "INVALID_ARITY"),
        (operation("lag", field("close_adj"), field("volume_shares")), "INVALID_OPERAND"),
        (operation("lag", field("close_adj"), literal(0)), "WINDOW_OUT_OF_RANGE"),
        (operation("lag", field("close_adj"), literal(253)), "WINDOW_OUT_OF_RANGE"),
        (
            operation(
                "ts_mean",
                operation("pct_change", field("close_adj"), literal(5)),
                literal(250),
            ),
            "LOOKBACK_EXCEEDS_LIMIT",
        ),
        ({"literal": math.inf}, "NON_FINITE_LITERAL"),
        ({"field_id": "close_adj", "unexpected": True}, "MALFORMED_NODE"),
    ],
)
def test_normalized_tree_rejects_invalid_nodes_deterministically(
    expression: dict[str, object],
    reason_code: str,
) -> None:
    with pytest.raises(AlphaValidationError) as captured:
        validate_alpha(expression)
    assert [issue.reason_code for issue in captured.value.issues] == [reason_code]
