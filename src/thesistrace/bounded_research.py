import math
from array import array
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from thesistrace.canonical_objects import (
    FAMILY_BY_TABLE,
    CanonicalFamily,
    partition_overlaps_window,
    partitioned_research_calendar_window,
    sort_partition_entries,
    validate_partition_entry,
)
from thesistrace.data.fields import authorable_field_bindings_from_snapshot
from thesistrace.ports import ObjectStorePort
from thesistrace.research_kernel.alpha import validate_alpha

INPUT_SESSIONS = 756
MISSING = math.nan
PRICE_FIELD_BY_ALPHA_FIELD = {
    "open_adj": "open_adj",
    "high_adj": "high_adj",
    "low_adj": "low_adj",
    "close_adj": "close_adj",
    "volume_shares": "volume_shares",
    "turnover_amount_cny": "turnover_cny",
}


class BoundedResearchError(RuntimeError):
    pass


@dataclass
class ColumnarResearchWindow:
    sessions: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    instruments: dict[str, dict[str, object]]
    universe_name: str
    universe_membership: dict[str, array]
    price_fields: dict[str, array]
    trading_states: bytearray
    upper_limits: array
    lower_limits: array
    st_designations: bytearray
    industry_membership: dict[str, tuple[dict[str, object], ...]]

    def __post_init__(self) -> None:
        self.session_index = {session: index for index, session in enumerate(self.sessions)}
        self.instrument_index = {
            instrument_id: index for index, instrument_id in enumerate(self.instrument_ids)
        }
        self.instrument_count = len(self.instrument_ids)

    def canonical_data(self) -> dict[str, object]:
        prices: list[dict[str, object]] = []
        trading_states: list[dict[str, object]] = []
        price_limits: list[dict[str, object]] = []
        st_designations: list[dict[str, object]] = []
        for session_index, session in enumerate(self.sessions):
            offset = session_index * self.instrument_count
            for instrument_index, instrument_id in enumerate(self.instrument_ids):
                position = offset + instrument_index
                price = {
                    field: values[position]
                    for field, values in self.price_fields.items()
                    if not math.isnan(values[position])
                }
                if price:
                    prices.append(
                        {
                            "session": session,
                            "instrument_id": instrument_id,
                            **price,
                        }
                    )
                state = self.trading_states[position]
                if state:
                    trading_states.append(
                        {
                            "session": session,
                            "instrument_id": instrument_id,
                            "state": ("normal" if state == 1 else "full_session_suspension"),
                        }
                    )
                upper = self.upper_limits[position]
                lower = self.lower_limits[position]
                if not math.isnan(upper) and not math.isnan(lower):
                    price_limits.append(
                        {
                            "session": session,
                            "instrument_id": instrument_id,
                            "upper": upper,
                            "lower": lower,
                        }
                    )
                if self.st_designations[position]:
                    st_designations.append({"trade_date": session, "instrument_id": instrument_id})
        return {
            "research_calendar": list(self.sessions),
            "instruments": [self.instruments[value] for value in self.instrument_ids],
            "prices": prices,
            "trading_states": trading_states,
            "price_limits": price_limits,
            "liquidity_universes": {
                self.universe_name: [
                    {
                        "session": session,
                        "instrument_ids": [
                            self.instrument_ids[index]
                            for index in self.universe_membership[session]
                        ],
                    }
                    for session in self.sessions
                ]
            },
            "st_designations": st_designations,
            "industry_membership": [
                dict(row)
                for instrument_id in self.instrument_ids
                for row in self.industry_membership.get(instrument_id, ())
            ],
        }


