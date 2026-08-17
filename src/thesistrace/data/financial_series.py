from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.data.fields import FINANCIAL_FIELDS
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

    def read_financial_table(
        self,
        manifest_sha256: str,
        endpoint: str,
        source_columns: tuple[str, ...],
        sessions: tuple[str, ...],
        instrument_ids: frozenset[str],
    ) -> pa.Table: ...


@dataclass(frozen=True)
class _FieldProjection:
    field_id: str
    endpoint: str
    source_column: str
    period_selection: str


_PROJECTIONS = tuple(
    _FieldProjection(
        field.field_id,
        field.source_endpoint,
        field.source_column,
        "annual"
        if field.report_period_selection == "latest_visible_full_year"
        else "latest_reported",
    )
    for field in FINANCIAL_FIELDS
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

    def resolve_table(
        self,
        *,
        manifest_sha256: str,
        field_ids: Sequence[str],
        sessions: Sequence[str],
        instrument_ids: Sequence[str],
    ) -> pa.Table:
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
        coordinates = _coordinate_table(requested_sessions, tuple(sorted(instrument_set)))
        result = coordinates.select(("session", "instrument_id"))
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
            table = self._reader.read_financial_table(
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
                aligned = _resolve_projection_group_table(
                    table,
                    selected,
                    requested_sessions,
                    instrument_set,
                )
                for projection in selected:
                    result = result.append_column(
                        projection.field_id,
                        aligned[projection.field_id],
                    )
        return result.select(("session", "instrument_id", *fields))


def _resolve_projection_group(
    rows: Sequence[Mapping[str, object]],
    projections: Sequence[_FieldProjection],
    sessions: tuple[str, ...],
    instrument_ids: frozenset[str],
    output: dict[str, dict[Coordinate, NumericValue]],
) -> None:
    annual = projections[0].period_selection == "annual"
    aligned = _align_projection_group(
        _state_transitions_rows(rows, projections, instrument_ids, annual=annual),
        projections,
        sessions,
        instrument_ids,
    )
    if aligned.num_rows == 0:
        return
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


def _resolve_projection_group_table(
    table: pa.Table,
    projections: Sequence[_FieldProjection],
    sessions: tuple[str, ...],
    instrument_ids: frozenset[str],
) -> pa.Table:
    annual = projections[0].period_selection == "annual"
    transitions = _state_transitions_table(
        table,
        projections,
        instrument_ids,
        annual=annual,
    )
    return _align_projection_group(transitions, projections, sessions, instrument_ids)


def _align_projection_group(
    transitions: pa.Table,
    projections: Sequence[_FieldProjection],
    sessions: tuple[str, ...],
    instrument_ids: frozenset[str],
) -> pa.Table:
    if transitions.num_rows == 0:
        empty = _coordinate_table(sessions, tuple(sorted(instrument_ids))).select(
            ("session", "instrument_id")
        )
        for projection in projections:
            empty = empty.append_column(
                projection.field_id,
                pa.nulls(empty.num_rows, type=pa.string()),
            )
        return empty
    coordinates = _coordinate_table(sessions, tuple(sorted(instrument_ids)))
    return coordinates.join_asof(
        transitions,
        on="session_date",
        by="instrument_id",
        tolerance=-100_000,
    ).select(("session", "instrument_id", *(item.field_id for item in projections)))


def _state_transitions_rows(
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


def _state_transitions_table(
    table: pa.Table,
    projections: Sequence[_FieldProjection],
    instrument_ids: frozenset[str],
    *,
    annual: bool,
) -> pa.Table:
    schema = _transition_schema(projections)
    if table.num_rows == 0:
        return pa.Table.from_batches([], schema=schema)
    accepted_mask = pc.and_kleene(
        pc.and_kleene(
            pc.is_in(table["instrument_id"], value_set=pa.array(sorted(instrument_ids))),
            pc.equal(table["availability_status"], "available"),
        ),
        pc.and_kleene(
            pc.equal(table["source_report_type"], "1"),
            pc.is_in(table["source_company_type"], value_set=pa.array(sorted(_COMPANY_TYPES))),
        ),
    )
    if annual:
        accepted_mask = pc.and_kleene(
            accepted_mask,
            pc.ends_with(table["source_report_period"], "1231"),
        )
    accepted = table.filter(pc.fill_null(accepted_mask, False))
    transitions: list[pa.Table] = []
    for instrument_id in sorted(instrument_ids):
        instrument = accepted.filter(pc.equal(accepted["instrument_id"], instrument_id))
        if instrument.num_rows == 0:
            continue
        instrument = instrument.append_column(
            "_report_period_order",
            pc.cast(instrument["source_report_period"], pa.int64()),
        ).append_column(
            "_update_order",
            pc.cast(
                pc.fill_null(pc.equal(instrument["update_flag"], "1"), False),
                pa.int8(),
            ),
        )
        instrument = instrument.sort_by(
            [
                ("effective_available_session", "ascending"),
                ("_report_period_order", "ascending"),
                ("_update_order", "ascending"),
                ("source_published_date", "ascending"),
                ("first_observed_at", "ascending"),
                ("source_row_sha256", "ascending"),
            ]
        )
        candidates = instrument.filter(
            pc.equal(
                instrument["_report_period_order"],
                pc.cumulative_max(instrument["_report_period_order"]),
            )
        )
        available_sessions = candidates["effective_available_session"].combine_chunks()
        last_at_session = pa.concat_arrays(
            [
                pc.not_equal(
                    available_sessions.slice(0, max(0, len(available_sessions) - 1)),
                    available_sessions.slice(1),
                ),
                pa.array([True]),
            ]
        )
        latest = candidates.filter(last_at_session)
        transitions.append(
            pa.table(
                {
                    "session_date": pc.cast(latest["effective_available_session"], pa.date32()),
                    "instrument_id": latest["instrument_id"],
                    **{
                        projection.field_id: latest[projection.source_column]
                        for projection in projections
                    },
                },
                schema=schema,
            )
        )
    if not transitions:
        return pa.Table.from_batches([], schema=schema)
    return pa.concat_tables(transitions).sort_by(
        [("session_date", "ascending"), ("instrument_id", "ascending")]
    )


def _transition_schema(projections: Sequence[_FieldProjection]) -> pa.Schema:
    return pa.schema(
        [pa.field("session_date", pa.date32()), pa.field("instrument_id", pa.string())]
        + [pa.field(projection.field_id, pa.string()) for projection in projections]
    )


def _coordinate_table(sessions: tuple[str, ...], instruments: tuple[str, ...]) -> pa.Table:
    session_axis = pa.array(sessions, type=pa.string())
    instrument_axis = pa.array(instruments, type=pa.string())
    session_indices = pa.array(
        np.repeat(np.arange(len(sessions), dtype=np.int64), len(instruments))
    )
    instrument_indices = pa.array(
        np.tile(np.arange(len(instruments), dtype=np.int64), len(sessions))
    )
    expanded_sessions = pc.take(session_axis, session_indices)
    return pa.table(
        {
            "session_date": pc.cast(expanded_sessions, pa.date32()),
            "instrument_id": pc.take(instrument_axis, instrument_indices),
            "session": expanded_sessions,
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
