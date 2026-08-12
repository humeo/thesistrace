from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.research_series import Coordinate, NumericValue


class FinancialSeriesError(ValueError):
    pass


class FinancialSeriesReader(Protocol):
    def read_financial_rows(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
    ) -> tuple[dict[str, object], ...]: ...


@dataclass(frozen=True)
class _FieldProjection:
    field_id: str
    endpoint: str
    source_column: str
    period_selection: str


_PROJECTIONS = (
    _FieldProjection("total_revenue_latest_fy", "income", "total_revenue", "annual"),
    _FieldProjection("net_profit_parent_latest_fy", "income", "n_income_attr_p", "annual"),
    _FieldProjection(
        "operating_cash_flow_latest_fy",
        "cashflow",
        "n_cashflow_act",
        "annual",
    ),
    _FieldProjection(
        "total_assets_latest_reported",
        "balancesheet",
        "total_assets",
        "latest_reported",
    ),
    _FieldProjection(
        "total_liabilities_latest_reported",
        "balancesheet",
        "total_liab",
        "latest_reported",
    ),
    _FieldProjection(
        "equity_parent_latest_reported",
        "balancesheet",
        "total_hldr_eqy_exc_min_int",
        "latest_reported",
    ),
)
_PROJECTION_BY_ID = {projection.field_id: projection for projection in _PROJECTIONS}
_ENDPOINTS = ("income", "balancesheet", "cashflow")
_METADATA_COLUMNS = (
    "instrument_id",
    "source_report_period",
    "source_report_type",
    "source_company_type",
    "effective_available_session",
    "availability_status",
    "first_observed_at",
    "source_published_date",
    "source_row_sha256",
    "update_flag",
)
_COMPANY_TYPES = frozenset({"1", "2", "3", "4"})


class FinancialSeriesResolver:
    """Resolve sparse PIT facts into requested storage-independent Numeric Series."""

    def __init__(self, reader: FinancialSeriesReader) -> None:
        self._reader = reader

    def resolve(
        self,
        *,
        manifest_sha256: str,
        field_ids: Sequence[str],
        sessions: Sequence[str],
        instrument_ids: Sequence[str],
    ) -> dict[str, dict[Coordinate, NumericValue]]:
        fields = tuple(str(value) for value in field_ids)
        requested_sessions = tuple(str(value) for value in sessions)
        requested_instruments = tuple(str(value) for value in instrument_ids)
        _validate_request(
            manifest_sha256,
            fields,
            requested_sessions,
            requested_instruments,
        )
        unknown = set(fields) - set(_PROJECTION_BY_ID)
        if unknown:
            raise FinancialSeriesError("FINANCIAL_FIELD_UNSUPPORTED")
        projections = tuple(_PROJECTION_BY_ID[field_id] for field_id in fields)
        instrument_set = frozenset(requested_instruments)
        resolved: dict[str, dict[Coordinate, NumericValue]] = {field_id: {} for field_id in fields}
        for endpoint in _ENDPOINTS:
            endpoint_projections = tuple(
                projection for projection in projections if projection.endpoint == endpoint
            )
            if not endpoint_projections:
                continue
            source_columns = tuple(
                dict.fromkeys(
                    (
                        *_METADATA_COLUMNS,
                        *(projection.source_column for projection in endpoint_projections),
                    )
                )
            )
            rows = self._reader.read_financial_rows(
                manifest_sha256,
                endpoint,
                source_columns,
                requested_sessions,
                instrument_set,
            )
            for selection in {item.period_selection for item in endpoint_projections}:
                selected = tuple(
                    item for item in endpoint_projections if item.period_selection == selection
                )
                _resolve_projection_group(
                    rows,
                    selected,
                    requested_sessions,
                    instrument_set,
                    resolved,
                )
        return resolved


def _resolve_projection_group(
    rows: Sequence[Mapping[str, object]],
    projections: Sequence[_FieldProjection],
    sessions: tuple[str, ...],
    instrument_ids: frozenset[str],
    output: dict[str, dict[Coordinate, NumericValue]],
) -> None:
    annual = projections[0].period_selection == "annual"
    transitions = _state_transitions(rows, projections, instrument_ids, annual=annual)
    if transitions.num_rows == 0:
        return
    coordinates = _coordinate_table(sessions, tuple(sorted(instrument_ids)))
    aligned = coordinates.join_asof(
        transitions,
        on="session_date",
        by="instrument_id",
        tolerance=-100_000,
    )
    for projection in projections:
        available = aligned.filter(pc.is_valid(aligned[projection.field_id]))
        values = available.select(("session", "instrument_id", projection.field_id)).to_pydict()
        output[projection.field_id].update(
            {
                (str(session), str(instrument_id)): _numeric_value(value)
                for session, instrument_id, value in zip(
                    values["session"],
                    values["instrument_id"],
                    values[projection.field_id],
                    strict=True,
                )
            }
        )


