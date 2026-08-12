import ast
import hashlib
import math
from collections import Counter, deque
from collections.abc import Mapping
from fractions import Fraction

from thesistrace.research_kernel.alpha_expression import (
    OPERATOR_BY_ID,
    SCALAR_OPERATOR_IDS,
    AlphaExpression,
    AlphaValidationIssue,
    ParsedAlpha,
    restore_compiled_alpha,
    validate_normalized_alpha,
)
from thesistrace.research_kernel.numeric import canonical_binary64_bytes
from thesistrace.research_series import AlignedResearchData


def validate_alpha(
    expression: AlphaExpression,
    *,
    field_bindings: Mapping[str, str],
) -> ParsedAlpha:
    return validate_normalized_alpha(
        expression,
        field_bindings=field_bindings,
    )


def evaluate_series(
    expression: AlphaExpression,
    values_by_field: dict[str, list[float | None]],
    *,
    field_bindings: Mapping[str, str],
) -> list[float | None]:
    parsed = validate_alpha(expression, field_bindings=field_bindings)
    return evaluate_parsed_series(parsed, values_by_field)


def evaluate_parsed_series(
    parsed: ParsedAlpha,
    values_by_field: dict[str, list[float | None]],
    *,
    length: int | None = None,
) -> list[float | None]:
    lengths = {len(values_by_field[field]) for field in parsed.field_names}
    if len(lengths) > 1:
        raise ValueError("all Alpha input series must have the same length")
    inferred_length = lengths.pop() if lengths else None
    if length is not None and inferred_length is not None and length != inferred_length:
        raise ValueError("explicit Alpha series length does not match field inputs")
    result_length = (
        length if length is not None else (1 if inferred_length is None else inferred_length)
    )
    return [
        evaluate_node(parsed.tree.body, index, values_by_field) for index in range(result_length)
    ]


def evaluate_node(
    node: ast.AST,
    index: int,
    values_by_field: dict[str, list[float | None]],
) -> float | None:
    if isinstance(node, ast.Constant):
        return finite_or_missing(float(node.value))
    if isinstance(node, ast.Name):
        return values_by_field[node.id[1:]][index]
    if isinstance(node, ast.UnaryOp):
        operand = evaluate_node(node.operand, index, values_by_field)
        return None if operand is None else finite_or_missing(-operand)
    if isinstance(node, ast.BinOp):
        left = evaluate_node(node.left, index, values_by_field)
        right = evaluate_node(node.right, index, values_by_field)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return finite_or_missing(left + right)
        if isinstance(node.op, ast.Sub):
            return finite_or_missing(left - right)
        if isinstance(node.op, ast.Mult):
            return finite_or_missing(left * right)
        if isinstance(node.op, ast.Div):
            return None if right == 0.0 else finite_or_missing(left / right)
    if isinstance(node, ast.Call):
        function_name = node.func.id
        if function_name in SCALAR_OPERATOR_IDS:
            value = evaluate_node(node.args[0], index, values_by_field)
            if value is None:
                return None
            if function_name == "abs":
                return finite_or_missing(abs(value))
            if function_name == "log":
                return None if value <= 0.0 else finite_or_missing(math.log(value))
            return -1.0 if value < 0.0 else (1.0 if value > 0.0 else 0.0)
        window = int(node.args[1].value)
        if function_name == "lag":
            return (
                None
                if index - window < 0
                else evaluate_node(node.args[0], index - window, values_by_field)
            )
        if function_name in {"delta", "pct_change"}:
            current = evaluate_node(node.args[0], index, values_by_field)
            prior = (
                None
                if index - window < 0
                else evaluate_node(node.args[0], index - window, values_by_field)
            )
            if current is None or prior is None:
                return None
            if function_name == "delta":
                return finite_or_missing(current - prior)
            return None if prior == 0.0 else finite_or_missing(current / prior - 1.0)
        start = index - window + 1
        if start < 0:
            return None
        window_values = [
            evaluate_node(node.args[0], position, values_by_field)
            for position in range(start, index + 1)
        ]
        if any(value is None for value in window_values):
            return None
        complete = [float(value) for value in window_values if value is not None]
        if function_name == "ts_sum":
            return finite_or_missing(math.fsum(complete))
        if function_name == "ts_mean":
            return finite_or_missing(math.fsum(complete) / window)
        if function_name == "ts_min":
            return min(complete)
        if function_name == "ts_max":
            return max(complete)
        mean = math.fsum(complete) / window
        variance = math.fsum((value - mean) ** 2 for value in complete) / window
        return finite_or_missing(math.sqrt(variance))
    raise AssertionError(f"unsupported validated node: {type(node).__name__}")


def evaluate_alpha_matrix(
    research_data: AlignedResearchData,
    *,
    expression: AlphaExpression,
    field_bindings: Mapping[str, str],
    neutralization: str,
) -> dict[str, object]:
    parsed = validate_alpha(expression, field_bindings=field_bindings)
    return evaluate_parsed_alpha_matrix(
        research_data,
        parsed=parsed,
        field_bindings=field_bindings,
        neutralization=neutralization,
    )


