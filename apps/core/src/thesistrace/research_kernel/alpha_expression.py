from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from thesistrace.research_kernel.alpha_builtins import BUILTIN_DEFINITIONS
from thesistrace.research_kernel.common_inputs import (
    CLOSE_FIELD_ID,
    COMMON_INPUT_WORK,
    validate_common_reference,
)
from thesistrace.research_kernel.expression_limits import (
    MAX_ESTIMATED_WORK,
    MAX_EXPRESSION_DEPTH,
    MAX_EXPRESSION_NODES,
)
from thesistrace.research_kernel.expression_types import (
    ARITHMETIC_OPERATORS,
    BOOLEAN_OPERATORS,
    BOOLEAN_TYPES,
    COMPARISON_OPERATORS,
    NUMERIC_TYPES,
    ValueType,
    binary_result_type,
    conditional_result_type,
    unary_result_type,
)

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
    return _validate_normalized_expression(
        expression, field_bindings=field_bindings, expected_type=ValueType.NUMERIC_SERIES,
    )


def validate_normalized_exposure(expression: Mapping[str, object]) -> ParsedAlpha:
    return _validate_normalized_expression(
        expression, field_bindings={}, expected_type=ValueType.NUMBER,
    )


def _validate_normalized_expression(
    expression: Mapping[str, object],
    *,
    field_bindings: Mapping[str, str],
    expected_type: ValueType,
) -> ParsedAlpha:
    pending = [(expression, 1)]
    count = 0
    while pending:
        node, depth = pending.pop()
        # Common IR stores its literal as metadata, but it remains a source expression node.
        literal_count = int(node.get("kind") == "common" and node.get("industry_code") is not None)
        count += 1 + literal_count
        if depth + literal_count > MAX_EXPRESSION_DEPTH:
            _reject("EXPRESSION_TOO_DEEP", "alpha.expression", "Expression exceeds depth limit")
        if count > MAX_EXPRESSION_NODES:
            _reject(
                "TOO_MANY_EXPRESSION_NODES", "alpha.expression", "Expression exceeds node limit"
            )
        for value in node.values():
            if isinstance(value, Mapping):
                pending.append((value, depth + 1))
            elif isinstance(value, list):
                pending.extend((child, depth + 1) for child in value if isinstance(child, Mapping))
    expression, effective_lookback, estimated_work, fields, field_ids, result_type = (
        _validate_compiled_node(
            expression,
            location="alpha.expression",
            field_bindings=field_bindings,
        )
    )
    if estimated_work > MAX_ESTIMATED_WORK:
        _reject("WORK_EXCEEDS_LIMIT", "alpha.expression", "Expression exceeds work limit")
    if result_type is not expected_type:
        _reject(
            "ROOT_MUST_BE_SERIES" if expected_type is ValueType.NUMERIC_SERIES
            else "EXPOSURE_MUST_BE_CONSTANT",
            "alpha.expression" if expected_type is ValueType.NUMERIC_SERIES
            else "exposure.expression",
            f"Expression must produce {expected_type.value}",
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
) -> tuple[dict[str, object], int, int, set[str], set[str], ValueType]:
    kind = node.get("kind")
    if kind == "common":
        try:
            reference = validate_common_reference(node)
        except ValueError as error:
            _reject("INVALID_COMMON_INPUT", location, str(error))
        if CLOSE_FIELD_ID not in field_bindings:
            _reject("UNKNOWN_FIELD", location, "Common input requires adjusted Close")
        return (
            reference,
            1,
            COMMON_INPUT_WORK,
            {field_bindings[CLOSE_FIELD_ID]},
            {CLOSE_FIELD_ID},
            ValueType.COMMON_NUMERIC_SERIES,
        )
    if kind == "field":
        if set(node) != {"kind", "field_id"}:
            _reject("INVALID_NODE", location, "Alpha field node is malformed")
        field_id = node.get("field_id")
        if not isinstance(field_id, str) or field_id not in field_bindings:
            _reject("UNKNOWN_FIELD", location, f"unknown Alpha field: {field_id}")
        return dict(node), 0, 1, {field_bindings[field_id]}, {field_id}, ValueType.NUMERIC_SERIES
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
        return dict(node), 0, 1, set(), set(), ValueType.NUMBER
    if kind == "unary":
        if set(node) != {"kind", "operator", "operand"}:
            _reject("INVALID_NODE", location, "Alpha unary node is malformed")
        if node.get("operator") not in {"negate", "not"} or not isinstance(
            node.get("operand"), Mapping
        ):
            _reject("INVALID_OPERATOR", location, "Alpha unary operator is invalid")
        child, lookback, work, fields, field_ids, child_type = _validate_compiled_node(
            node["operand"],
            location=f"{location}.operand",
            field_bindings=field_bindings,
        )
        try:
            result_type = unary_result_type(node["operator"], child_type)
        except ValueError as error:
            _reject("TYPE_MISMATCH", location, str(error))
        return (
            {"kind": "unary", "operator": node["operator"], "operand": child},
            lookback,
            work + 1,
            fields,
            field_ids,
            result_type,
        )
    if kind == "binary":
        if set(node) != {"kind", "operator", "left", "right"}:
            _reject("INVALID_NODE", location, "Alpha binary node is malformed")
        operator = node.get("operator")
        left = node.get("left")
        right = node.get("right")
        if (
            operator not in ARITHMETIC_OPERATORS | COMPARISON_OPERATORS | BOOLEAN_OPERATORS
            or not isinstance(left, Mapping)
            or not isinstance(right, Mapping)
        ):
            _reject("INVALID_OPERATOR", location, "Alpha binary operator is invalid")
        left_node, left_lookback, left_work, left_fields, left_ids, left_type = (
            _validate_compiled_node(
                left, location=f"{location}.left", field_bindings=field_bindings
            )
        )
        right_node, right_lookback, right_work, right_fields, right_ids, right_type = (
            _validate_compiled_node(
                right, location=f"{location}.right", field_bindings=field_bindings
            )
        )
        try:
            result_type = binary_result_type(operator, left_type, right_type)
        except ValueError as error:
            _reject("TYPE_MISMATCH", location, str(error))
        return (
            {"kind": "binary", "operator": operator, "left": left_node, "right": right_node},
            max(left_lookback, right_lookback),
            left_work + right_work + 1,
            left_fields | right_fields,
            left_ids | right_ids,
            result_type,
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
        if definition.result_rule == "common_series":
            _reject("INVALID_COMMON_INPUT", location, "Common inputs require canonical references")
        if len(arguments) != len(definition.parameters):
            _reject("INVALID_ARITY", location, f"Alpha builtin {identifier} has invalid arity")
        compiled_arguments: list[dict[str, object]] = []
        lookbacks: list[int] = []
        argument_types: list[ValueType] = []
        work = 0
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
                work += 1
                argument_types.append(ValueType.WINDOW)
                continue
            child, child_lookback, child_work, child_fields, child_ids, child_type = (
                _validate_compiled_node(
                    argument,
                    location=f"{location}.arguments[{index}]",
                    field_bindings=field_bindings,
                )
            )
            allowed = (
                NUMERIC_TYPES
                if parameter.rule == "numeric"
                else {ValueType.NUMERIC_SERIES}
                if parameter.rule == "numeric_series"
                else {ValueType.NUMERIC_SERIES, ValueType.COMMON_NUMERIC_SERIES}
                if parameter.rule == "temporal_series"
                else BOOLEAN_TYPES
                if parameter.rule == "boolean"
                else None
            )
            if allowed is not None and child_type not in allowed:
                _reject("TYPE_MISMATCH", location, f"{identifier} requires {parameter.rule}")
            argument_types.append(child_type)
            compiled_arguments.append(child)
            lookbacks.append(child_lookback)
            work += child_work
            fields |= child_fields
            field_ids |= child_ids
        try:
            result_type = (
                conditional_result_type(*argument_types)
                if definition.result_rule == "conditional"
                else ValueType.NUMERIC_SERIES
                if definition.result_rule == "numeric_series"
                else argument_types[0]
            )
        except ValueError as error:
            _reject("TYPE_MISMATCH", location, str(error))
        child_lookback = max(lookbacks, default=0)
        return (
            {"kind": "call", "identifier": identifier, "arguments": compiled_arguments},
            definition.effective_lookback(child_lookback, window),
            definition.estimated_work(work, window),
            fields,
            field_ids,
            result_type,
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
