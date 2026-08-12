from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from thesistrace.research_kernel.alpha_builtins import (
    BUILTIN_DEFINITIONS,
    NumericSeries,
)

type PlanValue = float | int | None | NumericSeries
type PlanNodeKind = Literal["number", "field", "unary", "binary", "builtin"]


class CompiledAlphaLike(Protocol):
    expression: Mapping[str, object]
    field_ids_by_identifier: dict[str, str]
    effective_lookback: int


@dataclass(frozen=True)
class SeriesPlanNode:
    kind: PlanNodeKind
    identifier: str
    inputs: tuple[int, ...] = ()
    value: float | int | None = None


@dataclass(frozen=True)
class SeriesExecutionPlan:
    nodes: tuple[SeriesPlanNode, ...]
    root: int
    field_names: tuple[str, ...]
    effective_lookback: int


def build_series_execution_plan(compiled: CompiledAlphaLike) -> SeriesExecutionPlan:
    nodes: list[SeriesPlanNode] = []

    def append(node: Mapping[str, object]) -> int:
        kind = node["kind"]
        if kind == "number":
            nodes.append(SeriesPlanNode(kind="number", identifier="number", value=node["value"]))
        elif kind == "field":
            nodes.append(SeriesPlanNode(kind="field", identifier=str(node["field_id"])))
        elif kind == "unary":
            operand = append(_mapping(node["operand"]))
            nodes.append(
                SeriesPlanNode(
                    kind="unary",
                    identifier=str(node["operator"]),
                    inputs=(operand,),
                )
            )
        elif kind == "binary":
            left = append(_mapping(node["left"]))
            right = append(_mapping(node["right"]))
            nodes.append(
                SeriesPlanNode(
                    kind="binary",
                    identifier=str(node["operator"]),
                    inputs=(left, right),
                )
            )
        elif kind == "call":
            arguments = node["arguments"]
            if not isinstance(arguments, list):
                raise ValueError("compiled Alpha call arguments are invalid")
            inputs = tuple(append(_mapping(argument)) for argument in arguments)
            nodes.append(
                SeriesPlanNode(
                    kind="builtin",
                    identifier=str(node["identifier"]),
                    inputs=inputs,
                )
            )
        else:
            raise ValueError(f"compiled Alpha node kind is invalid: {kind}")
        return len(nodes) - 1

    root = append(compiled.expression)
    return SeriesExecutionPlan(
        nodes=tuple(nodes),
        root=root,
        field_names=tuple(sorted(compiled.field_ids_by_identifier.values())),
        effective_lookback=compiled.effective_lookback,
    )


def evaluate_series_execution_plan(
    plan: SeriesExecutionPlan,
    values_by_field: dict[str, list[float | None] | NumericSeries],
    *,
    length: int | None = None,
) -> list[float | None]:
    lengths = {len(values_by_field[field]) for field in plan.field_names}
    if len(lengths) > 1:
        raise ValueError("all Alpha input series must have the same length")
    inferred_length = lengths.pop() if lengths else None
    if length is not None and inferred_length is not None and length != inferred_length:
        raise ValueError("explicit Alpha series length does not match field inputs")
    result_length = (
        length if length is not None else (1 if inferred_length is None else inferred_length)
    )
    values: list[PlanValue] = []
    builtins = {definition.identifier: definition for definition in BUILTIN_DEFINITIONS}

    for node in plan.nodes:
        if node.kind == "number":
            assert node.value is not None
            values.append(node.value)
        elif node.kind == "field":
            values.append(
                tuple(_finite_or_missing(value) for value in values_by_field[node.identifier])
            )
        elif node.kind == "unary":
            values.append(_unary(values[node.inputs[0]]))
        elif node.kind == "binary":
            values.append(
                _binary(
                    node.identifier,
                    values[node.inputs[0]],
                    values[node.inputs[1]],
                    result_length,
                )
            )
        else:
            arguments = tuple(values[index] for index in node.inputs)
            values.append(builtins[node.identifier].evaluator(arguments))

    result = values[plan.root]
    if not isinstance(result, tuple):
        result = _broadcast(result, result_length)
    if len(result) != result_length:
        raise ValueError("Alpha execution plan produced a misaligned Numeric Series")
    return list(result)


def evaluate_series_execution_matrix(
    plan: SeriesExecutionPlan,
    instrument_ids: Iterable[str],
    inputs_for_instrument: Callable[
        [str],
        dict[str, list[float | None] | NumericSeries],
    ],
    *,
    length: int,
) -> dict[str, list[float | None]]:
    return {
        instrument_id: evaluate_series_execution_plan(
            plan,
            inputs_for_instrument(instrument_id),
            length=length,
        )
        for instrument_id in instrument_ids
    }


def _unary(value: PlanValue) -> PlanValue:
    if value is None:
        return None
    if isinstance(value, tuple):
        return tuple(None if item is None else _finite_or_missing(-item) for item in value)
    return _finite_or_missing(-float(value))


def _binary(
    identifier: str,
    left: PlanValue,
    right: PlanValue,
    length: int,
) -> NumericSeries:
    left_series = _broadcast(left, length)
    right_series = _broadcast(right, length)
    result: list[float | None] = []
    for left_value, right_value in zip(left_series, right_series, strict=True):
        if left_value is None or right_value is None:
            result.append(None)
            continue
        if identifier == "add":
            value = left_value + right_value
        elif identifier == "subtract":
            value = left_value - right_value
        elif identifier == "multiply":
            value = left_value * right_value
        else:
            value = math.nan if right_value == 0.0 else left_value / right_value
        result.append(_finite_or_missing(value))
    return tuple(result)


def _broadcast(value: PlanValue, length: int) -> NumericSeries:
    if isinstance(value, tuple):
        if len(value) != length:
            raise ValueError("Alpha execution plan input alignment is invalid")
        return value
    if value is None:
        return (None,) * length
    return (float(value),) * length


def _finite_or_missing(value: float | None) -> float | None:
    if value is None:
        return None
    projected = float(value)
    return projected if math.isfinite(projected) else None


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("compiled Alpha child node is invalid")
    return value