def evaluate_compiled_alpha_matrix(
    research_data: AlignedResearchData,
    *,
    compiled_alpha: Mapping[str, object],
    field_bindings: Mapping[str, str],
    neutralization: str,
) -> dict[str, object]:
    parsed = restore_compiled_alpha(compiled_alpha)
    if not set(parsed.field_ids) <= set(field_bindings):
        raise ValueError("compiled Alpha Field References are invalid")
    return evaluate_parsed_alpha_matrix(
        research_data,
        parsed=parsed,
        field_bindings=field_bindings,
        neutralization=neutralization,
    )


def evaluate_parsed_alpha_matrix(
    research_data: AlignedResearchData,
    *,
    parsed: ParsedAlpha,
    field_bindings: Mapping[str, str],
    neutralization: str,
) -> dict[str, object]:
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization must be none or industry")
    calendar = list(research_data.sessions)
    instruments = sorted(research_data.instruments)
    field_ids_by_name = {
        evaluation_name: field_id for field_id, evaluation_name in field_bindings.items()
    }
    inputs = {
        evaluation_name: {
            instrument_id: [
                (
                    finite_or_missing(float(value))
                    if (value := research_data.fields[field_id].get((session, instrument_id)))
                    is not None
                    else None
                )
                for session in calendar
            ]
            for instrument_id in instruments
        }
        for evaluation_name, field_id in field_ids_by_name.items()
        if evaluation_name in parsed.field_names
    }
    evaluated = _evaluate_matrix_node(
        parsed.tree.body,
        inputs,
        instruments,
        calendar,
        research_data.universe_members,
    )

    session_results: list[dict[str, object]] = []
    for session_index, session in enumerate(calendar):
        coverage = Counter()
        raw_values: dict[str, float] = {}
        for instrument_id in research_data.universe_members.get(session, ()):
            value = evaluated[instrument_id][session_index]
            if value is None:
                coverage["missing_expression"] += 1
                continue
            raw_values[instrument_id] = value
        final_values = raw_values
        if neutralization == "industry":
            groups: dict[str, list[tuple[str, float]]] = {}
            for instrument_id, value in raw_values.items():
                industry = research_data.industries.get((session, instrument_id))
                if industry is None:
                    coverage["missing_industry"] += 1
                    continue
                groups.setdefault(industry, []).append((instrument_id, value))
            final_values = {}
            for rows in groups.values():
                if len(rows) < 2:
                    coverage["industry_group_too_small"] += len(rows)
                    continue
                mean = math.fsum(value for _, value in rows) / len(rows)
                for instrument_id, value in rows:
                    final_values[instrument_id] = finite_or_missing(value - mean) or 0.0
        rows = [
            {"instrument_id": instrument_id, "value": final_values[instrument_id]}
            for instrument_id in sorted(final_values)
        ]
        session_results.append(
            {"session": session, "values": rows, "coverage_loss": dict(sorted(coverage.items()))}
        )
    return {
        "expression": parsed.expression,
        "effective_lookback": parsed.effective_lookback,
        "neutralization": neutralization,
        "sessions": session_results,
        "checksum": alpha_matrix_checksum(session_results),
    }


def _evaluate_matrix_node(
    node: ast.AST,
    inputs: Mapping[str, dict[str, list[float | None]]],
    instruments: list[str],
    sessions: list[str],
    universe_members: Mapping[str, tuple[str, ...]],
) -> dict[str, list[float | None]]:
    if isinstance(node, ast.Name):
        return inputs[node.id[1:]]
    if isinstance(node, ast.Constant):
        value = finite_or_missing(float(node.value))
        return {instrument_id: [value] * len(sessions) for instrument_id in instruments}
    definition = OPERATOR_BY_ID.get(node.func.id) if isinstance(node, ast.Call) else None
    if definition is not None and definition.kind == "cross-sectional":
        child = _evaluate_matrix_node(node.args[0], inputs, instruments, sessions, universe_members)
        ranked = {instrument_id: [None] * len(sessions) for instrument_id in instruments}
        evaluator = definition.cross_section_evaluator
        assert evaluator is not None
        for session_index, session in enumerate(sessions):
            finite = [
                (instrument_id, value)
                for instrument_id in universe_members.get(session, ())
                if (value := child[instrument_id][session_index]) is not None
                and math.isfinite(value)
            ]
            for instrument_id, rank in evaluator(finite).items():
                ranked[instrument_id][session_index] = rank
        return ranked
    children = [
        _evaluate_matrix_node(child, inputs, instruments, sessions, universe_members)
        for child in _numeric_children(node)
    ]
    return {
        instrument_id: _evaluate_operator_series(
            node,
            [child[instrument_id] for child in children],
            len(sessions),
        )
        for instrument_id in instruments
    }


def _numeric_children(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.UnaryOp):
        return [node.operand]
    if isinstance(node, ast.BinOp):
        return [node.left, node.right]
    if isinstance(node, ast.Call):
        return [node.args[0]]
    raise AssertionError(f"unsupported validated matrix node: {type(node).__name__}")


