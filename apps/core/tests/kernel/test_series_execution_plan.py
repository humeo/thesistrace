from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from contracts import field, literal, operation

from thesistrace.alpha_language import alpha_language
from thesistrace.research_kernel import series_plan
from thesistrace.research_kernel.alpha import evaluate_series
from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_columnar_execution_matrix,
    evaluate_series_execution_matrix,
    evaluate_series_execution_plan,
)

FIELD_BINDINGS = {
    "price.close.adjusted": "close",
    "market.volume.shares": "volume",
}


def _parsed(expression: dict[str, object]):
    return validate_normalized_alpha(expression, field_bindings=FIELD_BINDINGS)


def test_plan_is_postorder_and_each_nested_builtin_runs_once(monkeypatch) -> None:
    expression = operation(
        "add",
        operation("ts_mean", field("price.close.adjusted"), literal(2)),
        operation("delta", field("price.close.adjusted"), literal(1)),
    )
    plan = build_series_execution_plan(_parsed(expression))
    calls: dict[str, int] = {}
    definitions = []
    for definition in series_plan.BUILTIN_DEFINITIONS:
        evaluator = definition.evaluator

        def counted(arguments, *, identifier=definition.identifier, target=evaluator):
            calls[identifier] = calls.get(identifier, 0) + 1
            return target(arguments)

        definitions.append(replace(definition, evaluator=counted))
    monkeypatch.setattr(series_plan, "BUILTIN_DEFINITIONS", tuple(definitions))

    result = evaluate_series_execution_plan(
        plan,
        {"price.close.adjusted": [1.0, 2.0, 4.0, 8.0]},
    )

    assert [node.identifier for node in plan.nodes] == [
        "price.close.adjusted",
        "number",
        "ts_mean",
        "price.close.adjusted",
        "number",
        "delta",
        "add",
    ]
    assert result == [None, 2.5, 5.0, 10.0]
    assert calls == {"ts_mean": 1, "delta": 1}


def test_plan_owns_broadcast_alignment_and_invalid_numeric_results() -> None:
    expression = operation(
        "divide",
        operation("add", field("price.close.adjusted"), literal(2)),
        operation("subtract", field("market.volume.shares"), literal(1)),
    )
    plan = build_series_execution_plan(_parsed(expression))

    assert evaluate_series_execution_plan(
        plan,
        {
            "price.close.adjusted": [1.0, None, float("inf")],
            "market.volume.shares": [1.0, 2.0, 3.0],
        },
    ) == [None, None, None]

    with pytest.raises(ValueError, match="same length"):
        evaluate_series_execution_plan(
            plan,
            {"price.close.adjusted": [1.0], "market.volume.shares": [1.0, 2.0]},
        )


def test_missing_scalar_broadcasts_as_an_all_missing_series() -> None:
    parsed = _parsed(
        operation(
            "add",
            field("price.close.adjusted"),
            operation("log", literal(-1)),
        )
    )

    assert evaluate_series_execution_plan(
        build_series_execution_plan(parsed),
        {"price.close.adjusted": [1.0, 2.0, 3.0]},
    ) == [None, None, None]


def test_existing_expression_entrypoint_uses_the_series_plan() -> None:
    expression = operation(
        "ts_mean",
        operation("log", field("price.close.adjusted")),
        literal(2),
    )

    assert evaluate_series(
        expression,
        {"close": [1.0, -1.0, 4.0, 16.0]},
        field_bindings=FIELD_BINDINGS,
    ) == [None, None, None, pytest.approx(2.0794415416798357)]


def test_compiled_expression_builds_a_canonical_field_plan() -> None:
    compiled = alpha_language.compile("ts_mean(close + 2, 2)")
    plan = build_series_execution_plan(compiled)

    assert plan.field_names == ("price.close.adjusted",)
    assert evaluate_series_execution_plan(
        plan,
        {"price.close.adjusted": [1.0, 2.0, 4.0]},
    ) == [None, 3.5, 5.0]


