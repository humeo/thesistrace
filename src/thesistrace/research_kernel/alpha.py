import ast
import hashlib
import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

from thesistrace.research_kernel.alpha_expression import (
    SCALAR_OPERATOR_IDS,
    AlphaExpression,
    AlphaValidationIssue,
    ParsedAlpha,
    validate_normalized_alpha,
)
from thesistrace.research_kernel.numeric import canonical_binary64_bytes


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
    canonical: dict[str, object],
    *,
    expression: AlphaExpression,
    field_bindings: Mapping[str, str],
    universe_name: str,
    neutralization: str,
) -> dict[str, object]:
    parsed = validate_alpha(expression, field_bindings=field_bindings)
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization must be none or industry")
    calendar = [str(item) for item in canonical["research_calendar"]]
    instruments = sorted(str(item["instrument_id"]) for item in canonical["instruments"])
    prices_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row for row in canonical["prices"]
    }
    canonical_keys = {
        "open_adj": "open_adj",
        "high_adj": "high_adj",
        "low_adj": "low_adj",
        "close_adj": "close_adj",
        "volume_shares": "volume_shares",
        "turnover_amount_cny": "turnover_cny",
    }
    evaluated: dict[str, list[float | None]] = {}
    for instrument_id in instruments:
        inputs: dict[str, list[float | None]] = {}
        for field in parsed.field_names:
            key = canonical_keys[field]
            inputs[field] = [
                float(row[key])
                if (row := prices_by_position.get((session, instrument_id)))
                else None
                for session in calendar
            ]
        evaluated[instrument_id] = evaluate_parsed_series(
            parsed,
            inputs,
            length=len(calendar),
        )

    universes = canonical["liquidity_universes"]
    universe_snapshots = {
        str(item["session"]): [str(value) for value in item["instrument_ids"]]
        for item in universes[universe_name]
    }
    st_positions = {
        (str(item.get("trade_date") or item.get("session")), str(item["instrument_id"]))
        for item in canonical.get("st_designations", [])
    }
    industries = canonical["industry_membership"]
    session_results: list[dict[str, object]] = []
    for session_index, session in enumerate(calendar):
        coverage = Counter()
        raw_values: dict[str, float] = {}
        for instrument_id in universe_snapshots.get(session, []):
            if (session, instrument_id) in st_positions:
                coverage["st_excluded"] += 1
                continue
            value = evaluated[instrument_id][session_index]
            if value is None:
                coverage["missing_expression"] += 1
                continue
            raw_values[instrument_id] = value
        final_values = raw_values
        if neutralization == "industry":
            groups: dict[str, list[tuple[str, float]]] = {}
            for instrument_id, value in raw_values.items():
                industry = resolve_industry(industries, instrument_id, session)
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
        "expression": expression,
        "effective_lookback": parsed.effective_lookback,
        "neutralization": neutralization,
        "sessions": session_results,
        "checksum": alpha_matrix_checksum(session_results),
    }


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


def resolve_industry(
    memberships: Any,
    instrument_id: str,
    session: str,
) -> str | None:
    for item in memberships:
        if item["instrument_id"] != instrument_id:
            continue
        active_to = str(item.get("active_to", ""))
        if str(item["active_from"]) <= session and (not active_to or session < active_to):
            value = str(item.get("sw2021_l1", ""))
            return value or None
    return None


def finite_or_missing(value: float) -> float | None:
    return value if math.isfinite(value) else None


def issue(reason_code: str, column: int, message: str) -> AlphaValidationIssue:
    return AlphaValidationIssue(
        reason_code=reason_code,
        location=f"alpha.expression:{column}",
        message=message,
    )
