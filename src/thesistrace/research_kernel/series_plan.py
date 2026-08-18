from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

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
                    if (value := _series_item(_matrix_value(child, instrument_id), index, length))
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


def evaluate_columnar_execution_matrix(
    plan: SeriesExecutionPlan,
    instruments: tuple[str, ...],
    sessions: tuple[str, ...],
    field_matrices: Mapping[str, np.ndarray],
    universe_members: Mapping[str, tuple[str, ...]],
    *,
    cancellation_check: Callable[[], None],
) -> np.ndarray:
    shape = (len(instruments), len(sessions))
    if any(matrix.shape != shape for matrix in field_matrices.values()):
        raise ValueError("columnar Alpha fields are misaligned")
    values: list[float | int | np.ndarray | None] = []
    remaining = [0] * len(plan.nodes)
    for node in plan.nodes:
        cancellation_check()
        for input_index in node.inputs:
            remaining[input_index] += 1
    builtins = {definition.identifier: definition for definition in BUILTIN_DEFINITIONS}
    instrument_positions = {instrument_id: index for index, instrument_id in enumerate(instruments)}

    for node in plan.nodes:
        if node.kind == "number":
            value: float | int | np.ndarray | None = node.value
        elif node.kind == "field":
            value = field_matrices[node.identifier]
        elif node.kind == "unary":
            operand = _columnar_array(values[node.inputs[0]], shape)
            value = np.where(np.isfinite(operand), -operand, np.nan)
        elif node.kind == "binary":
            left = _columnar_array(values[node.inputs[0]], shape)
            right = _columnar_array(values[node.inputs[1]], shape)
            valid = np.isfinite(left) & np.isfinite(right)
            if node.identifier == "divide":
                valid &= right != 0.0
            value = np.full(shape, np.nan, dtype=np.float64)
            operation = {
                "add": np.add,
                "subtract": np.subtract,
                "multiply": np.multiply,
                "divide": np.divide,
            }[node.identifier]
            with np.errstate(all="ignore"):
                operation(left, right, out=value, where=valid)
        elif node.identifier == "cs_rank":
            child = _columnar_array(values[node.inputs[0]], shape)
            value = _columnar_cross_section_rank(
                child,
                instrument_positions,
                sessions,
                universe_members,
                cancellation_check,
            )
        elif node.identifier == "pct_change":
            series = _columnar_array(values[node.inputs[0]], shape)
            window = values[node.inputs[1]]
            if not isinstance(window, int):
                raise ValueError("pct_change window is invalid")
            value = _columnar_pct_change(series, window)
        else:
            arguments = tuple(values[input_index] for input_index in node.inputs)
            rows = [
                _evaluate_columnar_builtin_row(
                    builtins[node.identifier].evaluator,
                    arguments,
                    instrument_index,
                    len(sessions),
                )
                for instrument_index in range(len(instruments))
            ]
            value = np.asarray(rows, dtype=np.float64)
            if value.shape != shape:
                raise ValueError("columnar Alpha builtin produced a misaligned result")
        values.append(value)
        cancellation_check()
        for input_index in node.inputs:
            remaining[input_index] -= 1
            if remaining[input_index] == 0 and input_index != plan.root:
                values[input_index] = None
    return _columnar_array(values[plan.root], shape)


def _columnar_pct_change(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 0:
        raise ValueError("pct_change window is invalid")
    result = np.full(values.shape, np.nan, dtype=np.float64)
    if window >= values.shape[1]:
        return result
    current = values[:, window:]
    prior = values[:, :-window]
    valid = np.isfinite(current) & np.isfinite(prior) & (prior != 0.0)
    with np.errstate(all="ignore"):
        np.divide(current, prior, out=result[:, window:], where=valid)
        np.subtract(result[:, window:], 1.0, out=result[:, window:], where=valid)
    result[:, window:][~valid] = np.nan
    return result


def _columnar_cross_section_rank(
    values: np.ndarray,
    instrument_positions: Mapping[str, int],
    sessions: tuple[str, ...],
    universe_members: Mapping[str, tuple[str, ...]],
    cancellation_check: Callable[[], None],
) -> np.ndarray:
    ranked = np.full(values.shape, np.nan, dtype=np.float64)
    for session_index, session in enumerate(sessions):
        cancellation_check()
        positions = np.fromiter(
            (
                instrument_positions[instrument_id]
                for instrument_id in universe_members.get(session, ())
                if instrument_id in instrument_positions
            ),
            dtype=np.intp,
        )
        if positions.size == 0:
            continue
        finite_mask = np.isfinite(values[positions, session_index])
        finite_positions = positions[finite_mask]
        finite_values = values[finite_positions, session_index]
        if finite_positions.size == 0:
            continue
        if finite_positions.size == 1:
            ranked[finite_positions[0], session_index] = 0.5
            continue
        _unique, inverse, counts = np.unique(
            finite_values,
            return_inverse=True,
            return_counts=True,
        )
        starts = np.cumsum(counts) - counts
        group_ranks = ((starts + starts + counts - 1) / 2) / (finite_positions.size - 1)
        ranked[finite_positions, session_index] = group_ranks[inverse]
    return ranked


def _evaluate_columnar_builtin_row(
    evaluator,
    arguments: tuple[float | int | np.ndarray | None, ...],
    instrument_index: int,
    length: int,
) -> tuple[float, ...]:
    projected = tuple(
        (
            tuple(
                None if not math.isfinite(value) else float(value)
                for value in argument[instrument_index]
            )
            if isinstance(argument, np.ndarray)
            else argument
        )
        for argument in arguments
    )
    result = evaluator(projected)
    series = _broadcast(result, length)
    return tuple(math.nan if value is None else float(value) for value in series)


def _columnar_array(
    value: float | int | np.ndarray | None,
    shape: tuple[int, int],
) -> np.ndarray:
    if isinstance(value, np.ndarray):
        if value.shape != shape:
            raise ValueError("columnar Alpha node is misaligned")
        return value
    fill = math.nan if value is None else float(value)
    return np.full(shape, fill, dtype=np.float64)


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
