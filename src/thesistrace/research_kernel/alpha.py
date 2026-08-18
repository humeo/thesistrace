import hashlib
import math
from collections import Counter
from collections.abc import Callable, Mapping

import numpy as np

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
    evaluate_columnar_execution_matrix,
    evaluate_series_execution_matrix,
    evaluate_series_execution_plan,
)
from thesistrace.research_series import AlignedResearchData, ColumnarResearchSeries


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
    return _compose_alpha_matrix(
        research_data,
        compiled_alpha=compiled_alpha,
        neutralization=neutralization,
        value_at=lambda instrument_id, session_index: evaluated[instrument_id][session_index],
        cancellation_check=None,
    )


def evaluate_columnar_alpha_matrix(
    research_data: ColumnarResearchSeries,
    *,
    compiled_alpha: CompiledAlphaLike,
    neutralization: str,
    cancellation_check: Callable[[], None],
) -> dict[str, object]:
    return _evaluate_columnar_alpha(
        research_data,
        compiled_alpha=compiled_alpha,
        neutralization=neutralization,
        cancellation_check=cancellation_check,
        include_checksum=True,
    )


def evaluate_columnar_alpha_sessions(
    research_data: ColumnarResearchSeries,
    *,
    compiled_alpha: CompiledAlphaLike,
    neutralization: str,
    cancellation_check: Callable[[], None],
) -> dict[str, object]:
    return _evaluate_columnar_alpha(
        research_data,
        compiled_alpha=compiled_alpha,
        neutralization=neutralization,
        cancellation_check=cancellation_check,
        include_checksum=False,
    )


def _evaluate_columnar_alpha(
    research_data: ColumnarResearchSeries,
    *,
    compiled_alpha: CompiledAlphaLike,
    neutralization: str,
    cancellation_check: Callable[[], None],
    include_checksum: bool,
) -> dict[str, object]:
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization must be none or industry")
    calendar = tuple(research_data.sessions)
    instruments = tuple(sorted(research_data.instruments))
    plan = build_series_execution_plan(compiled_alpha)
    evaluated = evaluate_columnar_execution_matrix(
        plan,
        instruments,
        calendar,
        research_data.numeric_field_matrices(plan.field_names, instruments),
        research_data.universe_members,
        cancellation_check=cancellation_check,
    )
    positions = {instrument_id: index for index, instrument_id in enumerate(instruments)}
    if neutralization == "none":
        return _compose_unneutralized_columnar_alpha_matrix(
            research_data,
            compiled_alpha=compiled_alpha,
            evaluated=evaluated,
            positions=positions,
            cancellation_check=cancellation_check,
            include_checksum=include_checksum,
        )
    return _compose_alpha_matrix(
        research_data,
        compiled_alpha=compiled_alpha,
        neutralization=neutralization,
        value_at=lambda instrument_id, session_index: evaluated[
            positions[instrument_id], session_index
        ],
        cancellation_check=cancellation_check,
        include_checksum=include_checksum,
    )


def _compose_unneutralized_columnar_alpha_matrix(
    research_data: ColumnarResearchSeries,
    *,
    compiled_alpha: CompiledAlphaLike,
    evaluated: np.ndarray,
    positions: Mapping[str, int],
    cancellation_check: Callable[[], None],
    include_checksum: bool,
) -> dict[str, object]:
    session_results: list[dict[str, object]] = []
    for session_index, session in enumerate(research_data.sessions):
        cancellation_check()
        instrument_ids = tuple(sorted(research_data.universe_members.get(session, ())))
        indices = np.fromiter(
            (positions[instrument_id] for instrument_id in instrument_ids),
            dtype=np.intp,
            count=len(instrument_ids),
        )
        values = evaluated[indices, session_index]
        finite = np.isfinite(values)
        rows = [
            {"instrument_id": instrument_id, "value": float(value)}
            for instrument_id, value in zip(
                np.asarray(instrument_ids, dtype=np.str_)[finite],
                values[finite],
                strict=True,
            )
        ]
        missing_count = int(len(values) - np.count_nonzero(finite))
        session_results.append(
            {
                "session": session,
                "values": rows,
                "coverage_loss": (
                    {"missing_expression": missing_count} if missing_count else {}
                ),
            }
        )
        cancellation_check()
    return {
        "expression": dict(compiled_alpha.expression),
        "effective_lookback": compiled_alpha.effective_lookback,
        "neutralization": "none",
        "sessions": session_results,
        "checksum": alpha_matrix_checksum(session_results) if include_checksum else None,
    }


def _compose_alpha_matrix(
    research_data: AlignedResearchData | ColumnarResearchSeries,
    *,
    compiled_alpha: CompiledAlphaLike,
    neutralization: str,
    value_at: Callable[[str, int], float | None],
    cancellation_check: Callable[[], None] | None,
    include_checksum: bool = True,
) -> dict[str, object]:
    calendar = list(research_data.sessions)
    session_results: list[dict[str, object]] = []
    for session_index, session in enumerate(calendar):
        if cancellation_check is not None:
            cancellation_check()
        coverage = Counter()
        raw_values: dict[str, float] = {}
        for instrument_id in research_data.universe_members.get(session, ()):
            value = value_at(instrument_id, session_index)
            if value is None or not math.isfinite(float(value)):
                coverage["missing_expression"] += 1
                continue
            raw_values[instrument_id] = float(value)
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
        if cancellation_check is not None:
            cancellation_check()
    return {
        "expression": dict(compiled_alpha.expression),
        "effective_lookback": compiled_alpha.effective_lookback,
        "neutralization": neutralization,
        "sessions": session_results,
        "checksum": alpha_matrix_checksum(session_results) if include_checksum else None,
    }


def alpha_matrix_checksum(sessions: list[dict[str, object]]) -> str:
    checksum: str | None = None
    for session in sessions:
        checksum = advance_alpha_checksum(checksum, session)
    return checksum or hashlib.sha256(b"thesistrace-alpha-checksum-v2\0").hexdigest()


def advance_alpha_checksum(
    prior: str | None,
    session: Mapping[str, object],
) -> str:
    checksum = hashlib.sha256(b"thesistrace-alpha-checksum-v2\0")
    if prior is not None:
        if len(prior) != 64:
            raise ValueError("Alpha checksum continuation is invalid")
        checksum.update(bytes.fromhex(prior))
    checksum.update(str(session["session"]).encode())
    checksum.update(b"\0")
    rows = session.get("values")
    if not isinstance(rows, list):
        raise ValueError("Alpha Matrix session values are invalid")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Alpha Matrix value is invalid")
    checksum.update(
        b"".join(
            str(row["instrument_id"]).encode()
            + b"\0"
            + canonical_binary64_bytes(float(row["value"]))
            for row in rows
        )
    )
    return checksum.hexdigest()


def finite_or_missing(value: float) -> float | None:
    return value if math.isfinite(value) else None


def issue(reason_code: str, column: int, message: str) -> AlphaValidationIssue:
    return AlphaValidationIssue(
        reason_code=reason_code,
        location=f"alpha.expression:{column}",
        message=message,
    )
