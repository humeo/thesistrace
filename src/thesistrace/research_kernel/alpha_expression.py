from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from thesistrace.research_kernel.alpha_builtins import BUILTIN_DEFINITIONS

type AlphaExpression = Mapping[str, object]
type OperandRule = Literal["numeric", "window"]

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


@dataclass(frozen=True)
class OperatorDefinition:
    operator_id: str
    kind: Literal["arithmetic", "scalar", "historical", "rolling"]
    operand_rules: tuple[OperandRule, ...]

    @property
    def rolling_bounds(self) -> dict[str, int] | None:
        if "window" not in self.operand_rules:
            return None
        return {"minimum": 1, "maximum": 252}

    def public(self) -> dict[str, object]:
        return {
            "operator_id": self.operator_id,
            "kind": self.kind,
            "arity": len(self.operand_rules),
            "operand_rules": list(self.operand_rules),
            "result_type": "numeric",
            "rolling_bounds": self.rolling_bounds,
        }


OPERATORS = (
    OperatorDefinition("add", "arithmetic", ("numeric", "numeric")),
    OperatorDefinition("subtract", "arithmetic", ("numeric", "numeric")),
    OperatorDefinition("multiply", "arithmetic", ("numeric", "numeric")),
    OperatorDefinition("divide", "arithmetic", ("numeric", "numeric")),
    OperatorDefinition("negate", "arithmetic", ("numeric",)),
    OperatorDefinition("abs", "scalar", ("numeric",)),
    OperatorDefinition("log", "scalar", ("numeric",)),
    OperatorDefinition("sign", "scalar", ("numeric",)),
    OperatorDefinition("lag", "historical", ("numeric", "window")),
    OperatorDefinition("delta", "historical", ("numeric", "window")),
    OperatorDefinition("pct_change", "historical", ("numeric", "window")),
    OperatorDefinition("ts_mean", "rolling", ("numeric", "window")),
    OperatorDefinition("ts_sum", "rolling", ("numeric", "window")),
    OperatorDefinition("ts_std", "rolling", ("numeric", "window")),
    OperatorDefinition("ts_min", "rolling", ("numeric", "window")),
    OperatorDefinition("ts_max", "rolling", ("numeric", "window")),
)
OPERATOR_BY_ID = {operator.operator_id: operator for operator in OPERATORS}
SCALAR_OPERATOR_IDS = frozenset(
    operator.operator_id for operator in OPERATORS if operator.kind == "scalar"
)
HISTORICAL_OPERATOR_IDS = frozenset(
    operator.operator_id for operator in OPERATORS if operator.kind == "historical"
)
ROLLING_OPERATOR_IDS = frozenset(
    operator.operator_id for operator in OPERATORS if operator.kind == "rolling"
)
WINDOW_OPERATOR_IDS = HISTORICAL_OPERATOR_IDS | ROLLING_OPERATOR_IDS


def operator_catalog() -> dict[str, object]:
    return {
        "semantic_version": "1.0.0",
        "operators": [operator.public() for operator in OPERATORS],
    }


