from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

from thesistrace.alpha_language.models import (
    AlphaAuthoringCatalog,
    AlphaBuiltinCatalogEntry,
    AlphaFieldCatalogEntry,
    BuiltinParameter,
    BuiltinWorkEstimate,
    CompiledAlpha,
    DiagnosticDetails,
    FormulaDiagnostic,
    FormulaDiagnostics,
    SourcePosition,
    SourceRange,
    ValueType,
)
from thesistrace.data.fields import FieldDefinition
from thesistrace.research_kernel.alpha_builtins import (
    BUILTIN_DEFINITIONS,
    BuiltinDefinition,
)

MAX_FORMULA_LENGTH = 4096
MAX_EXPRESSION_NODES = 256
MAX_EXPRESSION_DEPTH = 32
MAX_EFFECTIVE_LOOKBACK = 252
MAX_ESTIMATED_WORK = 4096
ALPHA_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class AlphaLanguageCatalogError(RuntimeError):
    pass


class FormulaCompilationError(ValueError):
    def __init__(self, diagnostics: list[FormulaDiagnostic]) -> None:
        super().__init__("Alpha Formula is invalid")
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class _BuiltExpression:
    expression: dict[str, object]
    value_type: ValueType
    field_ids_by_identifier: dict[str, str]
    effective_lookback: int
    node_count: int
    depth: int
    estimated_work: int


