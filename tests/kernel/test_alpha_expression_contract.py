import math

import pytest
from contracts import FIELD_BINDINGS, field, literal, operation
from series import aligned_market_data

from thesistrace.fixture import build_fixture
from thesistrace.research_kernel.alpha import (
    evaluate_alpha_matrix,
    evaluate_series,
    validate_alpha,
)
from thesistrace.research_kernel.alpha_expression import AlphaValidationError
from thesistrace.research_series import AlignedResearchData, InstrumentProfile


def test_cs_rank_preserves_child_lookback_and_ranks_complete_cross_sections() -> None:
    parsed = validate_alpha(
        operation(
            "cs_rank",
            operation("ts_mean", field("price.close.adjusted"), literal(20)),
        ),
        field_bindings=FIELD_BINDINGS,
    )
    assert parsed.effective_lookback == 19

    sessions = ("2026-08-11", "2026-08-12", "2026-08-13")
    instruments = ["equity:a", "equity:b", "equity:c"]
    data = AlignedResearchData(
        sessions=sessions,
        instruments={item: InstrumentProfile(board="main", listed_to="") for item in instruments},
        fields={
            "financial.test": {
                (sessions[0], instruments[0]): 1,
                (sessions[0], instruments[1]): 1,
                (sessions[1], instruments[0]): 2,
                (sessions[1], instruments[1]): 4,
                (sessions[1], instruments[2]): 3,
                (sessions[2], instruments[2]): 8,
            }
        },
        universe_members={session: tuple(instruments) for session in sessions},
        industries={},
        execution_prices={},
        trading_states={},
        price_limits={},
    )

    ranked = evaluate_alpha_matrix(
        data,
        compiled_alpha=validate_alpha(
            operation("cs_rank", field("financial.test")),
            field_bindings={"financial.test": "financial_test"},
        ),
        neutralization="none",
    )

    assert ranked["sessions"][0]["values"] == [
        {"instrument_id": instruments[0], "value": 0.5},
        {"instrument_id": instruments[1], "value": 0.5},
    ]
    assert ranked["sessions"][1]["values"] == [
        {"instrument_id": instruments[0], "value": 0.0},
        {"instrument_id": instruments[1], "value": 1.0},
        {"instrument_id": instruments[2], "value": 0.5},
    ]
    assert ranked["sessions"][2]["values"] == [{"instrument_id": instruments[2], "value": 0.5}]


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


@pytest.mark.parametrize("identifier", ["ts_sum", "ts_mean", "ts_std"])
def test_rolling_numeric_result_is_independent_of_execution_prefix(identifier: str) -> None:
    values = [1e16, 1e16, -1e16, 1.0]

    def last_value(series: list[float]) -> float:
        sessions = tuple(f"2026-08-{day:02d}" for day in range(1, len(series) + 1))
        instrument = "equity:a"
        data = AlignedResearchData(
            sessions=sessions,
            instruments={instrument: InstrumentProfile(board="main", listed_to="")},
            fields={
                "price.close.adjusted": {
                    (session, instrument): value
                    for session, value in zip(sessions, series, strict=True)
                }
            },
            universe_members={session: (instrument,) for session in sessions},
            industries={},
            execution_prices={},
            trading_states={},
            price_limits={},
        )
        result = evaluate_alpha_matrix(
            data,
            compiled_alpha=validate_alpha(
                operation(
                    identifier,
                    field("price.close.adjusted"),
                    literal(3),
                ),
                field_bindings=FIELD_BINDINGS,
            ),
            neutralization="none",
        )
        return result["sessions"][-1]["values"][0]["value"]

    assert last_value(values) == last_value(values[-3:])


def test_rolling_and_cross_sectional_operators_normalize_non_finite_inputs_to_missing() -> None:
    sessions = ("2026-08-01", "2026-08-02")
    instruments = ("equity:a", "equity:b", "equity:c")
    data = AlignedResearchData(
        sessions=sessions,
        instruments={item: InstrumentProfile(board="main", listed_to="") for item in instruments},
        fields={
            "price.close.adjusted": {
                (sessions[0], instruments[0]): 1.0,
                (sessions[1], instruments[0]): 3.0,
                (sessions[0], instruments[1]): math.inf,
                (sessions[1], instruments[1]): 4.0,
                (sessions[0], instruments[2]): math.nan,
                (sessions[1], instruments[2]): -math.inf,
            }
        },
        universe_members={session: instruments for session in sessions},
        industries={},
        execution_prices={},
        trading_states={},
        price_limits={},
    )
    result = evaluate_alpha_matrix(
        data,
        compiled_alpha=validate_alpha(
            operation(
                "cs_rank",
                operation("ts_mean", field("price.close.adjusted"), literal(2)),
            ),
            field_bindings=FIELD_BINDINGS,
        ),
        neutralization="none",
    )

    assert result["sessions"][1]["values"] == [
        {"instrument_id": "equity:a", "value": 0.5}
    ]


def test_normalized_matrix_matches_characterized_kernel_matrix() -> None:
    _, canonical = build_fixture()
    normalized = operation("pct_change", field("price.close.adjusted"), literal(20))
    matrix = evaluate_alpha_matrix(
        aligned_market_data(canonical),
        compiled_alpha=validate_alpha(normalized, field_bindings=FIELD_BINDINGS),
        neutralization="none",
    )
    assert matrix["checksum"] == (
        "2b71a709ea5889f9ff6c8d0062b5ae79d9b20f6a4a233f529ace33235d7805ac"
    )
    assert matrix["effective_lookback"] == 20


@pytest.mark.parametrize(
    ("expression", "reason_code"),
    [
        (field("price.close.raw"), "UNKNOWN_FIELD"),
        (field("close_adj"), "UNKNOWN_FIELD"),
        (operation("python_eval", literal(1)), "INVALID_OPERATOR"),
        (operation("add", literal(1)), "INVALID_OPERATOR"),
        (
            operation(
                "lag",
                field("price.close.adjusted"),
                field("market.volume.shares"),
            ),
            "INVALID_WINDOW",
        ),
        (
            operation("lag", field("price.close.adjusted"), literal(0)),
            "INVALID_WINDOW",
        ),
        (
            operation("lag", field("price.close.adjusted"), literal(253)),
            "INVALID_WINDOW",
        ),
        (
            operation(
                "ts_mean",
                operation("pct_change", field("price.close.adjusted"), literal(5)),
                literal(250),
            ),
            "LOOKBACK_EXCEEDS_LIMIT",
        ),
        (literal(math.inf), "INVALID_LITERAL"),
        ({"kind": "field", "field_id": "price.close.adjusted", "unexpected": True}, "INVALID_NODE"),
    ],
)
def test_normalized_tree_rejects_invalid_nodes_deterministically(
    expression: dict[str, object],
    reason_code: str,
) -> None:
    with pytest.raises(AlphaValidationError) as captured:
        validate_alpha(expression, field_bindings=FIELD_BINDINGS)
    assert [issue.reason_code for issue in captured.value.issues] == [reason_code]
