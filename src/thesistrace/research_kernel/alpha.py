import hashlib
import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

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

type FieldSeriesReader = Callable[
    [str, Sequence[Mapping[str, object] | None]],
    Sequence[float | None],
]


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
    return evaluate_series_execution_plan(
        build_series_execution_plan(parsed),
        {
            parsed.field_ids_by_identifier[identifier]: values
            for identifier, values in values_by_field.items()
        },
        length=length,
    )


def evaluate_alpha_matrix(
    canonical: dict[str, object],
    *,
    compiled_alpha: CompiledAlphaLike,
    universe_name: str,
    neutralization: str,
    read_field_series: FieldSeriesReader,
) -> dict[str, object]:
    if neutralization not in {"none", "industry"}:
        raise ValueError("neutralization must be none or industry")
    calendar = [str(item) for item in canonical["research_calendar"]]
    universes = canonical["liquidity_universes"]
    universe_snapshots = {
        str(item["session"]): [str(value) for value in item["instrument_ids"]]
        for item in universes[universe_name]
    }
    instruments = sorted(set().union(*(set(values) for values in universe_snapshots.values())))
    prices_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row for row in canonical["prices"]
    }
    plan = build_series_execution_plan(compiled_alpha)

    def inputs_for_instrument(instrument_id: str) -> dict[str, list[float | None]]:
        inputs: dict[str, list[float | None]] = {}
        for field_id in plan.field_names:
            inputs[field_id] = list(
                read_field_series(
                    field_id,
                    [prices_by_position.get((session, instrument_id)) for session in calendar],
                )
            )
        return inputs

    evaluated = evaluate_series_execution_matrix(
        plan,
        instruments,
        inputs_for_instrument,
        length=len(calendar),
    )

    industries = canonical["industry_membership"]
    session_results: list[dict[str, object]] = []
    for session_index, session in enumerate(calendar):
        coverage = Counter()
        raw_values: dict[str, float] = {}
        for instrument_id in universe_snapshots.get(session, []):
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