class AlphaLanguage:
    def __init__(
        self,
        *,
        fields: tuple[FieldDefinition, ...],
        builtins: tuple[BuiltinDefinition, ...] = BUILTIN_DEFINITIONS,
    ) -> None:
        field_by_identifier: dict[str, FieldDefinition] = {}
        for field in fields:
            if field.alpha is None:
                continue
            identifier = field.alpha.identifier
            _validate_identifier(identifier)
            if field.alpha_series_reader is None:
                raise AlphaLanguageCatalogError(
                    f"Alpha field has no Data Series reader: {identifier}"
                )
            if identifier in field_by_identifier:
                raise AlphaLanguageCatalogError(f"duplicate Alpha identifier: {identifier}")
            field_by_identifier[identifier] = field

        builtin_by_identifier: dict[str, BuiltinDefinition] = {}
        for builtin in builtins:
            _validate_identifier(builtin.identifier)
            if (
                builtin.identifier in builtin_by_identifier
                or builtin.identifier in field_by_identifier
            ):
                raise AlphaLanguageCatalogError(f"duplicate Alpha identifier: {builtin.identifier}")
            builtin_by_identifier[builtin.identifier] = builtin

        self._field_by_identifier = field_by_identifier
        self._builtin_by_identifier = builtin_by_identifier
        self._catalog = AlphaAuthoringCatalog(
            fields=[
                AlphaFieldCatalogEntry(
                    identifier=identifier,
                    field_id=field.field_id,
                    description=field.description,
                    unit=field.unit,
                )
                for identifier, field in field_by_identifier.items()
            ],
            builtins=[_public_builtin(builtin) for builtin in builtins],
        )

    def catalog(self) -> AlphaAuthoringCatalog:
        return self._catalog

    def diagnose(self, source: str) -> FormulaDiagnostics:
        try:
            self.compile(source)
        except FormulaCompilationError as error:
            return FormulaDiagnostics(valid=False, diagnostics=error.diagnostics)
        return FormulaDiagnostics(valid=True, diagnostics=[])

    def compile(self, source: str) -> CompiledAlpha:
        if len(source) > MAX_FORMULA_LENGTH:
            self._raise(
                source,
                "FORMULA_TOO_LONG",
                f"Formula exceeds {MAX_FORMULA_LENGTH} characters",
                details=DiagnosticDetails(
                    kind="resource_limit",
                    expected=MAX_FORMULA_LENGTH,
                    actual=len(source),
                ),
            )
        try:
            parsed = ast.parse(source, mode="eval")
        except (SyntaxError, ValueError, OverflowError) as error:
            raise FormulaCompilationError([_syntax_diagnostic(source, error)]) from None

        built = self._build(source, parsed.body, depth=1)
        if built.value_type is not ValueType.NUMERIC_SERIES:
            self._raise(
                source,
                "ROOT_MUST_BE_SERIES",
                "Alpha Formula must produce a Numeric Series",
                parsed.body,
                details=DiagnosticDetails(
                    kind="value_type",
                    expected=ValueType.NUMERIC_SERIES.value,
                    actual=built.value_type.value,
                ),
            )
        if built.node_count > MAX_EXPRESSION_NODES:
            self._raise(
                source,
                "TOO_MANY_EXPRESSION_NODES",
                f"Formula exceeds {MAX_EXPRESSION_NODES} expression nodes",
                parsed.body,
                details=DiagnosticDetails(
                    kind="resource_limit",
                    expected=MAX_EXPRESSION_NODES,
                    actual=built.node_count,
                ),
            )
        if built.effective_lookback > MAX_EFFECTIVE_LOOKBACK:
            self._raise(
                source,
                "LOOKBACK_EXCEEDS_LIMIT",
                f"Effective lookback exceeds {MAX_EFFECTIVE_LOOKBACK} Research Sessions",
                parsed.body,
                details=DiagnosticDetails(
                    kind="resource_limit",
                    expected=MAX_EFFECTIVE_LOOKBACK,
                    actual=built.effective_lookback,
                ),
            )
        if built.estimated_work > MAX_ESTIMATED_WORK:
            self._raise(
                source,
                "WORK_EXCEEDS_LIMIT",
                f"Estimated work exceeds {MAX_ESTIMATED_WORK}",
                parsed.body,
                details=DiagnosticDetails(
                    kind="resource_limit",
                    expected=MAX_ESTIMATED_WORK,
                    actual=built.estimated_work,
                ),
            )
        return CompiledAlpha(
            source=source,
            expression=built.expression,
            field_ids_by_identifier=built.field_ids_by_identifier,
            result_type=built.value_type,
            effective_lookback=built.effective_lookback,
            node_count=built.node_count,
            depth=built.depth,
            estimated_work=built.estimated_work,
        )

    def _build(self, source: str, node: ast.expr, *, depth: int) -> _BuiltExpression:
        if depth > MAX_EXPRESSION_DEPTH:
            self._raise(
                source,
                "EXPRESSION_TOO_DEEP",
                f"Formula exceeds expression depth {MAX_EXPRESSION_DEPTH}",
                node,
                details=DiagnosticDetails(
                    kind="resource_limit",
                    expected=MAX_EXPRESSION_DEPTH,
                    actual=depth,
                ),
            )
        if isinstance(node, ast.Name):
            field = self._field_by_identifier.get(node.id)
            if field is not None and field.alpha is not None:
                return _BuiltExpression(
                    expression={"kind": "field", "field_id": field.field_id},
                    value_type=ValueType.NUMERIC_SERIES,
                    field_ids_by_identifier={node.id: field.field_id},
                    effective_lookback=0,
                    node_count=1,
                    depth=depth,
                    estimated_work=1,
                )
            if node.id in self._builtin_by_identifier:
                self._raise(
                    source,
                    "EXPECTED_FIELD",
                    f"Builtin {node.id} must be called",
                    node,
                    details=DiagnosticDetails(
                        kind="callability",
                        expected="builtin_call",
                        actual="bare_builtin_identifier",
                    ),
                )
            self._raise(
                source,
                "UNKNOWN_IDENTIFIER",
                f"Unknown Alpha identifier: {node.id}",
                node,
                details=DiagnosticDetails(
                    kind="identifier",
                    expected=sorted((*self._field_by_identifier, *self._builtin_by_identifier)),
                    actual=node.id,
                ),
            )
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                self._raise(
                    source,
                    "BOOLEAN_NOT_ALLOWED",
                    "Boolean literals are not part of the Alpha Language",
                    node,
                    details=DiagnosticDetails(
                        kind="literal",
                        expected="finite_number",
                        actual="boolean",
                    ),
                )
            if not isinstance(node.value, (int, float)):
                self._raise(
                    source,
                    "UNSUPPORTED_LITERAL",
                    "Only numeric literals are allowed",
                    node,
                    details=DiagnosticDetails(
                        kind="literal",
                        expected="finite_number",
                        actual=type(node.value).__name__,
                    ),
                )
            try:
                finite = math.isfinite(float(node.value))
            except OverflowError:
                finite = False
            if not finite:
                self._raise(
                    source,
                    "NON_FINITE_LITERAL",
                    "Numeric literal must be finite",
                    node,
                    details=DiagnosticDetails(
                        kind="literal",
                        expected="finite_number",
                        actual="non_finite_number",
                    ),
                )
            return _BuiltExpression(
                expression={"kind": "number", "value": node.value},
                value_type=ValueType.NUMBER,
                field_ids_by_identifier={},
                effective_lookback=0,
                node_count=1,
                depth=depth,
                estimated_work=1,
            )
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, ast.USub):
                self._raise(
                    source,
                    "UNSUPPORTED_OPERATOR",
                    "Only unary minus is supported",
                    node,
                )
            operand = self._build(source, node.operand, depth=depth + 1)
            return _BuiltExpression(
                expression={
                    "kind": "unary",
                    "operator": "negate",
                    "operand": operand.expression,
                },
                value_type=operand.value_type,
                field_ids_by_identifier=operand.field_ids_by_identifier,
                effective_lookback=operand.effective_lookback,
                node_count=operand.node_count + 1,
                depth=max(depth, operand.depth),
                estimated_work=operand.estimated_work + 1,
            )
        if isinstance(node, ast.BinOp):
            operator = {
                ast.Add: "add",
                ast.Sub: "subtract",
                ast.Mult: "multiply",
                ast.Div: "divide",
            }.get(type(node.op))
            if operator is None:
                self._raise(
                    source,
                    "UNSUPPORTED_OPERATOR",
                    "Unsupported Alpha arithmetic operator",
                    node,
                )
            left = self._build(source, node.left, depth=depth + 1)
            right = self._build(source, node.right, depth=depth + 1)
            result_type = (
                ValueType.NUMERIC_SERIES
                if ValueType.NUMERIC_SERIES in {left.value_type, right.value_type}
                else ValueType.NUMBER
            )
            return _BuiltExpression(
                expression={
                    "kind": "binary",
                    "operator": operator,
                    "left": left.expression,
                    "right": right.expression,
                },
                value_type=result_type,
                field_ids_by_identifier={
                    **left.field_ids_by_identifier,
                    **right.field_ids_by_identifier,
                },
                effective_lookback=max(left.effective_lookback, right.effective_lookback),
                node_count=left.node_count + right.node_count + 1,
                depth=max(depth, left.depth, right.depth),
                estimated_work=left.estimated_work + right.estimated_work + 1,
            )
        if isinstance(node, ast.Call):
            return self._build_call(source, node, depth=depth)
        self._raise(
            source,
            "UNSUPPORTED_SYNTAX",
            f"Unsupported Alpha syntax: {type(node).__name__}",
            node,
        )

    def _build_call(self, source: str, node: ast.Call, *, depth: int) -> _BuiltExpression:
        if not isinstance(node.func, ast.Name):
            self._raise(
                source,
                "UNSUPPORTED_SYNTAX",
                "Only direct builtin calls are allowed",
                node.func,
                details=DiagnosticDetails(
                    kind="callability",
                    expected="builtin_identifier",
                    actual=type(node.func).__name__,
                ),
            )
        identifier = node.func.id
        if identifier in self._field_by_identifier:
            self._raise(
                source,
                "NOT_CALLABLE",
                f"Alpha field {identifier} is not callable",
                node.func,
                details=DiagnosticDetails(
                    kind="callability",
                    expected="builtin_identifier",
                    actual="field_identifier",
                ),
            )
        builtin = self._builtin_by_identifier.get(identifier)
        if builtin is None:
            self._raise(
                source,
                "UNKNOWN_IDENTIFIER",
                f"Unknown Alpha identifier: {identifier}",
                node.func,
                details=DiagnosticDetails(
                    kind="identifier",
                    expected=sorted(self._builtin_by_identifier),
                    actual=identifier,
                ),
            )
        if node.keywords:
            keyword = node.keywords[0]
            if keyword.arg is None:
                self._raise(
                    source,
                    "STARRED_ARGUMENT_NOT_ALLOWED",
                    "Starred arguments are not allowed",
                    keyword.value,
                )
            self._raise(
                source,
                "KEYWORD_ARGUMENT_NOT_ALLOWED",
                "Keyword arguments are not allowed",
                keyword.value,
            )
        if any(isinstance(argument, ast.Starred) for argument in node.args):
            starred = next(argument for argument in node.args if isinstance(argument, ast.Starred))
            self._raise(
                source,
                "STARRED_ARGUMENT_NOT_ALLOWED",
                "Starred arguments are not allowed",
                starred,
            )
        if len(node.args) != len(builtin.parameters):
            self._raise(
                source,
                "INVALID_ARITY",
                f"{identifier} expects {len(builtin.parameters)} arguments",
                node,
                details=DiagnosticDetails(
                    kind="arity",
                    expected=len(builtin.parameters),
                    actual=len(node.args),
                ),
            )

        arguments: list[_BuiltExpression] = []
        window: int | None = None
        for argument_node, parameter in zip(node.args, builtin.parameters, strict=True):
            rule = parameter.rule
            if rule == "window":
                window = self._window(source, argument_node)
                arguments.append(
                    _BuiltExpression(
                        expression={"kind": "number", "value": window},
                        value_type=ValueType.WINDOW,
                        field_ids_by_identifier={},
                        effective_lookback=0,
                        node_count=1,
                        depth=depth + 1,
                        estimated_work=1,
                    )
                )
                continue
            argument = self._build(source, argument_node, depth=depth + 1)
            if rule == "numeric_series" and argument.value_type is not ValueType.NUMERIC_SERIES:
                self._raise(
                    source,
                    "TYPE_MISMATCH",
                    f"{identifier} requires a Numeric Series",
                    argument_node,
                    details=DiagnosticDetails(
                        kind="value_type",
                        expected=ValueType.NUMERIC_SERIES.value,
                        actual=argument.value_type.value,
                    ),
                )
            arguments.append(argument)

        first = arguments[0]
        child_lookback = max(argument.effective_lookback for argument in arguments)
        return _BuiltExpression(
            expression={
                "kind": "call",
                "identifier": identifier,
                "arguments": [argument.expression for argument in arguments],
            },
            value_type=(
                ValueType.NUMERIC_SERIES
                if builtin.result_rule == "numeric_series"
                else first.value_type
            ),
            field_ids_by_identifier={
                key: value
                for argument in arguments
                for key, value in argument.field_ids_by_identifier.items()
            },
            effective_lookback=builtin.effective_lookback(child_lookback, window),
            node_count=1 + sum(argument.node_count for argument in arguments),
            depth=max(depth, *(argument.depth for argument in arguments)),
            estimated_work=builtin.estimated_work(
                sum(argument.estimated_work for argument in arguments),
                window,
            ),
        )

    def _window(self, source: str, node: ast.expr) -> int:
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
            self._raise(
                source,
                "WINDOW_MUST_BE_INTEGER",
                "Window must be an integer literal",
                node,
                details=DiagnosticDetails(
                    kind="window",
                    expected="integer_literal_1_to_252",
                    actual=type(node).__name__,
                ),
            )
        if not isinstance(node.value, int):
            self._raise(
                source,
                "WINDOW_MUST_BE_INTEGER",
                "Window must be an integer literal",
                node,
                details=DiagnosticDetails(
                    kind="window",
                    expected="integer_literal_1_to_252",
                    actual=type(node.value).__name__,
                ),
            )
        if node.value < 1 or node.value > 252:
            self._raise(
                source,
                "WINDOW_OUT_OF_RANGE",
                "Window must be between 1 and 252",
                node,
                details=DiagnosticDetails(
                    kind="window",
                    expected="integer_literal_1_to_252",
                    actual=node.value,
                ),
            )
        return node.value

    @staticmethod
    def _raise(
        source: str,
        code: str,
        message: str,
        node: ast.AST | None = None,
        *,
        details: DiagnosticDetails | None = None,
    ) -> None:
        raise FormulaCompilationError(
            [
                FormulaDiagnostic(
                    code=code,
                    message=message,
                    range=_source_range(source, node),
                    details=details,
                )
            ]
        )