def _evaluate_operator_series(
    node: ast.AST,
    children: list[list[float | None]],
    length: int,
) -> list[float | None]:
    if isinstance(node, ast.UnaryOp):
        return [None if value is None else finite_or_missing(-value) for value in children[0]]
    if isinstance(node, ast.BinOp):
        return [
            _binary_value(node.op, left, right)
            for left, right in zip(children[0], children[1], strict=True)
        ]
    if not isinstance(node, ast.Call):
        raise AssertionError("unsupported validated Series operator")
    operator_id = node.func.id
    values = children[0]
    if operator_id in SCALAR_OPERATOR_IDS:
        return [_scalar_value(operator_id, value) for value in values]
    window = int(node.args[1].value)
    if operator_id in {"lag", "delta", "pct_change"}:
        return _historical_series(operator_id, values, window)
    return _rolling_series(operator_id, values, window)


def _binary_value(
    operator: ast.operator,
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None or right is None:
        return None
    if isinstance(operator, ast.Add):
        return finite_or_missing(left + right)
    if isinstance(operator, ast.Sub):
        return finite_or_missing(left - right)
    if isinstance(operator, ast.Mult):
        return finite_or_missing(left * right)
    if isinstance(operator, ast.Div):
        return None if right == 0.0 else finite_or_missing(left / right)
    raise AssertionError("unsupported validated binary operator")


def _scalar_value(operator_id: str, value: float | None) -> float | None:
    if value is None:
        return None
    if operator_id == "abs":
        return finite_or_missing(abs(value))
    if operator_id == "log":
        return None if value <= 0 else finite_or_missing(math.log(value))
    return -1.0 if value < 0 else (1.0 if value > 0 else 0.0)


def _historical_series(
    operator_id: str,
    values: list[float | None],
    window: int,
) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    for index in range(window, len(values)):
        current = values[index]
        prior = values[index - window]
        if operator_id == "lag":
            output[index] = prior
        elif current is not None and prior is not None:
            output[index] = (
                finite_or_missing(current - prior)
                if operator_id == "delta"
                else (None if prior == 0 else finite_or_missing(current / prior - 1.0))
            )
    return output


def _rolling_series(
    operator_id: str,
    values: list[float | None],
    window: int,
) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    queue: deque[float | None] = deque()
    missing = 0
    total = 0
    squares = 0
    extrema: deque[tuple[int, float]] = deque()
    for index, value in enumerate(values):
        queue.append(value)
        if value is None:
            missing += 1
        else:
            exact = _scaled_binary64(value)
            total += exact
            squares += exact * exact
            if operator_id in {"ts_min", "ts_max"}:
                while extrema and (
                    extrema[-1][1] >= value
                    if operator_id == "ts_min"
                    else extrema[-1][1] <= value
                ):
                    extrema.pop()
                extrema.append((index, value))
        if len(queue) > window:
            expired = queue.popleft()
            if expired is None:
                missing -= 1
            else:
                exact = _scaled_binary64(expired)
                total -= exact
                squares -= exact * exact
            while extrema and extrema[0][0] <= index - window:
                extrema.popleft()
        if len(queue) != window or missing:
            continue
        if operator_id == "ts_sum":
            output[index] = _fraction_or_missing(Fraction(total, _BINARY64_SCALE))
        elif operator_id == "ts_mean":
            output[index] = _fraction_or_missing(
                Fraction(total, _BINARY64_SCALE * window)
            )
        elif operator_id in {"ts_min", "ts_max"}:
            output[index] = extrema[0][1]
        else:
            variance = Fraction(
                squares * window - total * total,
                _BINARY64_SCALE * _BINARY64_SCALE * window * window,
            )
            finite_variance = _fraction_or_missing(variance)
            output[index] = (
                None if finite_variance is None else math.sqrt(finite_variance)
            )
    return output


_BINARY64_SCALE = 1 << 1074


def _scaled_binary64(value: float) -> int:
    numerator, denominator = value.as_integer_ratio()
    return numerator * (_BINARY64_SCALE // denominator)


def _fraction_or_missing(value: Fraction) -> float | None:
    try:
        return finite_or_missing(float(value))
    except OverflowError:
        return None


def alpha_matrix_checksum(sessions: list[dict[str, object]]) -> str:
    checksum = hashlib.sha256()
    for session in sessions:
        checksum.update(str(session["session"]).encode())
        checksum.update(b"\0")
        rows = session.get("values")
        if not isinstance(rows, list):
            raise ValueError("Alpha Matrix session values are invalid")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("Alpha Matrix value is invalid")
            checksum.update(str(row["instrument_id"]).encode())
            checksum.update(b"\0")
            checksum.update(canonical_binary64_bytes(float(row["value"])))
    return checksum.hexdigest()


def finite_or_missing(value: float) -> float | None:
    return value if math.isfinite(value) else None


def issue(reason_code: str, column: int, message: str) -> AlphaValidationIssue:
    return AlphaValidationIssue(
        reason_code=reason_code,
        location=f"alpha.expression:{column}",
        message=message,
    )