def load_columnar_research_window(
    objects: ObjectStorePort,
    release: Mapping[str, object],
    definition: Mapping[str, object],
) -> ColumnarResearchWindow:
    entries_value = release.get("objects")
    if not isinstance(entries_value, list):
        raise BoundedResearchError("Dataset Release has no object manifest")
    entries = [
        entry
        for entry in entries_value
        if isinstance(entry, dict) and entry.get("kind") == "canonical_partition"
    ]
    if not entries:
        raise BoundedResearchError("Dataset Release is not partitioned Parquet")
    final_session = str(
        _mapping(release.get("appended_session_range"), "appended session range")["end"]
    )
    sessions = tuple(
        partitioned_research_calendar_window(
            objects,
            entries,
            final_session=final_session,
            session_count=INPUT_SESSIONS,
        )
    )
    if len(sessions) != INPUT_SESSIONS:
        raise BoundedResearchError("ResearchRun requires exactly 756 input sessions")
    first_session = sessions[0]
    session_index = {session: index for index, session in enumerate(sessions)}

    instrument_rows = _read_static_rows(objects, entries, "instruments")
    instrument_reference = {str(row["instrument_id"]): dict(row) for row in instrument_rows}
    universe_name = str(definition["universe"])
    global_ids = tuple(sorted(instrument_reference))
    global_index = {value: index for index, value in enumerate(global_ids)}
    global_membership: dict[str, array] = {session: array("I") for session in sessions}
    selected_global: set[int] = set()
    family = FAMILY_BY_TABLE["liquidity_universes"]
    for batch in _window_batches(
        objects,
        entries,
        family,
        first_session,
        final_session,
        columns=("session", "universe", "instrument_ids"),
    ):
        session_values = batch.column("session")
        universe_values = batch.column("universe")
        instrument_values = batch.column("instrument_ids")
        for row_index in range(batch.num_rows):
            session = str(session_values[row_index].as_py())
            if (
                session not in session_index
                or str(universe_values[row_index].as_py()) != universe_name
            ):
                continue
            membership = array("I")
            for instrument_id in instrument_values[row_index].as_py():
                index = global_index.get(str(instrument_id))
                if index is None:
                    raise BoundedResearchError(
                        "Liquidity Universe references an unknown instrument"
                    )
                membership.append(index)
                selected_global.add(index)
            global_membership[session] = membership
    selected_ids = tuple(global_ids[index] for index in sorted(selected_global))
    if not selected_ids:
        raise BoundedResearchError("selected Liquidity Universe is empty")
    compact_by_global = {
        global_value: compact for compact, global_value in enumerate(sorted(selected_global))
    }
    universe_membership = {
        session: array(
            "I",
            (compact_by_global[value] for value in global_membership[session]),
        )
        for session in sessions
    }
    compact_index = {value: index for index, value in enumerate(selected_ids)}
    cell_count = len(sessions) * len(selected_ids)

    alpha = _mapping(definition.get("alpha"), "Alpha definition")
    parsed = validate_alpha(
        alpha["expression"],
        field_bindings=authorable_field_bindings_from_snapshot(definition.get("field_bindings")),
    )
    price_columns = {PRICE_FIELD_BY_ALPHA_FIELD[field] for field in parsed.field_names} | {
        "open_adj",
        "open_raw",
    }
    price_fields = {field: array("d", [MISSING]) * cell_count for field in price_columns}
    price_family = FAMILY_BY_TABLE["prices"]
    selected_price_columns = ("session", "instrument_id", *sorted(price_columns))
    for batch in _window_batches(
        objects,
        entries,
        price_family,
        first_session,
        final_session,
        columns=selected_price_columns,
    ):
        columns = {name: batch.column(name).to_pylist() for name in selected_price_columns}
        for row_index, session_value in enumerate(columns["session"]):
            session_position = session_index.get(str(session_value))
            instrument_position = compact_index.get(str(columns["instrument_id"][row_index]))
            if session_position is None or instrument_position is None:
                continue
            position = session_position * len(selected_ids) + instrument_position
            for field in price_columns:
                value = columns[field][row_index]
                if value is not None:
                    price_fields[field][position] = float(value)

    trading_states = bytearray(cell_count)
    state_family = FAMILY_BY_TABLE["trading_states"]
    for batch in _window_batches(
        objects,
        entries,
        state_family,
        first_session,
        final_session,
        columns=("session", "instrument_id", "state"),
    ):
        for row in batch.to_pylist():
            position = _flat_position(row, session_index, compact_index, len(selected_ids))
            if position is not None:
                trading_states[position] = 2 if row["state"] == "full_session_suspension" else 1

    upper_limits = array("d", [MISSING]) * cell_count
    lower_limits = array("d", [MISSING]) * cell_count
    limit_family = FAMILY_BY_TABLE["price_limits"]
    for batch in _window_batches(
        objects,
        entries,
        limit_family,
        first_session,
        final_session,
        columns=("session", "instrument_id", "upper", "lower"),
    ):
        for row in batch.to_pylist():
            position = _flat_position(row, session_index, compact_index, len(selected_ids))
            if position is not None:
                upper_limits[position] = float(row["upper"])
                lower_limits[position] = float(row["lower"])

    st_designations = bytearray(cell_count)
    st_family = FAMILY_BY_TABLE["st_designations"]
    for batch in _window_batches(
        objects,
        entries,
        st_family,
        first_session,
        final_session,
        columns=("trade_date", "instrument_id"),
    ):
        for row in batch.to_pylist():
            session_position = session_index.get(str(row["trade_date"]))
            instrument_position = compact_index.get(str(row["instrument_id"]))
            if session_position is not None and instrument_position is not None:
                st_designations[session_position * len(selected_ids) + instrument_position] = 1

    industry_rows: dict[str, list[dict[str, object]]] = {}
    for row in _read_static_rows(objects, entries, "industry_membership"):
        instrument_id = str(row["instrument_id"])
        if instrument_id in compact_index:
            industry_rows.setdefault(instrument_id, []).append(row)
    industry_membership = {
        instrument_id: tuple(sorted(rows, key=lambda row: str(row["active_from"])))
        for instrument_id, rows in industry_rows.items()
    }
    return ColumnarResearchWindow(
        sessions=sessions,
        instrument_ids=selected_ids,
        instruments={value: instrument_reference[value] for value in selected_ids},
        universe_name=universe_name,
        universe_membership=universe_membership,
        price_fields=price_fields,
        trading_states=trading_states,
        upper_limits=upper_limits,
        lower_limits=lower_limits,
        st_designations=st_designations,
        industry_membership=industry_membership,
    )


