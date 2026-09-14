"""Resolve sparse supplier indicator states for a frozen family."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from math import isfinite

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.data.fields import FINANCIAL_INDICATOR_FIELDS

_FIELDS = {field.field_id: field for field in FINANCIAL_INDICATOR_FIELDS}
_METADATA = {
    "instrument_id",
    "source_report_period",
    "source_published_date",
    "state_effective_session",
    "availability_status",
    "observation_event_at",
}
type IndicatorTableReader = Callable[[set[str], frozenset[str], str], pa.Table]


def normalize_indicator_value(source: object, *, source_unit: str) -> float | None:
    if source is None:
        return None
    try:
        number = Decimal(str(source))
        if not number.is_finite():
            raise ValueError("Non-finite financial indicator")
        if source_unit == "percent":
            number /= 100
        value = float(number)
        if not isfinite(value):
            raise ValueError("Unrepresentable financial indicator")
        return value
    except (InvalidOperation, OverflowError) as error:
        raise ValueError("Invalid financial indicator number") from error


class FinancialIndicatorSeriesResolver:
    def __init__(self, manifest_sha256: str, read_table: IndicatorTableReader) -> None:
        self._manifest_sha256 = manifest_sha256
        self._read_table = read_table

    def resolve_table(
        self,
        *,
        manifest_sha256: str,
        field_ids: Sequence[str],
        sessions: Sequence[str],
        instrument_ids: Sequence[str],
    ) -> pa.Table:
        if (
            manifest_sha256 != self._manifest_sha256
            or set(field_ids) - set(_FIELDS)
            or len(set(field_ids)) != len(field_ids)
            or tuple(sessions) != tuple(sorted(set(sessions)))
            or len(set(instrument_ids)) != len(instrument_ids)
        ):
            raise ValueError("Invalid financial indicator Series request")
        schema = pa.schema(
            [
                ("session", pa.string()),
                ("instrument_id", pa.string()),
                *((field, pa.float64()) for field in field_ids),
            ]
        )
        if not sessions or not instrument_ids:
            return pa.Table.from_pylist([], schema=schema)
        fields = [_FIELDS[field] for field in field_ids]
        table = self._read_table(
            _METADATA | {field.source_column for field in fields},
            frozenset(instrument_ids),
            sessions[-1],
        )
        ordered_instruments = tuple(sorted(instrument_ids))
        width = len(ordered_instruments)
        values = {
            field.field_id: np.full(len(sessions) * width, np.nan, dtype=np.float64)
            for field in fields
        }
        for instrument_index, instrument in enumerate(ordered_instruments):
            facts = table.filter(pc.equal(table["instrument_id"], instrument)).to_pylist()
            facts = [row for row in facts if row["state_effective_session"] is not None]
            facts = _agreeing_observation_states(
                facts, tuple(field.source_column for field in fields),
            )
            facts.sort(
                key=lambda row: (row["state_effective_session"], row["observation_event_at"])
            )
            states = {}
            position = 0
            for session_index, session in enumerate(sessions):
                while (
                    position < len(facts) and facts[position]["state_effective_session"] <= session
                ):
                    row = facts[position]
                    key = (row["source_report_period"], row["source_published_date"])
                    previous = states.get(key)
                    if (
                        previous is not None
                        and previous["observation_event_at"] == row["observation_event_at"]
                        and previous != row
                    ):
                        row = {**row, "availability_status": "conflicting_observation"}
                    states[key] = row
                    position += 1
                selected = states[max(states)] if states else None
                for field in fields:
                    value = None
                    if selected is not None and selected["availability_status"] == "available":
                        value = normalize_indicator_value(
                            selected[field.source_column], source_unit=field.source_unit,
                        )
                    if value is not None:
                        values[field.field_id][session_index * width + instrument_index] = value
        return pa.Table.from_arrays(
            [
                pc.take(pa.array(sessions, type=pa.string()),
                        pa.array(np.repeat(np.arange(len(sessions)), width))),
                pc.take(pa.array(ordered_instruments, type=pa.string()),
                        pa.array(np.tile(np.arange(width), len(sessions)))),
                *(pa.array(values[field], mask=np.isnan(values[field])) for field in field_ids),
            ],
            schema=schema,
        )

    def resolve(self, **request) -> dict[str, dict[tuple[str, str], float | None]]:
        table = self.resolve_table(**request)
        return {
            field: {(row["session"], row["instrument_id"]): row[field] for row in table.to_pylist()}
            for field in request["field_ids"]
        }


def _agreeing_observation_states(
    rows: list[dict[str, object]], source_columns: Sequence[str],
) -> list[dict[str, object]]:
    """Project each simultaneous source group without selecting a winning row."""
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(row["source_report_period"], row["source_published_date"],
                 row["observation_event_at"], row["state_effective_session"])].append(row)
    states = []
    for group in grouped.values():
        if len(group) == 1:
            states.append(group[0])
            continue
        state = dict(group[0])
        state["availability_status"] = (
            "available" if all(row["availability_status"] in
                               {"available", "conflicting_observation"} for row in group)
            else "conflicting_observation"
        )
        for column in source_columns:
            values = {row[column] for row in group}
            state[column] = next(iter(values)) if len(values) == 1 else None
        states.append(state)
    return states
