from __future__ import annotations

from enum import StrEnum


class ValueType(StrEnum):
    NUMERIC_SERIES = "numeric_series"
    NUMBER = "number"
    BOOLEAN_SERIES = "boolean_series"
    BOOLEAN = "boolean"
    COMMON_NUMERIC_SERIES = "common_numeric_series"
    COMMON_BOOLEAN_SERIES = "common_boolean_series"
    WINDOW = "window"


NUMERIC_TYPES = frozenset(
    {ValueType.NUMBER, ValueType.NUMERIC_SERIES, ValueType.COMMON_NUMERIC_SERIES}
)
BOOLEAN_TYPES = frozenset(
    {ValueType.BOOLEAN, ValueType.BOOLEAN_SERIES, ValueType.COMMON_BOOLEAN_SERIES}
)
SERIES_TYPES = frozenset(
    {
        ValueType.NUMERIC_SERIES,
        ValueType.BOOLEAN_SERIES,
        ValueType.COMMON_NUMERIC_SERIES,
        ValueType.COMMON_BOOLEAN_SERIES,
    }
)
COMPARISON_OPERATORS = frozenset({"gt", "ge", "lt", "le", "eq", "ne"})
ARITHMETIC_OPERATORS = frozenset({"add", "subtract", "multiply", "divide"})
BOOLEAN_OPERATORS = frozenset({"and", "or"})


def unary_result_type(operator: str, operand: ValueType) -> ValueType:
    allowed = BOOLEAN_TYPES if operator == "not" else NUMERIC_TYPES
    if operator not in {"not", "negate"} or operand not in allowed:
        raise ValueError(f"{operator} does not accept {operand.value}")
    return operand


def binary_result_type(operator: str, left: ValueType, right: ValueType) -> ValueType:
    if operator in BOOLEAN_OPERATORS:
        allowed = BOOLEAN_TYPES
    elif operator in ARITHMETIC_OPERATORS | COMPARISON_OPERATORS:
        allowed = NUMERIC_TYPES
    else:
        raise ValueError(f"Unknown binary operator: {operator}")
    if left not in allowed or right not in allowed:
        raise ValueError(f"{operator} cannot combine {left.value} and {right.value}")
    return _result_scope(
        (left, right), boolean=operator in BOOLEAN_OPERATORS | COMPARISON_OPERATORS
    )


def _result_scope(types: tuple[ValueType, ...], *, boolean: bool) -> ValueType:
    if any(value in {ValueType.NUMERIC_SERIES, ValueType.BOOLEAN_SERIES} for value in types):
        return ValueType.BOOLEAN_SERIES if boolean else ValueType.NUMERIC_SERIES
    if any(value in SERIES_TYPES for value in types):
        return ValueType.COMMON_BOOLEAN_SERIES if boolean else ValueType.COMMON_NUMERIC_SERIES
    return ValueType.BOOLEAN if boolean else ValueType.NUMBER


def conditional_result_type(
    condition: ValueType,
    when_true: ValueType,
    when_false: ValueType,
) -> ValueType:
    if condition not in BOOLEAN_TYPES:
        raise ValueError("if_else condition must be Boolean")
    if when_true in NUMERIC_TYPES and when_false in NUMERIC_TYPES:
        boolean = False
    elif when_true in BOOLEAN_TYPES and when_false in BOOLEAN_TYPES:
        boolean = True
    else:
        raise ValueError("if_else branches must have the same value type")
    return _result_scope((condition, when_true, when_false), boolean=boolean)
