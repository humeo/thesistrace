from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

type AlphaExpression = Mapping[str, object]
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
    field_ids: tuple[str, ...]
    effective_lookback: int


COMPILED_ALPHA_FORMAT = "thesistrace-compiled-alpha"
COMPILED_ALPHA_VERSION = 1


@dataclass(frozen=True)
class OperatorDefinition:
    operator_id: str
    kind: Literal["arithmetic", "scalar", "historical", "rolling", "cross-sectional"]
    operand_rules: tuple[OperandRule, ...]
    lookback_rule: Literal["none", "historical", "rolling"] = "none"
    complexity: str = "linear-in-series-length"
    cross_section_evaluator: Callable[
        [Sequence[tuple[str, float]]], dict[str, float]
    ] | None = None

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
            "lookback_rule": self.lookback_rule,
            "complexity": self.complexity,
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
    OperatorDefinition("lag", "historical", ("numeric", "window"), "historical"),
    OperatorDefinition("delta", "historical", ("numeric", "window"), "historical"),
    OperatorDefinition("pct_change", "historical", ("numeric", "window"), "historical"),
    OperatorDefinition("ts_mean", "rolling", ("numeric", "window"), "rolling"),
    OperatorDefinition("ts_sum", "rolling", ("numeric", "window"), "rolling"),
    OperatorDefinition("ts_std", "rolling", ("numeric", "window"), "rolling"),
    OperatorDefinition("ts_min", "rolling", ("numeric", "window"), "rolling"),
    OperatorDefinition("ts_max", "rolling", ("numeric", "window"), "rolling"),
    OperatorDefinition(
        "cs_rank",
        "cross-sectional",
        ("numeric",),
        cross_section_evaluator=lambda values: _ascending_average_ordinal_rank(values),
    ),
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


def _ascending_average_ordinal_rank(
    values: Sequence[tuple[str, float]],
) -> dict[str, float]:
    if len(values) == 1:
        return {values[0][0]: 0.5}
    ordered = sorted(values, key=lambda item: (item[1], item[0]))
    ranked: dict[str, float] = {}
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][1] == ordered[position][1]:
            end += 1
        rank = ((position + end - 1) / 2) / (len(ordered) - 1)
        ranked.update((instrument_id, rank) for instrument_id, _value in ordered[position:end])
        position = end
    return ranked


def operator_catalog() -> dict[str, object]:
    return {
        "semantic_version": "1.1.0",
        "operators": [operator.public() for operator in OPERATORS],
    }


def validate_normalized_alpha(
    expression: Mapping[str, object],
    *,
    field_bindings: Mapping[str, str],
) -> ParsedAlpha:
    body, effective_lookback, fields, field_ids = _build_node(
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
        expression=dict(expression),
        tree=ast.fix_missing_locations(ast.Expression(body=body)),
        field_names=tuple(sorted(fields)),
        field_ids=tuple(sorted(field_ids)),
        effective_lookback=effective_lookback,
    )


def freeze_parsed_alpha(parsed: ParsedAlpha) -> dict[str, object]:
    """Freeze validated Alpha IR without retaining a live operator catalog."""
    return {
        "format": COMPILED_ALPHA_FORMAT,
        "version": COMPILED_ALPHA_VERSION,
        "expression": dict(parsed.expression),
        "execution_tree": _freeze_execution_node(parsed.tree.body),
        "field_names": list(parsed.field_names),
        "field_ids": list(parsed.field_ids),
        "effective_lookback": parsed.effective_lookback,
    }


def restore_compiled_alpha(value: Mapping[str, object]) -> ParsedAlpha:
    """Restore frozen execution IR without consulting the authoring catalog."""
    if set(value) != {
        "format",
        "version",
        "expression",
        "execution_tree",
        "field_names",
        "field_ids",
        "effective_lookback",
    } or (
        value.get("format") != COMPILED_ALPHA_FORMAT
        or value.get("version") != COMPILED_ALPHA_VERSION
    ):
        raise ValueError("compiled Alpha contract is invalid")
    expression = value.get("expression")
    field_names = value.get("field_names")
    field_ids = value.get("field_ids")
    lookback = value.get("effective_lookback")
    if (
        not isinstance(expression, Mapping)
        or not isinstance(field_names, list)
        or not all(isinstance(item, str) and item for item in field_names)
        or field_names != sorted(set(field_names))
        or not isinstance(field_ids, list)
        or not all(isinstance(item, str) and item for item in field_ids)
        or field_ids != sorted(set(field_ids))
        or isinstance(lookback, bool)
        or not isinstance(lookback, int)
        or not 0 <= lookback <= 252
    ):
        raise ValueError("compiled Alpha contract is invalid")
    tree, restored_names = _restore_execution_node(value.get("execution_tree"))
    if restored_names != set(field_names):
        raise ValueError("compiled Alpha fields are invalid")
    return ParsedAlpha(
        expression=dict(expression),
        tree=ast.fix_missing_locations(ast.Expression(body=tree)),
        field_names=tuple(field_names),
        field_ids=tuple(field_ids),
        effective_lookback=lookback,
    )