@pytest.mark.parametrize("source", [
    "rank(pct_change(close, 2)) + rank(pct_change(close, 2))",
    "ts_mean(close, 3) / (ts_mean(close, 3) + ts_mean(close, 3))",
    "ts_std(close, 3) + delta(ts_std(close, 3), 1) - ts_std(close, 3)",
    "rank(ts_mean(close, 3)) + ts_mean(rank(ts_mean(close, 3)), 2)",
    "(close + 1.0) + ts_mean(close, 1)",
])
def test_repeated_columnar_subexpressions_preserve_values_and_plan_across_calls(source) -> None:
    plan = build_series_execution_plan(alpha_language.compile(source))
    original = replace(plan)
    instruments = ("a", "b", "c")
    sessions = tuple(f"s{index}" for index in range(8))
    universe = {session: instruments[index % 2:] for index, session in enumerate(sessions)}
    prices = np.array([
        [1.0, 2.0, 2.0, 0.0, np.nan, 7.0, 1e9, 1.0],
        [3.0, 3.0, 2.0, 5.0, 6.0, 7.0, 1e9, 2.0],
        [1.0, 5.0, 4.0, 7.0, 8.0, 8.0, 1e-9, 1.0],
    ])
    for multiplier in (1.0, -1.0, 2.0):
        fields = {"price.close.adjusted": prices * multiplier}
        expected = evaluate_series_execution_matrix(
            plan, instruments,
            lambda instrument, fields=fields: {
                key: matrix[instruments.index(instrument)].tolist()
                for key, matrix in fields.items()
            },
            length=len(sessions), sessions=sessions, universe_members=universe,
        )
        actual = evaluate_columnar_execution_matrix(
            plan, instruments, sessions, fields, universe,
            cancellation_check=lambda: None,
        )
        np.testing.assert_array_equal(
            actual, np.asarray([expected[instrument] for instrument in instruments], dtype=float),
        )
        assert plan == original


def test_columnar_plan_is_exactly_equivalent_for_time_series_and_cross_section() -> None:
    compiled = alpha_language.compile(
        "rank(pct_change(close, 1)) + ts_mean(volume, 2)"
    )
    plan = build_series_execution_plan(compiled)
    instruments = ("instrument_a", "instrument_b")
    sessions = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06")
    close = np.asarray(((10.0, 11.0, 12.0, 13.0), (20.0, 18.0, 21.0, 22.0)))
    volume = np.asarray(((100.0, 110.0, 120.0, 130.0), (200.0, 190.0, 180.0, 170.0)))
    universes = {session: instruments for session in sessions}

    columnar = evaluate_columnar_execution_matrix(
        plan,
        instruments,
        sessions,
        {
            "price.close.adjusted": close,
            "market.volume.shares": volume,
        },
        universes,
        cancellation_check=lambda: None,
    )
    legacy = evaluate_series_execution_matrix(
        plan,
        instruments,
        lambda instrument_id: {
            "price.close.adjusted": close[instruments.index(instrument_id)].tolist(),
            "market.volume.shares": volume[instruments.index(instrument_id)].tolist(),
        },
        length=len(sessions),
        universe_members=universes,
        sessions=sessions,
    )
    expected = np.asarray(
        [
            [np.nan if value is None else value for value in legacy[instrument_id]]
            for instrument_id in instruments
        ]
    )

    np.testing.assert_array_equal(columnar, expected)


def test_columnar_plan_checks_cancellation_between_bounded_operator_stages() -> None:
    plan = build_series_execution_plan(
        alpha_language.compile("rank(pct_change(close, 1))")
    )
    sessions = tuple(f"2026-08-{day:02d}" for day in range(1, 11))
    calls = 0

    def cancel_during_execution() -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("cancelled at bounded stage")

    with pytest.raises(RuntimeError, match="cancelled at bounded stage"):
        evaluate_columnar_execution_matrix(
            plan,
            ("instrument_a", "instrument_b"),
            sessions,
            {
                "price.close.adjusted": np.ones((2, len(sessions))),
            },
            {session: ("instrument_a", "instrument_b") for session in sessions},
            cancellation_check=cancel_during_execution,
        )

    assert calls == 4