def _state_transitions(
    rows: Sequence[Mapping[str, object]],
    projections: Sequence[_FieldProjection],
    instrument_ids: frozenset[str],
    *,
    annual: bool,
) -> pa.Table:
    accepted = sorted(
        (
            row
            for row in rows
            if str(row.get("instrument_id", "")) in instrument_ids
            and row.get("availability_status") == "available"
            and str(row.get("source_report_type", "")) == "1"
            and str(row.get("source_company_type", "")) in _COMPANY_TYPES
            and (not annual or str(row.get("source_report_period", "")).endswith("1231"))
        ),
        key=lambda row: (str(row.get("instrument_id", "")), _version_key(row)),
    )
    transitions: list[dict[str, object]] = []
    position = 0
    while position < len(accepted):
        instrument_id = str(accepted[position]["instrument_id"])
        latest_by_period: dict[str, Mapping[str, object]] = {}
        while position < len(accepted) and accepted[position]["instrument_id"] == instrument_id:
            available_session = str(accepted[position]["effective_available_session"])
            while (
                position < len(accepted)
                and accepted[position]["instrument_id"] == instrument_id
                and accepted[position]["effective_available_session"] == available_session
            ):
                row = accepted[position]
                latest_by_period[str(row["source_report_period"])] = row
                position += 1
            selected = latest_by_period[max(latest_by_period)]
            transitions.append(
                {
                    "session_date": date.fromisoformat(available_session),
                    "instrument_id": instrument_id,
                    **{
                        projection.field_id: selected.get(projection.source_column)
                        for projection in projections
                    },
                }
            )
    schema = pa.schema(
        [pa.field("session_date", pa.date32()), pa.field("instrument_id", pa.string())]
        + [pa.field(projection.field_id, pa.string()) for projection in projections]
    )
    return pa.Table.from_pylist(
        sorted(transitions, key=lambda row: (row["session_date"], row["instrument_id"])),
        schema=schema,
    )


def _coordinate_table(sessions: tuple[str, ...], instruments: tuple[str, ...]) -> pa.Table:
    session_dates = [date.fromisoformat(session) for session in sessions]
    return pa.table(
        {
            "session_date": pa.array(
                [session for session in session_dates for _instrument in instruments],
                type=pa.date32(),
            ),
            "instrument_id": pa.array(instruments * len(sessions), type=pa.string()),
            "session": pa.array(
                [session for session in sessions for _instrument in instruments],
                type=pa.string(),
            ),
        }
    )


def _version_key(row: Mapping[str, object]) -> tuple[str, str, int, str, str, str]:
    return (
        str(row.get("effective_available_session", "")),
        str(row.get("source_report_period", "")),
        1 if str(row.get("update_flag", "")) == "1" else 0,
        str(row.get("source_published_date", "")),
        str(row.get("first_observed_at", "")),
        str(row.get("source_row_sha256", "")),
    )


def _numeric_value(value: object) -> NumericValue:
    if isinstance(value, bool):
        raise FinancialSeriesError("FINANCIAL_VALUE_INVALID")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise FinancialSeriesError("FINANCIAL_VALUE_INVALID") from error
    if not numeric.is_finite():
        raise FinancialSeriesError("FINANCIAL_VALUE_INVALID")
    return value if isinstance(value, (Decimal, int, float, str)) else str(value)


def _validate_request(
    manifest_sha256: str,
    field_ids: tuple[str, ...],
    sessions: tuple[str, ...],
    instrument_ids: tuple[str, ...],
) -> None:
    try:
        valid_sessions = all(
            date.fromisoformat(session).isoformat() == session for session in sessions
        )
    except ValueError:
        valid_sessions = False
    if (
        len(manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in manifest_sha256)
        or not field_ids
        or len(set(field_ids)) != len(field_ids)
        or not sessions
        or sessions != tuple(sorted(set(sessions)))
        or not valid_sessions
        or not instrument_ids
        or instrument_ids != tuple(sorted(set(instrument_ids)))
        or any(not instrument_id for instrument_id in instrument_ids)
    ):
        raise FinancialSeriesError("FINANCIAL_SERIES_REQUEST_INVALID")