def _freeze_execution_node(node: ast.AST) -> dict[str, object]:
    if isinstance(node, ast.Name):
        return {"kind": "field", "evaluation_name": node.id[1:]}
    if isinstance(node, ast.Constant):
        return {"kind": "literal", "value": node.value}
    if isinstance(node, ast.UnaryOp):
        return {
            "kind": "operator",
            "operator_id": "negate",
            "operands": [_freeze_execution_node(node.operand)],
        }
    if isinstance(node, ast.BinOp):
        operator_id = {
            ast.Add: "add",
            ast.Sub: "subtract",
            ast.Mult: "multiply",
            ast.Div: "divide",
        }.get(type(node.op))
        if operator_id is None:
            raise ValueError("validated Alpha contains an unsupported execution node")
        return {
            "kind": "operator",
            "operator_id": operator_id,
            "operands": [
                _freeze_execution_node(node.left),
                _freeze_execution_node(node.right),
            ],
        }
    if isinstance(node, ast.Call):
        return {
            "kind": "operator",
            "operator_id": node.func.id,
            "operands": [_freeze_execution_node(operand) for operand in node.args],
        }
    raise ValueError("validated Alpha contains an unsupported execution node")


def _restore_execution_node(value: object) -> tuple[ast.expr, set[str]]:
    if not isinstance(value, Mapping):
        raise ValueError("compiled Alpha execution tree is invalid")
    kind = value.get("kind")
    if kind == "field" and set(value) == {"kind", "evaluation_name"}:
        name = value.get("evaluation_name")
        if not isinstance(name, str) or not name:
            raise ValueError("compiled Alpha field is invalid")
        return ast.Name(id=f"f{name}", ctx=ast.Load()), {name}
    if kind == "literal" and set(value) == {"kind", "value"}:
        literal = value.get("value")
        if isinstance(literal, bool) or not isinstance(literal, (int, float)):
            raise ValueError("compiled Alpha literal is invalid")
        return ast.Constant(value=literal), set()
    if kind != "operator" or set(value) != {"kind", "operator_id", "operands"}:
        raise ValueError("compiled Alpha execution tree is invalid")
    operator_id = value.get("operator_id")
    operands = value.get("operands")
    definition = OPERATOR_BY_ID.get(operator_id) if isinstance(operator_id, str) else None
    if (
        definition is None
        or not isinstance(operands, list)
        or len(operands) != len(definition.operand_rules)
    ):
        raise ValueError("compiled Alpha operator is invalid")
    restored = [_restore_execution_node(operand) for operand in operands]
    return (
        _operator_ast(operator_id, [item[0] for item in restored]),
        set().union(*(item[1] for item in restored)),
    )


def _build_node(
    node: object,
    *,
    location: str,
    expected_rule: OperandRule,
    field_bindings: Mapping[str, str],
) -> tuple[ast.expr, int, set[str], set[str]]:
    if expected_rule == "window":
        expression, lookback, fields = _build_window(node, location)
        return expression, lookback, fields, set()
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
        return ast.Name(id=f"f{evaluation_name}", ctx=ast.Load()), 0, {evaluation_name}, {field_id}

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
        return ast.Constant(value=value), 0, set(), set()

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
    fields = set().union(*(item[2] for item in built))
    field_ids = set().union(*(item[3] for item in built))
    if operator.kind == "historical":
        effective_lookback = child_lookback + int(operands[1]["literal"])
    elif operator.kind == "rolling":
        effective_lookback = child_lookback + int(operands[1]["literal"]) - 1
    else:
        effective_lookback = child_lookback
    return (
        _operator_ast(operator_id, [item[0] for item in built]),
        effective_lookback,
        fields,
        field_ids,
    )


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