@pytest.mark.parametrize("engine", ["series", "matrix_rank", "columnar"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_ttm_arithmetic_requires_matching_windows_through_scalar_wrappers(
    engine: str, wrapped: bool,
) -> None:
    left, right = "financial.income.total_revenue.ttm", "financial.cashflow.operating_cash_flow.ttm"
    numerator = field(left)
    if wrapped:
        numerator = operation("negate", operation("divide", operation("multiply", numerator,
                              literal(2)), literal(-2)))
    expression = operation("divide", numerator, field(right))
    if engine == "matrix_rank":
        expression = operation("rank", expression)
    plan = build_series_execution_plan(validate_normalized_alpha(
        expression, field_bindings={left: "revenue_ttm", right: "operating_cash_flow_ttm"},
    ))
    values = {left: [10.0, 10.0, 10.0], right: [2.0, 2.0, 2.0]}
    windows = {left: np.array([20100331, 20100630, 0]),
               right: np.array([20100331, 20100331, 0])}
    sessions = ("2010-04-21", "2010-08-02", "2010-08-03")
    universe = {day: ("equity:a",) for day in sessions}
    expected = [0.5 if engine == "matrix_rank" else 5.0, None, None]
    if engine == "series":
        actual = evaluate_series_execution_plan(plan, values, ttm_windows=windows)
    elif engine == "matrix_rank":
        actual = evaluate_series_execution_matrix(
            plan, ("equity:a",), lambda _: values, length=3, sessions=sessions,
            universe_members=universe, ttm_windows_for_instrument=lambda _: windows,
        )["equity:a"]
    else:
        result = evaluate_columnar_execution_matrix(
            plan, ("equity:a",), sessions, {key: np.array([v]) for key, v in values.items()},
            universe, cancellation_check=lambda: None,
            ttm_windows={key: v.reshape(1, -1) for key, v in windows.items()},
        )[0]
        actual = [float(value) if np.isfinite(value) else None for value in result]
    assert actual == expected


@pytest.mark.parametrize("kind", ["market", "lag", "rank", "abs"])
def test_ttm_window_checks_respect_non_ttm_and_explicit_transform_boundaries(kind: str) -> None:
    left = "financial.income.total_revenue.ttm"
    right = ("price.close.adjusted" if kind == "market"
             else "financial.cashflow.operating_cash_flow.ttm")
    lhs, rhs = field(left), field(right)
    if kind == "lag":
        lhs = operation("lag", lhs, literal(1))
    elif kind == "rank":
        lhs, rhs = operation("rank", lhs), operation("rank", rhs)
    elif kind == "abs":
        lhs = operation("abs", lhs)
    plan = build_series_execution_plan(validate_normalized_alpha(
        operation("divide", lhs, rhs), field_bindings={left: "revenue_ttm", right: "denominator"},
    ))
    windows = {left: np.array([[20100331, 20100630, 0]], dtype=np.int32)}
    if kind != "market":
        windows[right] = np.array([[20100331, 20100331, 0]], dtype=np.int32)
    sessions = ("2010-04-21", "2010-08-02", "2010-08-03")
    result = evaluate_columnar_execution_matrix(
        plan, ("equity:a",), sessions,
        {left: np.array([[10.0] * 3]), right: np.array([[2.0] * 3])},
        {day: ("equity:a",) for day in sessions}, cancellation_check=lambda: None,
        ttm_windows=windows,
    )[0]
    expected = {"market": [5.0, 5.0, 5.0], "lag": [None, 5.0, 5.0],
                "rank": [1.0, 1.0, 1.0], "abs": [5.0, None, None]}
    assert [float(value) if np.isfinite(value) else None for value in result] == expected[kind]


@pytest.mark.parametrize("engine", ["series", "matrix", "columnar"])
@pytest.mark.parametrize("source,expected", [
    ("if_else((revenue_ttm > 0) and (operating_cash_flow_ttm > 0), 1, 0)", [1, 1]),
    ("if_else(close > 0, revenue_ttm, revenue_ttm) / operating_cash_flow_ttm", [5, None]),
    ("if_else(close > 0, 2, revenue_ttm) / operating_cash_flow_ttm", [1, None]),
    ("if_else(close > 0, revenue_ttm, 2) / operating_cash_flow_ttm", [5, 1]),
    ("if_else(close > 0, revenue_ttm, operating_cash_flow_ttm) / operating_cash_flow_ttm",
     [5, 1]),
])
def test_conditional_ttm_branches_preserve_only_selected_flow_windows(engine, source, expected):
    from thesistrace.alpha_language import alpha_language

    plan = build_series_execution_plan(alpha_language.compile(source))
    left = "financial.income.total_revenue.ttm"
    right = "financial.cashflow.operating_cash_flow.ttm"
    values = {left: [10.0, 10.0], right: [2.0, 2.0], "price.close.adjusted": [1.0, -1.0]}
    windows = {left: np.array([20200331, 20200630]), right: np.array([20200331, 20200331])}
    sessions = ("2020-05-01", "2020-08-01")
    members = {day: ("A",) for day in sessions}
    if engine == "series":
        actual = evaluate_series_execution_plan(plan, values, ttm_windows=windows)
    elif engine == "matrix":
        # Adding rank exercises the separate cross-sectional path.
        ranked = build_series_execution_plan(alpha_language.compile(f"rank({source})"))
        actual = evaluate_series_execution_matrix(
            ranked, ("A",), lambda _: values, length=2, sessions=sessions,
            universe_members=members, ttm_windows_for_instrument=lambda _: windows,
        )["A"]
        expected = [None if value is None else 0.5 for value in expected]
    else:
        result = evaluate_columnar_execution_matrix(
            plan, ("A",), sessions, {key: np.array([value]) for key, value in values.items()},
            members, cancellation_check=lambda: None,
            ttm_windows={key: value.reshape(1, -1) for key, value in windows.items()},
        )[0]
        actual = [float(value) if np.isfinite(value) else None for value in result]
    assert actual == expected
