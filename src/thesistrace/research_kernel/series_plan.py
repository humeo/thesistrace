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
class ExecutableAlpha:
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
    universe_members: Mapping[str, tuple[str, ...]] | None = None,
    sessions: tuple[str, ...] | None = None,
) -> dict[str, list[float | None]]:
    instruments = tuple(instrument_ids)
    inputs = {instrument_id: inputs_for_instrument(instrument_id) for instrument_id in instruments}
    if not any(node.kind == "builtin" and node.identifier == "cs_rank" for node in plan.nodes):
        return {
            instrument_id: evaluate_series_execution_plan(
                plan, inputs[instrument_id], length=length
            )
            for instrument_id in instruments
        }
    if sessions is None or len(sessions) != length or universe_members is None:
        raise ValueError("cs_rank execution requires aligned Research Sessions and Universe")
    values: list[PlanValue | dict[str, PlanValue]] = []
    builtins = {definition.identifier: definition for definition in BUILTIN_DEFINITIONS}
    for node in plan.nodes:
        if node.kind == "number":
            values.append(node.value)
        elif node.kind == "field":
            values.append(
                {
                    instrument_id: tuple(
                        _finite_or_missing(value)
                        for value in inputs[instrument_id][node.identifier]
                    )
                    for instrument_id in instruments
                }
            )
        elif node.kind == "unary":
            values.append(_matrix_map(values[node.inputs[0]], _unary, instruments))
        elif node.kind == "binary":
            values.append(
                {
                    instrument_id: _binary(
                        node.identifier,
                        _matrix_value(values[node.inputs[0]], instrument_id),
                        _matrix_value(values[node.inputs[1]], instrument_id),
                        length,
                    )
                    for instrument_id in instruments
                }
            )
        elif node.identifier == "cs_rank":
            child = values[node.inputs[0]]
            ranked = {instrument_id: [None] * length for instrument_id in instruments}
            for index, session in enumerate(sessions):
                finite = sorted(
                    (
                        instrument_id,
                        float(value),
                    )
                    for instrument_id in universe_members.get(session, ())
                    if (
                        value := _series_item(_matrix_value(child, instrument_id), index, length)
                    )
                    is not None
                    and math.isfinite(float(value))
                )
                for instrument_id, rank in _cross_section_ranks(finite).items():
                    ranked[instrument_id][index] = rank
            values.append(
                {instrument_id: tuple(series) for instrument_id, series in ranked.items()}
            )
        else:
            values.append(
                {
                    instrument_id: builtins[node.identifier].evaluator(
                        tuple(
                            _matrix_value(values[input_index], instrument_id)
                            for input_index in node.inputs
                        )
                    )
                    for instrument_id in instruments
                }
            )
    root = values[plan.root]
    return {
        instrument_id: list(_broadcast(_matrix_value(root, instrument_id), length))
        for instrument_id in instruments
    }


def _matrix_value(value: PlanValue | dict[str, PlanValue], instrument_id: str) -> PlanValue:
    return value[instrument_id] if isinstance(value, dict) else value


def _matrix_map(
    value: PlanValue | dict[str, PlanValue],
    operation: Callable[[PlanValue], PlanValue],
    instruments: tuple[str, ...],
) -> dict[str, PlanValue]:
    return {
        instrument_id: operation(_matrix_value(value, instrument_id))
        for instrument_id in instruments
    }


def _series_item(value: PlanValue, index: int, length: int) -> float | None:
    return _broadcast(value, length)[index]


def _cross_section_ranks(values: list[tuple[str, float]]) -> dict[str, float]:
    if len(values) == 1:
        return {values[0][0]: 0.5}
    ordered = sorted(values, key=lambda item: (item[1], item[0]))
    result: dict[str, float] = {}
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][1] == ordered[position][1]:
            end += 1
        rank = ((position + end - 1) / 2) / (len(ordered) - 1)
        result.update((instrument_id, rank) for instrument_id, _ in ordered[position:end])
        position = end
    return result


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
