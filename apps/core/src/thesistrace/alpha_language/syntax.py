"""Operator spellings shared by the compiler and the public authoring reference."""

import ast

ARITHMETIC_OPERATORS = {
    ast.Add: ("+", "add"), ast.Sub: ("-", "subtract"),
    ast.Mult: ("*", "multiply"), ast.Div: ("/", "divide"),
}
COMPARISON_OPERATORS = {
    ast.Gt: (">", "gt"), ast.GtE: (">=", "ge"), ast.Lt: ("<", "lt"),
    ast.LtE: ("<=", "le"), ast.Eq: ("==", "eq"), ast.NotEq: ("!=", "ne"),
}
UNARY_OPERATORS = {ast.USub: ("-", "negate"), ast.Not: ("not", "not")}
BOOLEAN_OPERATORS = {ast.And: ("and", "and"), ast.Or: ("or", "or")}