def validate_normalized_alpha(
    expression: Mapping[str, object],
    *,
    field_bindings: Mapping[str, str],
) -> ParsedAlpha:
    expression, effective_lookback, estimated_work, fields, field_ids = _build_node(
        expression,
        location="alpha.expression",
        expected_rule="numeric",
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


def estimate_alpha_run_work(
    formula_work: int,
    *,
    research_session_count: int,
    universe_instrument_count: int,
) -> int:
    if formula_work < 1 or research_session_count < 1 or universe_instrument_count < 0:
        raise ValueError("Alpha Run work dimensions are invalid")
    return formula_work * research_session_count * universe_instrument_count


def _build_node(
    node: object,
    *,
    location: str,
    expected_rule: OperandRule,
    field_bindings: Mapping[str, str],
) -> tuple[dict[str, object], int, int, set[str], set[str]]:
    if expected_rule == "window":
        expression, lookback, work, fields = _build_window(node, location)
        return expression, lookback, work, fields, set()
    if not isinstance(node, Mapping):
        _reject("MALFORMED_NODE", location, "expression node must be an object")

    keys = set(node)
    if keys == {"field_id"}:
        field_id = node["field_id"]
        if not isinstance(field_id, str):
            _reject("MALFORMED_NODE", location, "field_id must be a string")
        evaluation_name = field_bindings.get(field_id)
        if evaluation_name is None:
            _reject("UNKNOWN_FIELD", location, f"unknown field_id: {field_id}")
        return {"kind": "field", "field_id": field_id}, 0, 1, {evaluation_name}, {field_id}

    if keys == {"literal"}:
        value = node["literal"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _reject("MALFORMED_NODE", location, "literal must be numeric")
        try:
            finite_value = math.isfinite(float(value))
        except OverflowError:
            finite_value = False
        if not finite_value:
            _reject("NON_FINITE_LITERAL", location, "literal must be finite")
        return {"kind": "number", "value": value}, 0, 1, set(), set()

    if keys != {"operator_id", "operands"}:
        _reject("MALFORMED_NODE", location, "node has unknown or missing properties")
    operator_id = node["operator_id"]
    operands = node["operands"]
    if not isinstance(operator_id, str):
        _reject("MALFORMED_NODE", location, "operator_id must be a string")
    operator = OPERATOR_BY_ID.get(operator_id)
    if operator is None:
        _reject("UNKNOWN_OPERATOR", location, f"unknown operator_id: {operator_id}")
    if not isinstance(operands, list):
        _reject("MALFORMED_NODE", location, "operands must be an array")
    if len(operands) != len(operator.operand_rules):
        _reject(
            "INVALID_ARITY",
            location,
            f"{operator_id} requires {len(operator.operand_rules)} operands",
        )

    built = [
        _build_node(
            operand,
            location=f"{location}.operands[{index}]",
            expected_rule=rule,
            field_bindings=field_bindings,
        )
        for index, (operand, rule) in enumerate(zip(operands, operator.operand_rules, strict=True))
    ]
    child_lookback = max((item[1] for item in built), default=0)
    child_work = sum(item[2] for item in built)
    fields = set().union(*(item[3] for item in built))
    field_ids = set().union(*(item[4] for item in built))
    if operator.kind == "historical":
        effective_lookback = child_lookback + int(operands[1]["literal"])
    elif operator.kind == "rolling":
        effective_lookback = child_lookback + int(operands[1]["literal"]) - 1
    else:
        effective_lookback = child_lookback
    if operator.kind == "arithmetic":
        estimated_work = child_work + 1
    else:
        builtin = next(
            definition for definition in BUILTIN_DEFINITIONS if definition.identifier == operator_id
        )
        window = int(operands[1]["literal"]) if operator_id in WINDOW_OPERATOR_IDS else None
        estimated_work = builtin.estimated_work(child_work, window)
    return (
        _operator_expression(operator_id, [item[0] for item in built]),
        effective_lookback,
        estimated_work,
        fields,
        field_ids,
    )


def _build_window(node: object, location: str) -> tuple[dict[str, object], int, int, set[str]]:
    if not isinstance(node, Mapping) or set(node) != {"literal"}:
        _reject("INVALID_OPERAND", location, "window operand must be an integer literal")
    value = node["literal"]
    if isinstance(value, bool) or not isinstance(value, int):
        _reject("INVALID_OPERAND", location, "window operand must be an integer literal")
    if value < 1 or value > 252:
        _reject("WINDOW_OUT_OF_RANGE", location, "window must be between 1 and 252")
    return {"kind": "number", "value": value}, 0, 1, set()


def _operator_expression(
    operator_id: str,
    operands: list[dict[str, object]],
) -> dict[str, object]:
    if operator_id in {"add", "subtract", "multiply", "divide"}:
        return {
            "kind": "binary",
            "operator": operator_id,
            "left": operands[0],
            "right": operands[1],
        }
    if operator_id == "negate":
        return {"kind": "unary", "operator": "negate", "operand": operands[0]}
    return {"kind": "call", "identifier": operator_id, "arguments": operands}


def _reject(reason_code: str, location: str, message: str) -> None:
    raise AlphaValidationError(
        [AlphaValidationIssue(reason_code=reason_code, location=location, message=message)]
    )