def _validate_identifier(identifier: str) -> None:
    if not ALPHA_IDENTIFIER.fullmatch(identifier):
        raise AlphaLanguageCatalogError(f"invalid Alpha identifier: {identifier}")


def _public_builtin(builtin: BuiltinDefinition) -> AlphaBuiltinCatalogEntry:
    return AlphaBuiltinCatalogEntry(
        identifier=builtin.identifier,
        parameters=[
            BuiltinParameter(
                name=parameter.name,
                value_type=parameter.rule,
                minimum=1 if parameter.rule == "window" else None,
                maximum=252 if parameter.rule == "window" else None,
            )
            for parameter in builtin.parameters
        ],
        result_type=builtin.result_rule,
        description=builtin.description,
        examples=list(builtin.examples),
        missing_value_behavior=builtin.missing_value_behavior,
        numeric_behavior=builtin.numeric_behavior,
        work_estimate=BuiltinWorkEstimate(
            base_operations=builtin.work.base_operations,
            per_window_operations=builtin.work.per_window_operations,
        ),
    )


def _source_range(source: str, node: ast.AST | None) -> SourceRange:
    if node is None or not hasattr(node, "lineno"):
        return _range_from_offsets(source, 0, len(source))
    start = _line_column_to_offset(source, node.lineno, node.col_offset)
    end_line = getattr(node, "end_lineno", node.lineno)
    end_column = getattr(node, "end_col_offset", node.col_offset)
    end = _line_column_to_offset(source, end_line, end_column)
    return _range_from_offsets(source, start, end)