def _flat_position(
    row: Mapping[str, object],
    session_index: Mapping[str, int],
    instrument_index: Mapping[str, int],
    instrument_count: int,
) -> int | None:
    session = str(row.get("session") or row.get("trade_date"))
    session_position = session_index.get(session)
    instrument_position = instrument_index.get(str(row["instrument_id"]))
    if session_position is None or instrument_position is None:
        return None
    return session_position * instrument_count + instrument_position


def _read_static_rows(
    objects: ObjectStorePort,
    entries: Sequence[Mapping[str, object]],
    table_name: str,
) -> list[dict[str, object]]:
    family = FAMILY_BY_TABLE[table_name]
    rows: list[dict[str, object]] = []
    for batch in _window_batches(
        objects,
        entries,
        family,
        None,
        None,
        columns=tuple(family.schema.names),
    ):
        rows.extend(batch.to_pylist())
    return rows


def _window_batches(
    objects: ObjectStorePort,
    entries: Sequence[Mapping[str, object]],
    family: CanonicalFamily,
    first_session: str | None,
    final_session: str | None,
    *,
    columns: Sequence[str],
) -> Iterator[pa.RecordBatch]:
    for entry in sort_partition_entries(entries):
        if entry.get("family") != family.family:
            continue
        validate_partition_entry(entry, family)
        if not partition_overlaps_window(
            entry,
            family,
            first_session=first_session,
            final_session=final_session,
        ):
            continue
        payload = objects.read_parquet_bytes(str(entry["sha256"]))
        parquet = pq.ParquetFile(pa.BufferReader(payload))
        if not parquet.schema_arrow.equals(family.schema, check_metadata=True):
            raise BoundedResearchError(f"Canonical partition schema mismatch: {family.family}")
        if parquet.metadata.num_row_groups != 1:
            raise BoundedResearchError(f"Canonical partition row-group mismatch: {family.family}")
        yield from parquet.iter_batches(batch_size=8192, columns=list(columns))


def _mapping(value: Any, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BoundedResearchError(f"{name} is invalid")
    return value
