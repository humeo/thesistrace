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
