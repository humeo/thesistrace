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
    sorted_instruments = tuple(sorted(instrument_ids))
    coordinates = _coordinate_table(sessions, sorted_instruments)
    ordered = transitions.sort_by(
        [("instrument_id", "ascending"), ("session_date", "ascending")]
    )
    transition_instruments = ordered["instrument_id"].combine_chunks()
    group_starts = np.empty(ordered.num_rows, dtype=np.bool_)
    group_starts[0] = True
    group_starts[1:] = pc.not_equal(
        transition_instruments.slice(0, ordered.num_rows - 1),
        transition_instruments.slice(1),
    ).to_numpy(zero_copy_only=False)
    start_indices = np.flatnonzero(group_starts)
    end_indices = np.append(start_indices[1:], ordered.num_rows)
    requested_dates = np.asarray(sessions, dtype="datetime64[D]")
    transition_dates = ordered["session_date"].combine_chunks().to_numpy(
        zero_copy_only=False
    )
    instrument_positions = {
        instrument_id: position for position, instrument_id in enumerate(sorted_instruments)
    }
    aligned_indices = np.zeros(len(sessions) * len(sorted_instruments), dtype=np.int64)
    missing = np.ones(aligned_indices.size, dtype=np.bool_)
    session_offsets = np.arange(len(sessions), dtype=np.int64) * len(sorted_instruments)
    for start, end in zip(start_indices, end_indices, strict=True):
        instrument_id = str(transition_instruments[start].as_py())
        selected = np.searchsorted(
            transition_dates[start:end], requested_dates, side="right"
        ) - 1
        available = selected >= 0
        output_positions = session_offsets + instrument_positions[instrument_id]
        aligned_indices[output_positions[available]] = start + selected[available]
        missing[output_positions[available]] = False
    take_indices = pa.array(aligned_indices, mask=missing)
    result = coordinates.select(("session", "instrument_id"))
    for projection in projections:
        result = result.append_column(
            projection.field_id,
            pc.take(ordered[projection.field_id], take_indices),
        )
    return result


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
    accepted = accepted.append_column(
        "_report_period_order",
        pc.cast(accepted["source_report_period"], pa.int64()),
    ).append_column(
        "_update_order",
        pc.cast(
            pc.fill_null(pc.equal(accepted["update_flag"], "1"), False),
            pa.int8(),
        ),
    )
    accepted = accepted.sort_by(
        [
            ("instrument_id", "ascending"),
            ("effective_available_session", "ascending"),
            ("_report_period_order", "ascending"),
            ("_update_order", "ascending"),
            ("source_published_date", "ascending"),
            ("first_observed_at", "ascending"),
            ("source_row_sha256", "ascending"),
        ]
    )
    instrument_column = accepted["instrument_id"].combine_chunks()
    report_periods = accepted["_report_period_order"].combine_chunks().to_numpy()
    group_starts = np.empty(accepted.num_rows, dtype=np.bool_)
    group_starts[0] = True
    group_starts[1:] = pc.not_equal(
        instrument_column.slice(0, accepted.num_rows - 1),
        instrument_column.slice(1),
    ).to_numpy(zero_copy_only=False)
    start_indices = np.flatnonzero(group_starts)
    end_indices = np.append(start_indices[1:], accepted.num_rows)
    candidate_mask = np.zeros(accepted.num_rows, dtype=np.bool_)
    for start, end in zip(start_indices, end_indices, strict=True):
        periods = report_periods[start:end]
        candidate_mask[start:end] = periods == np.maximum.accumulate(periods)
    candidates = accepted.filter(pa.array(candidate_mask))
    if candidates.num_rows == 0:
        return pa.Table.from_batches([], schema=schema)
    candidate_instruments = candidates["instrument_id"].combine_chunks()
    available_sessions = candidates["effective_available_session"].combine_chunks()
    if candidates.num_rows == 1:
        last_at_session = pa.array([True])
    else:
        same_instrument = pc.equal(
            candidate_instruments.slice(0, candidates.num_rows - 1),
            candidate_instruments.slice(1),
        )
        same_session = pc.equal(
            available_sessions.slice(0, candidates.num_rows - 1),
            available_sessions.slice(1),
        )
        last_at_session = pa.concat_arrays(
            [pc.invert(pc.and_kleene(same_instrument, same_session)), pa.array([True])]
        )
    latest = candidates.filter(last_at_session)
    transitions = pa.table(
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
    return transitions.sort_by(
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
