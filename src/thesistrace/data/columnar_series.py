"""Arrow-backed Research Series views over one bounded calculation slice."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import TypeVar

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.research_series import (
    ColumnarResearchSeries,
    ExecutionPrice,
    InstrumentProfile,
    PriceLimit,
)

T = TypeVar("T")


def _sorted_table(table: pa.Table, columns: Sequence[str]) -> pa.Table:
    if table.num_rows < 2:
        return table.combine_chunks()
    return table.take(pc.sort_indices(table, sort_keys=[(name, "ascending") for name in columns]))


def _session_filter(table: pa.Table, column: str, sessions: tuple[str, ...]) -> pa.Table:
    return table.filter(pc.is_in(table[column], value_set=pa.array(sessions)))


class _CoordinateValues(Mapping[tuple[str, str], T]):
    def __init__(
        self,
        table: pa.Table,
        *,
        session_column: str,
        value_columns: tuple[str, ...],
        convert,
    ) -> None:
        ordered = table.combine_chunks()
        sessions = ordered[session_column].combine_chunks().to_pylist()
        instruments = ordered["instrument_id"].combine_chunks().to_pylist()
        self._keys = tuple(
            (str(session), str(instrument))
            for session, instrument in zip(sessions, instruments, strict=True)
        )
        self._columns = tuple(ordered[name].combine_chunks() for name in value_columns)
        self._convert = convert
        self._cache: dict[tuple[str, str], T] = {}

    def __getitem__(self, coordinate: tuple[str, str]) -> T:
        cached = self._cache.get(coordinate)
        if cached is not None:
            return cached
        position = bisect_left(self._keys, coordinate)
        if position == len(self._keys) or self._keys[position] != coordinate:
            raise KeyError(coordinate)
        values = tuple(column[position].as_py() for column in self._columns)
        if any(value is None for value in values):
            raise KeyError(coordinate)
        result = self._convert(*values)
        self._cache[coordinate] = result
        return result

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


class _InstrumentProfiles(Mapping[str, InstrumentProfile]):
    def __init__(self, table: pa.Table) -> None:
        self._table = table.combine_chunks()
        self._ids = tuple(
            map(str, self._table["instrument_id"].combine_chunks().to_pylist())
        )
        self._cache: dict[str, InstrumentProfile] = {}

    def __getitem__(self, instrument_id: str) -> InstrumentProfile:
        cached = self._cache.get(instrument_id)
        if cached is not None:
            return cached
        position = bisect_left(self._ids, instrument_id)
        if position == len(self._ids) or self._ids[position] != instrument_id:
            raise KeyError(instrument_id)
        result = InstrumentProfile(
            board=str(self._table["board"][position].as_py()),
            listed_to=str(self._table["listed_to"][position].as_py() or ""),
        )
        self._cache[instrument_id] = result
        return result

    def __iter__(self) -> Iterator[str]:
        return (str(value) for value in self._ids)

    def __len__(self) -> int:
        return len(self._ids)


class _UniverseMembers(Mapping[str, tuple[str, ...]]):
    def __init__(self, table: pa.Table) -> None:
        self._table = table.combine_chunks()
        self._sessions = tuple(map(str, self._table["session"].combine_chunks().to_pylist()))
        self._cache: dict[str, tuple[str, ...]] = {}

    def __getitem__(self, session: str) -> tuple[str, ...]:
        cached = self._cache.get(session)
        if cached is not None:
            return cached
        position = bisect_left(self._sessions, session)
        if position == len(self._sessions) or self._sessions[position] != session:
            raise KeyError(session)
        values = self._table["instrument_ids"][position].as_py()
        result = tuple(str(value) for value in values)
        self._cache[session] = result
        return result

    def __iter__(self) -> Iterator[str]:
        return (str(value) for value in self._sessions)

    def __len__(self) -> int:
        return len(self._sessions)


class _IndustryMembership(Mapping[tuple[str, str], str]):
    def __init__(self, table: pa.Table) -> None:
        self._table = table.combine_chunks()

    def __getitem__(self, coordinate: tuple[str, str]) -> str:
        session, instrument_id = coordinate
        mask = pc.and_(
            pc.equal(self._table["instrument_id"], instrument_id),
            pc.and_(
                pc.less_equal(self._table["active_from"], session),
                pc.or_(
                    pc.equal(self._table["active_to"], ""),
                    pc.greater(self._table["active_to"], session),
                ),
            ),
        )
        visible = self._table.filter(mask)
        if visible.num_rows == 0:
            raise KeyError(coordinate)
        return str(visible["sw2021_l1"][visible.num_rows - 1].as_py())

    def __iter__(self) -> Iterator[tuple[str, str]]:
        raise TypeError("Industry membership is a point-in-time lookup")

    def __len__(self) -> int:
        return self._table.num_rows


@dataclass(frozen=True)
class ColumnarResearchData:
    sessions: tuple[str, ...]
    _instruments: pa.Table
    _eod_prices: pa.Table
    _universes: pa.Table
    _trading_states: pa.Table
    _price_limits: pa.Table
    _industries: pa.Table
    _financial_values: pa.Table | None
    _field_columns: Mapping[str, str]

    @cached_property
    def instruments(self) -> Mapping[str, InstrumentProfile]:
        return _InstrumentProfiles(self._instruments)

    @cached_property
    def universe_members(self) -> Mapping[str, tuple[str, ...]]:
        return _UniverseMembers(self._universes)

    @cached_property
    def fields(self) -> Mapping[str, Mapping[tuple[str, str], object]]:
        market = {
            field_id: _CoordinateValues(
                self._eod_prices,
                session_column="session_date",
                value_columns=(column,),
                convert=lambda value: value,
            )
            for field_id, column in self._field_columns.items()
            if column in self._eod_prices.column_names
        }
        if self._financial_values is not None:
            market.update(
                {
                    field_id: _CoordinateValues(
                        self._financial_values,
                        session_column="session",
                        value_columns=(field_id,),
                        convert=lambda value: value,
                    )
                    for field_id in self._field_columns
                    if field_id in self._financial_values.column_names
                }
            )
        return market

    @cached_property
    def execution_prices(self) -> Mapping[tuple[str, str], ExecutionPrice]:
        return _CoordinateValues(
            self._eod_prices,
            session_column="session_date",
            value_columns=("open_raw", "open_adj"),
            convert=lambda raw, adjusted: ExecutionPrice(str(raw), str(adjusted)),
        )

    @cached_property
    def trading_states(self) -> Mapping[tuple[str, str], str]:
        return _CoordinateValues(
            self._trading_states,
            session_column="session",
            value_columns=("state",),
            convert=str,
        )

    @cached_property
    def price_limits(self) -> Mapping[tuple[str, str], PriceLimit]:
        return _CoordinateValues(
            self._price_limits,
            session_column="session",
            value_columns=("upper", "lower"),
            convert=lambda upper, lower: PriceLimit(str(upper), str(lower)),
        )

    @cached_property
    def industries(self) -> Mapping[tuple[str, str], str]:
        return _IndustryMembership(self._industries)

    def snapshot(self) -> ColumnarResearchData:
        return self

    def numeric_field_matrices(
        self,
        field_ids: tuple[str, ...],
        instruments: tuple[str, ...],
    ) -> Mapping[str, np.ndarray]:
        shape = (len(instruments), len(self.sessions))
        matrices: dict[str, np.ndarray] = {}
        for field_id in field_ids:
            if (
                self._financial_values is not None
                and field_id in self._financial_values.column_names
            ):
                matrices[field_id] = _numeric_matrix(
                    self._financial_values,
                    session_column="session",
                    value_column=field_id,
                    sessions=self.sessions,
                    instruments=instruments,
                    shape=shape,
                )
                continue
            matrices[field_id] = _numeric_matrix(
                self._eod_prices,
                session_column="session_date",
                value_column=self._field_columns[field_id],
                sessions=self.sessions,
                instruments=instruments,
                shape=shape,
            )
        return matrices

    def adjusted_open_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        axis, matrix = self._adjusted_open_axis
        if instruments != axis:
            positions = [axis.index(instrument_id) for instrument_id in instruments]
            return matrix[positions]
        return matrix

    def adjusted_open_decimal_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        axis, matrix = self._adjusted_open_decimal_axis
        if instruments != axis:
            positions = [axis.index(instrument_id) for instrument_id in instruments]
            return matrix[positions]
        return matrix

    @cached_property
    def _adjusted_open_axis(self) -> tuple[tuple[str, ...], np.ndarray]:
        instruments = tuple(sorted(self.instruments))
        matrix = _numeric_matrix(
            self._eod_prices,
            session_column="session_date",
            value_column="open_adj",
            sessions=self.sessions,
            instruments=instruments,
            shape=(len(instruments), len(self.sessions)),
        )
        return instruments, matrix

    @cached_property
    def _adjusted_open_decimal_axis(self) -> tuple[tuple[str, ...], np.ndarray]:
        instruments = tuple(sorted(self.instruments))
        matrix = _object_matrix(
            self._eod_prices,
            session_column="session_date",
            value_column="open_adj",
            sessions=self.sessions,
            instruments=instruments,
        )
        return instruments, matrix

    def slice_sessions(self, sessions: tuple[str, ...]) -> ColumnarResearchData:
        if not sessions or any(session not in self.sessions for session in sessions):
            raise ValueError("Columnar Research Sessions are outside the input slice")
        financial = (
            None
            if self._financial_values is None
            else _session_filter(self._financial_values, "session", sessions)
        )
        return ColumnarResearchData(
            sessions=sessions,
            _instruments=self._instruments,
            _eod_prices=_session_filter(self._eod_prices, "session_date", sessions),
            _universes=_session_filter(self._universes, "session", sessions),
            _trading_states=_session_filter(self._trading_states, "session", sessions),
            _price_limits=_session_filter(self._price_limits, "session", sessions),
            _industries=self._industries,
            _financial_values=financial,
            _field_columns=self._field_columns,
        )

    def append_sessions(self, later: ColumnarResearchSeries) -> ColumnarResearchData:
        if not isinstance(later, ColumnarResearchData):
            raise TypeError("Columnar Research append requires one storage backend")
        if (
            not self.sessions
            or not later.sessions
            or self.sessions[-1] >= later.sessions[0]
            or self._field_columns != later._field_columns
            or (self._financial_values is None) != (later._financial_values is None)
        ):
            raise ValueError("Columnar Research append boundary is invalid")
        financial = (
            None
            if self._financial_values is None or later._financial_values is None
            else pa.concat_tables([self._financial_values, later._financial_values])
        )
        return ColumnarResearchData(
            sessions=(*self.sessions, *later.sessions),
            _instruments=_merge_reference_rows(
                self._instruments,
                later._instruments,
                key_columns=("instrument_id",),
            ),
            _eod_prices=pa.concat_tables([self._eod_prices, later._eod_prices]),
            _universes=pa.concat_tables([self._universes, later._universes]),
            _trading_states=pa.concat_tables(
                [self._trading_states, later._trading_states]
            ),
            _price_limits=pa.concat_tables([self._price_limits, later._price_limits]),
            _industries=_merge_reference_rows(
                self._industries,
                later._industries,
                key_columns=("instrument_id", "active_from", "active_to", "sw2021_l1"),
            ),
            _financial_values=financial,
            _field_columns=self._field_columns,
        )


def _numeric_matrix(
    table: pa.Table,
    *,
    session_column: str,
    value_column: str,
    sessions: tuple[str, ...],
    instruments: tuple[str, ...],
    shape: tuple[int, int],
) -> np.ndarray:
    matrix = np.full(shape, np.nan, dtype=np.float64)
    if table.num_rows == 0:
        return matrix
    session_axis = np.asarray(sessions, dtype=np.str_)
    instrument_axis = np.asarray(instruments, dtype=np.str_)
    row_sessions = np.asarray(
        table[session_column].combine_chunks().to_numpy(zero_copy_only=False),
        dtype=np.str_,
    )
    row_instruments = np.asarray(
        table["instrument_id"].combine_chunks().to_numpy(zero_copy_only=False),
        dtype=np.str_,
    )
    session_indices = np.searchsorted(session_axis, row_sessions)
    instrument_indices = np.searchsorted(instrument_axis, row_instruments)
    if (
        np.any(session_indices >= len(session_axis))
        or np.any(instrument_indices >= len(instrument_axis))
        or np.any(session_axis[session_indices] != row_sessions)
        or np.any(instrument_axis[instrument_indices] != row_instruments)
    ):
        raise ValueError("Columnar Research coordinates are misaligned")
    values = pc.cast(table[value_column].combine_chunks(), pa.float64()).to_numpy(
        zero_copy_only=False
    )
    matrix[instrument_indices, session_indices] = values
    return matrix


def _merge_reference_rows(
    earlier: pa.Table,
    later: pa.Table,
    *,
    key_columns: tuple[str, ...],
) -> pa.Table:
    combined = _sorted_table(pa.concat_tables([earlier, later]), key_columns)
    if combined.num_rows < 2:
        return combined
    keys = list(
        zip(
            *(combined[column].combine_chunks().to_pylist() for column in key_columns),
            strict=True,
        )
    )
    positions = [0, *(index for index in range(1, len(keys)) if keys[index] != keys[index - 1])]
    return combined.take(pa.array(positions, type=pa.int64()))


def _object_matrix(
    table: pa.Table,
    *,
    session_column: str,
    value_column: str,
    sessions: tuple[str, ...],
    instruments: tuple[str, ...],
) -> np.ndarray:
    matrix = np.full((len(instruments), len(sessions)), None, dtype=object)
    session_axis = np.asarray(sessions, dtype=np.str_)
    instrument_axis = np.asarray(instruments, dtype=np.str_)
    row_sessions = np.asarray(
        table[session_column].combine_chunks().to_numpy(zero_copy_only=False),
        dtype=np.str_,
    )
    row_instruments = np.asarray(
        table["instrument_id"].combine_chunks().to_numpy(zero_copy_only=False),
        dtype=np.str_,
    )
    session_indices = np.searchsorted(session_axis, row_sessions)
    instrument_indices = np.searchsorted(instrument_axis, row_instruments)
    if (
        np.any(session_indices >= len(session_axis))
        or np.any(instrument_indices >= len(instrument_axis))
        or np.any(session_axis[session_indices] != row_sessions)
        or np.any(instrument_axis[instrument_indices] != row_instruments)
    ):
        raise ValueError("Columnar Research coordinates are misaligned")
    values = np.asarray(table[value_column].combine_chunks().to_pylist(), dtype=object)
    matrix[instrument_indices, session_indices] = values
    return matrix
