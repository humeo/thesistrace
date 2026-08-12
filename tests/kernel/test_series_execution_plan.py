from __future__ import annotations

from dataclasses import replace

import pytest

from thesistrace.alpha_language import alpha_language
from thesistrace.research_kernel import series_plan
from thesistrace.research_kernel.alpha import evaluate_series
from thesistrace.research_kernel.alpha_expression import validate_normalized_alpha
from thesistrace.research_kernel.series_plan import (
    build_series_execution_plan,
    evaluate_series_execution_plan,
)

FIELD_BINDINGS = {
    "price.close.adjusted": "close_adj",
    "market.volume.shares": "volume_shares",
}


def _parsed(expression: dict[str, object]):
    return validate_normalized_alpha(expression, field_bindings=FIELD_BINDINGS)


def test_plan_is_postorder_and_each_nested_builtin_runs_once(monkeypatch) -> None:
    expression = {
        "operator_id": "add",
        "operands": [
            {
                "operator_id": "ts_mean",
                "operands": [{"field_id": "price.close.adjusted"}, {"literal": 2}],
            },
            {
                "operator_id": "delta",
                "operands": [{"field_id": "price.close.adjusted"}, {"literal": 1}],
            },
        ],
    }
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
    expression = {
        "operator_id": "divide",
        "operands": [
            {
                "operator_id": "add",
                "operands": [{"field_id": "price.close.adjusted"}, {"literal": 2}],
            },
            {
                "operator_id": "subtract",
                "operands": [{"field_id": "market.volume.shares"}, {"literal": 1}],
            },
        ],
    }
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
        {
            "operator_id": "add",
            "operands": [
                {"field_id": "price.close.adjusted"},
                {
                    "operator_id": "log",
                    "operands": [{"literal": -1}],
                },
            ],
        }
    )

    assert evaluate_series_execution_plan(
        build_series_execution_plan(parsed),
        {"price.close.adjusted": [1.0, 2.0, 3.0]},
    ) == [None, None, None]


def test_existing_expression_entrypoint_uses_the_series_plan() -> None:
    expression = {
        "operator_id": "ts_mean",
        "operands": [
            {
                "operator_id": "log",
                "operands": [{"field_id": "price.close.adjusted"}],
            },
            {"literal": 2},
        ],
    }

    assert evaluate_series(
        expression,
        {"close_adj": [1.0, -1.0, 4.0, 16.0]},
        field_bindings=FIELD_BINDINGS,
    ) == [None, None, None, pytest.approx(2.0794415416798357)]


def test_compiled_expression_builds_a_canonical_field_plan() -> None:
    compiled = alpha_language.compile("ts_mean(close_adj + 2, 2)")
    plan = build_series_execution_plan(compiled)

    assert plan.field_names == ("price.close.adjusted",)
    assert evaluate_series_execution_plan(
        plan,
        {"price.close.adjusted": [1.0, 2.0, 4.0]},
    ) == [None, 3.5, 5.0]
