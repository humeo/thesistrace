from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.data.fields import DAILY_BASIC_FIELDS

_PROJECTIONS = {field.field_id: field.source_column for field in DAILY_BASIC_FIELDS}
type DailyBasicTableReader = Callable[[set[str], frozenset[str], set[str]], pa.Table]


class DailyBasicSeriesResolver:
    """Resolve a frozen daily family by exact coordinates, with no forward fill."""

    def __init__(self, manifest_sha256: str, read_table: DailyBasicTableReader) -> None:
        self._manifest_sha256 = manifest_sha256
        self._read_table = read_table

    def _read(
        self, manifest_sha256: str, field_ids: Sequence[str], sessions: Sequence[str],
        instrument_ids: Sequence[str],
    ) -> pa.Table:
        if (
            manifest_sha256 != self._manifest_sha256
            or set(field_ids) - set(_PROJECTIONS)
            or len(field_ids) != len(set(field_ids))
            or list(sessions) != sorted(set(sessions))
            or len(instrument_ids) != len(set(instrument_ids))
        ):
            raise ValueError("Daily basic Series request is invalid")
        columns = {"session", "instrument_id", *(_PROJECTIONS[f] for f in field_ids)}
        return self._read_table(set(sessions), frozenset(instrument_ids), columns)

    def resolve(
        self, *, manifest_sha256: str, field_ids: Sequence[str], sessions: Sequence[str],
        instrument_ids: Sequence[str],
    ) -> dict[str, dict[tuple[str, str], object]]:
        table = self._read(manifest_sha256, field_ids, sessions, instrument_ids)
        rows = table.to_pylist()
        return {field_id: {
            (row["session"], row["instrument_id"]): row[_PROJECTIONS[field_id]] for row in rows
        } for field_id in field_ids}

    def resolve_table(
        self, *, manifest_sha256: str, field_ids: Sequence[str], sessions: Sequence[str],
        instrument_ids: Sequence[str],
    ) -> pa.Table:
        table = self._read(manifest_sha256, field_ids, sessions, instrument_ids)
        axis = pa.table({
            "session": pc.take(pa.array(sessions, type=pa.string()),
                               pa.array(np.repeat(np.arange(len(sessions)), len(instrument_ids)))),
            "instrument_id": pc.take(pa.array(instrument_ids, type=pa.string()),
                                     pa.array(np.tile(
                                         np.arange(len(instrument_ids)), len(sessions),
                                     ))),
        })
        values = table.select(["session", "instrument_id", *(_PROJECTIONS[f] for f in field_ids)])
        values = values.rename_columns(["session", "instrument_id", *field_ids])
        values = values.append_column("source_row_present", pa.array([True] * values.num_rows))
        return axis.join(values, keys=["session", "instrument_id"], join_type="left outer").sort_by(
            [("session", "ascending"), ("instrument_id", "ascending")]
        )
