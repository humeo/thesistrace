from __future__ import annotations

import ast
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

type AlphaExpression = str | Mapping[str, object]
type OperandRule = Literal["numeric", "window"]


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
    tree: ast.Expression
    field_names: tuple[str, ...]
    effective_lookback: int


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
    authorable_field_ids: Collection[str],
) -> ParsedAlpha:
    allowed_fields = frozenset(authorable_field_ids)
    body, effective_lookback, fields = _build_node(
        expression,
        location="alpha.expression",
        expected_rule="numeric",
        allowed_fields=allowed_fields,
    )
    if effective_lookback > 252:
        _reject(
            "LOOKBACK_EXCEEDS_LIMIT",
            "alpha.expression",
            f"effective lookback {effective_lookback} exceeds 252",
        )
    return ParsedAlpha(
        expression=dict(expression),
        tree=ast.fix_missing_locations(ast.Expression(body=body)),
        field_names=tuple(sorted(fields)),
        effective_lookback=effective_lookback,
    )


def _build_node(
    node: object,
    *,
    location: str,
    expected_rule: OperandRule,
    allowed_fields: frozenset[str],
) -> tuple[ast.expr, int, set[str]]:
    if expected_rule == "window":
        return _build_window(node, location)
    if not isinstance(node, Mapping):
        _reject("MALFORMED_NODE", location, "expression node must be an object")

    keys = set(node)
    if keys == {"field_id"}:
        field_id = node["field_id"]
        if not isinstance(field_id, str):
            _reject("MALFORMED_NODE", location, "field_id must be a string")
        if field_id not in allowed_fields:
            _reject("UNKNOWN_FIELD", location, f"unknown field_id: {field_id}")
        return ast.Name(id=f"f{field_id}", ctx=ast.Load()), 0, {field_id}

    if keys == {"literal"}:
        value = node["literal"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _reject("MALFORMED_NODE", location, "literal must be numeric")
        if not math.isfinite(float(value)):
            _reject("NON_FINITE_LITERAL", location, "literal must be finite")
        return ast.Constant(value=value), 0, set()

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
            allowed_fields=allowed_fields,
        )
        for index, (operand, rule) in enumerate(zip(operands, operator.operand_rules, strict=True))
    ]
    child_lookback = max((item[1] for item in built), default=0)
    fields = set().union(*(item[2] for item in built))
    if operator.kind == "historical":
        effective_lookback = child_lookback + int(operands[1]["literal"])
    elif operator.kind == "rolling":
        effective_lookback = child_lookback + int(operands[1]["literal"]) - 1
    else:
        effective_lookback = child_lookback
    return _operator_ast(operator_id, [item[0] for item in built]), effective_lookback, fields


def _build_window(node: object, location: str) -> tuple[ast.expr, int, set[str]]:
    if not isinstance(node, Mapping) or set(node) != {"literal"}:
        _reject("INVALID_OPERAND", location, "window operand must be an integer literal")
    value = node["literal"]
    if isinstance(value, bool) or not isinstance(value, int):
        _reject("INVALID_OPERAND", location, "window operand must be an integer literal")
    if value < 1 or value > 252:
        _reject("WINDOW_OUT_OF_RANGE", location, "window must be between 1 and 252")
    return ast.Constant(value=value), 0, set()


def _operator_ast(operator_id: str, operands: list[ast.expr]) -> ast.expr:
    binary = {
        "add": ast.Add,
        "subtract": ast.Sub,
        "multiply": ast.Mult,
        "divide": ast.Div,
    }
    if operator_type := binary.get(operator_id):
        return ast.BinOp(left=operands[0], op=operator_type(), right=operands[1])
    if operator_id == "negate":
        return ast.UnaryOp(op=ast.USub(), operand=operands[0])
    return ast.Call(func=ast.Name(id=operator_id, ctx=ast.Load()), args=operands, keywords=[])


def _reject(reason_code: str, location: str, message: str) -> None:
    raise AlphaValidationError(
        [AlphaValidationIssue(reason_code=reason_code, location=location, message=message)]
    )
