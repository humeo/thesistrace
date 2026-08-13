import hashlib
import math
from collections import Counter
from collections.abc import Mapping

from thesistrace.research_kernel.alpha_expression import (
    AlphaExpression,
    AlphaValidationIssue,
    ParsedAlpha,
    validate_normalized_alpha,
)
from thesistrace.research_kernel.numeric import canonical_binary64_bytes
from thesistrace.research_kernel.series_plan import (
    CompiledAlphaLike,
    build_series_execution_plan,
    evaluate_series_execution_matrix,
    evaluate_series_execution_plan,
)
from thesistrace.research_series import AlignedResearchData


def validate_alpha(
    expression: AlphaExpression,
    *,
    field_bindings: Mapping[str, str],
) -> ParsedAlpha:
    return validate_normalized_alpha(expression, field_bindings=field_bindings)


def evaluate_series(
    expression: AlphaExpression,
    values_by_field: dict[str, list[float | None]],
    *,
    field_bindings: Mapping[str, str],
) -> list[float | None]:
    return evaluate_parsed_series(
        validate_alpha(expression, field_bindings=field_bindings),
        values_by_field,
    )


def evaluate_parsed_series(
    parsed: ParsedAlpha,
    values_by_field: dict[str, list[float | None]],
    *,
    length: int | None = None,
) -> list[float | None]:
    return evaluate_series_execution_plan(
        build_series_execution_plan(parsed),
        {
            parsed.field_ids_by_identifier[identifier]: values
            for identifier, values in values_by_field.items()
        },
        length=length,
    )


def evaluate_alpha_matrix(
    research_data: AlignedResearchData,
    *,
    compiled_alpha: CompiledAlphaLike,
    neutralization: str,
) -> dict[str, object]:
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization must be none or industry")
    calendar = list(research_data.sessions)
    instruments = sorted(research_data.instruments)
    plan = build_series_execution_plan(compiled_alpha)
    evaluated = evaluate_series_execution_matrix(
        plan,
        instruments,
        lambda instrument_id: {
            field_id: [
                (
                    finite_or_missing(float(value))
                    if (value := research_data.fields[field_id].get((session, instrument_id)))
                    is not None
                    else None
                )
                for session in calendar
            ]
            for field_id in plan.field_names
        },
        length=len(calendar),
        universe_members=research_data.universe_members,
        sessions=tuple(calendar),
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
        "expression": dict(compiled_alpha.expression),
        "effective_lookback": compiled_alpha.effective_lookback,
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


def finite_or_missing(value: float) -> float | None:
    return value if math.isfinite(value) else None


def issue(reason_code: str, column: int, message: str) -> AlphaValidationIssue:
    return AlphaValidationIssue(
        reason_code=reason_code,
        location=f"alpha.expression:{column}",
        message=message,
    )
