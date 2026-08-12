import math

import pytest
from contracts import FIELD_BINDINGS, field, literal, operation

from thesistrace.data import read_alpha_field_series
from thesistrace.fixture import build_fixture
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix,
    evaluate_series,
    validate_alpha,
)
from thesistrace.research_kernel.alpha_expression import (
    MAX_ALPHA_RUN_ESTIMATED_WORK,
    AlphaValidationError,
    estimate_alpha_run_work,
    operator_catalog,
)


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


def test_run_work_combines_formula_dates_and_universe_at_boundary() -> None:
    boundary = estimate_alpha_run_work(
        100,
        research_session_count=50,
        universe_instrument_count=3_000,
    )
    one_over = estimate_alpha_run_work(
        100,
        research_session_count=51,
        universe_instrument_count=3_000,
    )

    assert boundary == MAX_ALPHA_RUN_ESTIMATED_WORK
    assert one_over > MAX_ALPHA_RUN_ESTIMATED_WORK
    assert (
        estimate_alpha_run_work(
            100,
            research_session_count=50,
            universe_instrument_count=0,
        )
        == 0
    )


def test_alpha_matrix_evaluates_only_the_selected_universe_union() -> None:
    _, canonical = build_fixture()
    selected = str(canonical["instruments"][0]["instrument_id"])
    excluded = str(canonical["instruments"][1]["instrument_id"])
    for snapshot in canonical["liquidity_universes"]["top300"]:
        snapshot["instrument_ids"] = [selected]
    reads: list[tuple[str, int]] = []

    def reader(field_id, rows):
        reads.append((field_id, len(rows)))
        return read_alpha_field_series(field_id, rows)

    matrix = evaluate_alpha_matrix(
        canonical,
        compiled_alpha=validate_alpha(
            {"field_id": "price.close.adjusted"},
            field_bindings=FIELD_BINDINGS,
        ),
        universe_name="top300",
        neutralization="none",
        read_field_series=reader,
    )

    assert reads == [("price.close.adjusted", len(canonical["research_calendar"]))]
    assert all(
        excluded not in {row["instrument_id"] for row in session["values"]}
        for session in matrix["sessions"]
    )


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
    ("normalized", "expected"),
    [
        (
            operation("add", field("price.close.adjusted"), literal(2)),
            [3.0, 4.0, 6.0, 10.0, 18.0],
        ),
        (
            operation("subtract", field("price.close.adjusted"), literal(2)),
            [-1.0, 0.0, 2.0, 6.0, 14.0],
        ),
        (
            operation("multiply", field("price.close.adjusted"), literal(2)),
            [2.0, 4.0, 8.0, 16.0, 32.0],
        ),
        (
            operation("divide", field("price.close.adjusted"), literal(2)),
            [0.5, 1.0, 2.0, 4.0, 8.0],
        ),
        (
            operation("negate", field("price.close.adjusted")),
            [-1.0, -2.0, -4.0, -8.0, -16.0],
        ),
        (
            operation("abs", operation("negate", field("price.close.adjusted"))),
            [1.0, 2.0, 4.0, 8.0, 16.0],
        ),
        (
            operation("log", field("price.close.adjusted")),
            [0.0, math.log(2.0), math.log(4.0), math.log(8.0), math.log(16.0)],
        ),
        (
            operation("sign", field("price.close.adjusted")),
            [1.0, 1.0, 1.0, 1.0, 1.0],
        ),
        (
            operation("lag", field("price.close.adjusted"), literal(2)),
            [None, None, 1.0, 2.0, 4.0],
        ),
        (
            operation("delta", field("price.close.adjusted"), literal(2)),
            [None, None, 3.0, 6.0, 12.0],
        ),
        (
            operation("pct_change", field("price.close.adjusted"), literal(2)),
            [None, None, 3.0, 3.0, 3.0],
        ),
        (
            operation("ts_mean", field("price.close.adjusted"), literal(2)),
            [None, 1.5, 3.0, 6.0, 12.0],
        ),
        (
            operation("ts_sum", field("price.close.adjusted"), literal(2)),
            [None, 3.0, 6.0, 12.0, 24.0],
        ),
        (
            operation("ts_std", field("price.close.adjusted"), literal(2)),
            [None, 0.5, 1.0, 2.0, 4.0],
        ),
        (
            operation("ts_min", field("price.close.adjusted"), literal(2)),
            [None, 1.0, 2.0, 4.0, 8.0],
        ),
        (
            operation("ts_max", field("price.close.adjusted"), literal(2)),
            [None, 2.0, 4.0, 8.0, 16.0],
        ),
    ],
)
def test_every_normalized_operator_has_exact_semantics(
    normalized: dict[str, object],
    expected: list[float | None],
) -> None:
    values = {"close_adj": [1.0, 2.0, 4.0, 8.0, 16.0]}
    assert evaluate_series(normalized, values, field_bindings=FIELD_BINDINGS) == expected


def test_normalized_evaluation_preserves_missing_and_non_finite_rules() -> None:
    close = field("price.close.adjusted")
    values = {"close_adj": [1.0, 2.0, None, 4.0, 8.0]}

    assert evaluate_series(
        operation("pct_change", close, literal(1)),
        values,
        field_bindings=FIELD_BINDINGS,
    ) == [None, 1.0, None, None, 1.0]
    assert evaluate_series(
        operation("ts_mean", close, literal(2)),
        values,
        field_bindings=FIELD_BINDINGS,
    ) == [None, 1.5, None, None, 6.0]
    assert evaluate_series(
        operation("ts_std", close, literal(1)),
        values,
        field_bindings=FIELD_BINDINGS,
    ) == [0.0, 0.0, None, 0.0, 0.0]
    assert evaluate_series(
        operation("sign", operation("negate", close)),
        values,
        field_bindings=FIELD_BINDINGS,
    ) == [-1.0, -1.0, None, -1.0, -1.0]
    assert evaluate_series(
        operation("log", operation("subtract", close, literal(4))),
        values,
        field_bindings=FIELD_BINDINGS,
    ) == [None, None, None, None, math.log(4.0)]
    assert (
        evaluate_series(
            operation("divide", close, operation("subtract", close, close)),
            values,
            field_bindings=FIELD_BINDINGS,
        )
        == [None] * 5
    )
    assert evaluate_series(literal(1), {}, field_bindings=FIELD_BINDINGS) == [1.0]


def test_normalized_matrix_matches_characterized_kernel_matrix() -> None:
    _, canonical = build_fixture()
    normalized = operation("pct_change", field("price.close.adjusted"), literal(20))
    matrix = evaluate_alpha_matrix(
        canonical,
        compiled_alpha=validate_alpha(normalized, field_bindings=FIELD_BINDINGS),
        universe_name="top300",
        neutralization="none",
        read_field_series=read_alpha_field_series,
    )
    assert matrix["checksum"] == (
        "5acaa9358b7a109487c94477d93b96562f961307e7f780348c4ee8080e2048fb"
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
