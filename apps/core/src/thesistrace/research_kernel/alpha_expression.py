from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from thesistrace.research_kernel.alpha_builtins import BUILTIN_DEFINITIONS

type AlphaExpression = Mapping[str, object]

MAX_ALPHA_RUN_ESTIMATED_WORK = 15_000_000


@dataclass(frozen=True)
class AlphaValidationIssue:
    reason_code: str
    location: str
    message: str


class AlphaValidationError(ValueError):
    def __init__(self, issues: list[AlphaValidationIssue]) -> None:
        super().__init__("alpha expression is invalid")
        self.issues = issues


@dataclass(frozen=True)
class ParsedAlpha:
    expression: AlphaExpression
    field_names: tuple[str, ...]
    field_ids: tuple[str, ...]
    field_ids_by_identifier: dict[str, str]
    effective_lookback: int
    estimated_work: int


def validate_normalized_alpha(
    expression: Mapping[str, object],
    *,
    field_bindings: Mapping[str, str],
) -> ParsedAlpha:
    expression, effective_lookback, estimated_work, fields, field_ids = _validate_compiled_node(
        expression,
        location="alpha.expression",
        field_bindings=field_bindings,
    )
    if effective_lookback > 252:
        _reject(
            "LOOKBACK_EXCEEDS_LIMIT",
            "alpha.expression",
            f"effective lookback {effective_lookback} exceeds 252",
        )
    return ParsedAlpha(
        expression=expression,
        field_names=tuple(sorted(fields)),
        field_ids=tuple(sorted(field_ids)),
        field_ids_by_identifier={
            identifier: field_id
            for field_id, identifier in field_bindings.items()
            if field_id in field_ids
        },
        effective_lookback=effective_lookback,
        estimated_work=estimated_work,
    )


def _validate_compiled_node(
    node: Mapping[str, object],
    *,
    location: str,
    field_bindings: Mapping[str, str],
) -> tuple[dict[str, object], int, int, set[str], set[str]]:
    kind = node.get("kind")
    if kind == "field":
        if set(node) != {"kind", "field_id"}:
            _reject("INVALID_NODE", location, "Alpha field node is malformed")
        field_id = node.get("field_id")
        if not isinstance(field_id, str) or field_id not in field_bindings:
            _reject("UNKNOWN_FIELD", location, f"unknown Alpha field: {field_id}")
        return dict(node), 0, 1, {field_bindings[field_id]}, {field_id}
    if kind == "number":
        if set(node) != {"kind", "value"}:
            _reject("INVALID_NODE", location, "Alpha number node is malformed")
        value = node.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            _reject("INVALID_LITERAL", location, "Alpha number must be finite")
        return dict(node), 0, 1, set(), set()
    if kind == "unary":
        if set(node) != {"kind", "operator", "operand"}:
            _reject("INVALID_NODE", location, "Alpha unary node is malformed")
        if node.get("operator") != "negate" or not isinstance(node.get("operand"), Mapping):
            _reject("INVALID_OPERATOR", location, "Alpha unary operator is invalid")
        child, lookback, work, fields, field_ids = _validate_compiled_node(
            node["operand"],
            location=f"{location}.operand",
            field_bindings=field_bindings,
        )
        return (
            {"kind": "unary", "operator": "negate", "operand": child},
            lookback,
            work + 1,
            fields,
            field_ids,
        )
    if kind == "binary":
        if set(node) != {"kind", "operator", "left", "right"}:
            _reject("INVALID_NODE", location, "Alpha binary node is malformed")
        operator = node.get("operator")
        left = node.get("left")
        right = node.get("right")
        if (
            operator not in {"add", "subtract", "multiply", "divide"}
            or not isinstance(left, Mapping)
            or not isinstance(right, Mapping)
        ):
            _reject("INVALID_OPERATOR", location, "Alpha binary operator is invalid")
        left_node, left_lookback, left_work, left_fields, left_ids = _validate_compiled_node(
            left, location=f"{location}.left", field_bindings=field_bindings
        )
        right_node, right_lookback, right_work, right_fields, right_ids = _validate_compiled_node(
            right, location=f"{location}.right", field_bindings=field_bindings
        )
        return (
            {"kind": "binary", "operator": operator, "left": left_node, "right": right_node},
            max(left_lookback, right_lookback),
            left_work + right_work + 1,
            left_fields | right_fields,
            left_ids | right_ids,
        )
    if kind == "call":
        if set(node) != {"kind", "identifier", "arguments"}:
            _reject("INVALID_NODE", location, "Alpha call node is malformed")
        identifier = node.get("identifier")
        arguments = node.get("arguments")
        definition = next(
            (item for item in BUILTIN_DEFINITIONS if item.identifier == identifier),
            None,
        )
        if definition is None or not isinstance(arguments, list):
            _reject("INVALID_OPERATOR", location, f"unknown Alpha builtin: {identifier}")
        if len(arguments) != len(definition.parameters):
            _reject("INVALID_ARITY", location, f"Alpha builtin {identifier} has invalid arity")
        compiled_arguments: list[dict[str, object]] = []
        lookbacks: list[int] = []
        work = 1
        fields: set[str] = set()
        field_ids: set[str] = set()
        window: int | None = None
        for index, (argument, parameter) in enumerate(
            zip(arguments, definition.parameters, strict=True)
        ):
            if not isinstance(argument, Mapping):
                _reject("INVALID_OPERAND", location, "Alpha builtin argument is invalid")
            if parameter.rule == "window":
                value = argument.get("value") if argument.get("kind") == "number" else None
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 252:
                    _reject(
                        "INVALID_WINDOW",
                        f"{location}.arguments[{index}]",
                        "Alpha window must be an integer from 1 to 252",
                    )
                window = value
                compiled_arguments.append(dict(argument))
                continue
            child, child_lookback, child_work, child_fields, child_ids = _validate_compiled_node(
                argument,
                location=f"{location}.arguments[{index}]",
                field_bindings=field_bindings,
            )
            compiled_arguments.append(child)
            lookbacks.append(child_lookback)
            work += child_work
            fields |= child_fields
            field_ids |= child_ids
        child_lookback = max(lookbacks, default=0)
        return (
            {"kind": "call", "identifier": identifier, "arguments": compiled_arguments},
            definition.effective_lookback(child_lookback, window),
            definition.estimated_work(work, window),
            fields,
            field_ids,
        )
    _reject("INVALID_NODE", location, "Alpha expression must use the compiled Formula IR")


def estimate_alpha_run_work(
    formula_work: int,
    *,
    research_session_count: int,
    universe_instrument_count: int,
) -> int:
    if formula_work < 1 or research_session_count < 1 or universe_instrument_count < 0:
        raise ValueError("Alpha Run work dimensions are invalid")
    return formula_work * research_session_count * universe_instrument_count


def _reject(reason_code: str, location: str, message: str) -> None:
    raise AlphaValidationError(
        [AlphaValidationIssue(reason_code=reason_code, location=location, message=message)]
    )