def _syntax_diagnostic(
    source: str,
    error: SyntaxError | ValueError | OverflowError,
) -> FormulaDiagnostic:
    if isinstance(error, SyntaxError):
        if not error.offset:
            start = len(source)
            end = start
            return FormulaDiagnostic(
                code="SYNTAX_ERROR",
                message="Formula is not one complete Alpha expression",
                range=_range_from_offsets(source, start, end),
                details=DiagnosticDetails(
                    kind="syntax",
                    expected="one_complete_expression",
                    actual="incomplete_expression",
                ),
            )
        line = error.lineno or 1
        start_column = max(error.offset - 1, 0)
        end_column = max((error.end_offset or error.offset) - 1, start_column + 1)
        start = _character_line_column_to_offset(source, line, start_column)
        end = _character_line_column_to_offset(source, error.end_lineno or line, end_column)
    else:
        start, end = 0, len(source)
    return FormulaDiagnostic(
        code="SYNTAX_ERROR",
        message="Formula is not one complete Alpha expression",
        range=_range_from_offsets(source, start, end),
        details=DiagnosticDetails(
            kind="syntax",
            expected="one_complete_expression",
            actual="invalid_syntax",
        ),
    )


def _line_column_to_offset(source: str, line: int, byte_column: int) -> int:
    lines = source.splitlines(keepends=True)
    prefix = sum(len(item) for item in lines[: line - 1])
    selected = lines[line - 1] if line <= len(lines) else ""
    encoded = selected.encode("utf-8")[:byte_column]
    return prefix + len(encoded.decode("utf-8", errors="ignore"))


def _character_line_column_to_offset(source: str, line: int, column: int) -> int:
    lines = source.splitlines(keepends=True)
    return sum(len(item) for item in lines[: line - 1]) + column


def _range_from_offsets(source: str, start: int, end: int) -> SourceRange:
    return SourceRange(
        start=_position(source, start),
        end=_position(source, end),
    )


def _position(source: str, offset: int) -> SourcePosition:
    bounded = max(0, min(offset, len(source)))
    before = source[:bounded]
    return SourcePosition(
        offset=bounded,
        line=before.count("\n") + 1,
        column=bounded - before.rfind("\n"),
    )
