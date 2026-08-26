"""Arrow-backed Research Series views over one bounded calculation slice."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import TypeVar

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from thesistrace.research_series import (
    ExecutionPrice,
    InstrumentProfile,
    PriceLimit,
)

T = TypeVar("T")


def _session_filter(table: pa.Table, column: str, sessions: tuple[str, ...]) -> pa.Table:
    return table.filter(pc.is_in(table[column], value_set=pa.array(sessions)))


class _CoordinateValues(Mapping[tuple[str, str], T]):
    def __init__(
        self,
        index: _CoordinateIndex,
        *,
        value_columns: tuple[str, ...],
        convert,
    ) -> None:
        self._index = index
        self._columns = tuple(index.table[name].combine_chunks() for name in value_columns)
        self._convert = convert
        self._cache: dict[tuple[str, str], T] = {}

    def __getitem__(self, coordinate: tuple[str, str]) -> T:
        cached = self._cache.get(coordinate)
        if cached is not None:
            return cached
        position = self._index.position(coordinate)
        values = tuple(column[position].as_py() for column in self._columns)
        if any(value is None for value in values):
            raise KeyError(coordinate)
        result = self._convert(*values)
        self._cache[coordinate] = result
        return result

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return self._index.coordinates()

    def __len__(self) -> int:
        return len(self._index.row_keys)


class _CoordinateIndex:
    def __init__(
        self,
        table: pa.Table,
        *,
        session_column: str,
        sessions: tuple[str, ...],
        instruments: tuple[str, ...],
    ) -> None:
        self.table = table.combine_chunks()
        self.sessions = sessions
        self.instruments = instruments
        self._session_positions = {value: index for index, value in enumerate(sessions)}
        self._instrument_positions = {
            value: index for index, value in enumerate(instruments)
        }
        row_sessions = np.asarray(
            self.table[session_column].combine_chunks().to_numpy(zero_copy_only=False),
            dtype=np.str_,
        )
        row_instruments = np.asarray(
            self.table["instrument_id"].combine_chunks().to_numpy(zero_copy_only=False),
            dtype=np.str_,
        )
        session_axis = np.asarray(sessions, dtype=np.str_)
        instrument_axis = np.asarray(instruments, dtype=np.str_)
        self.row_session_indices = np.searchsorted(session_axis, row_sessions).astype(
            np.int32,
            copy=False,
        )
        self.row_instrument_indices = np.searchsorted(
            instrument_axis,
            row_instruments,
        ).astype(np.int32, copy=False)
        if (
            np.any(self.row_session_indices >= len(session_axis))
            or np.any(self.row_instrument_indices >= len(instrument_axis))
            or np.any(session_axis[self.row_session_indices] != row_sessions)
            or np.any(instrument_axis[self.row_instrument_indices] != row_instruments)
        ):
            raise ValueError("Columnar Research coordinates are misaligned")
        self.row_keys = (
            self.row_session_indices.astype(np.int64) * len(instruments)
            + self.row_instrument_indices
        )
        if len(self.row_keys) > 1 and np.any(self.row_keys[1:] <= self.row_keys[:-1]):
            raise ValueError("Columnar Research coordinates are not unique and ordered")

    def position(self, coordinate: tuple[str, str]) -> int:
        session, instrument_id = coordinate
        try:
            key = (
                self._session_positions[session] * len(self.instruments)
                + self._instrument_positions[instrument_id]
            )
        except KeyError as error:
            raise KeyError(coordinate) from error
        position = int(np.searchsorted(self.row_keys, key))
        if position == len(self.row_keys) or self.row_keys[position] != key:
            raise KeyError(coordinate)
        return position

    def coordinates(self) -> Iterator[tuple[str, str]]:
        return (
            (self.sessions[int(session_index)], self.instruments[int(instrument_index)])
            for session_index, instrument_index in zip(
                self.row_session_indices,
                self.row_instrument_indices,
                strict=True,
            )
        )


class _InstrumentProfiles(Mapping[str, InstrumentProfile]):
    def __init__(self, table: pa.Table, ids: tuple[str, ...]) -> None:
        self._table = table.combine_chunks()
        self._ids = ids
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
    def __init__(self, table: pa.Table, eod_index: _CoordinateIndex) -> None:
        self._table = table.combine_chunks()
        self._sessions = tuple(map(str, self._table["session"].combine_chunks().to_pylist()))
        eod_prices = eod_index.table
        eligible_mask = pc.and_kleene(
            pc.and_kleene(
                pc.is_valid(eod_prices["open_raw"]),
                pc.is_valid(eod_prices["open_adj"]),
            ),
            pc.and_kleene(
                pc.is_valid(eod_prices["turnover_amount_cny"]),
                pc.greater(eod_prices["turnover_amount_cny"], 0),
            ),
        ).to_numpy(zero_copy_only=False)
        self._eligible_by_session: dict[str, frozenset[str]] = {}
        for session_index in np.unique(eod_index.row_session_indices[eligible_mask]):
            instrument_positions = np.unique(
                eod_index.row_instrument_indices[
                    eligible_mask & (eod_index.row_session_indices == session_index)
                ]
            )
            self._eligible_by_session[eod_index.sessions[int(session_index)]] = frozenset(
                eod_index.instruments[int(position)] for position in instrument_positions
            )
        self._cache: dict[str, tuple[str, ...]] = {}

    def __getitem__(self, session: str) -> tuple[str, ...]:
        cached = self._cache.get(session)
        if cached is not None:
            return cached
        position = bisect_left(self._sessions, session)
        if position == len(self._sessions) or self._sessions[position] != session:
            raise KeyError(session)
        values = self._table["instrument_ids"][position].as_py()
        eligible = self._eligible_by_session.get(session, frozenset())
        result = tuple(str(value) for value in values if str(value) in eligible)
        self._cache[session] = result
        return result

    def __iter__(self) -> Iterator[str]:
        return (str(value) for value in self._sessions)

    def __len__(self) -> int:
        return len(self._sessions)


class _IndustryMembership(Mapping[tuple[str, str], str]):
    def __init__(self, table: pa.Table) -> None:
        ordered = table.combine_chunks()
        self._row_count = ordered.num_rows
        memberships: dict[str, list[tuple[str, str, str]]] = {}
        for instrument_id, active_from, active_to, industry in zip(
            ordered["instrument_id"].to_pylist(),
            ordered["active_from"].to_pylist(),
            ordered["active_to"].to_pylist(),
            ordered["sw2021_l1"].to_pylist(),
            strict=True,
        ):
            memberships.setdefault(str(instrument_id), []).append(
                (str(active_from), str(active_to or ""), str(industry))
            )
        self._memberships = {
            instrument_id: tuple(values) for instrument_id, values in memberships.items()
        }

    def __getitem__(self, coordinate: tuple[str, str]) -> str:
        session, instrument_id = coordinate
        visible: str | None = None
        for active_from, active_to, industry in self._memberships.get(instrument_id, ()):
            if active_from <= session and (not active_to or session < active_to):
                visible = industry
        if visible is None:
            raise KeyError(coordinate)
        return visible

    def __iter__(self) -> Iterator[tuple[str, str]]:
        raise TypeError("Industry membership is a point-in-time lookup")

    def __len__(self) -> int:
        return self._row_count


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
    def _instrument_axis(self) -> tuple[str, ...]:
        return tuple(
            map(str, self._instruments["instrument_id"].combine_chunks().to_pylist())
        )

    @cached_property
    def _eod_index(self) -> _CoordinateIndex:
        return _CoordinateIndex(
            self._eod_prices,
            session_column="session_date",
            sessions=self.sessions,
            instruments=self._instrument_axis,
        )

    @cached_property
    def _trading_state_index(self) -> _CoordinateIndex:
        return _CoordinateIndex(
            self._trading_states,
            session_column="session",
            sessions=self.sessions,
            instruments=self._instrument_axis,
        )

    @cached_property
    def _price_limit_index(self) -> _CoordinateIndex:
        return _CoordinateIndex(
            self._price_limits,
            session_column="session",
            sessions=self.sessions,
            instruments=self._instrument_axis,
        )

    @cached_property
    def _financial_index(self) -> _CoordinateIndex | None:
        if self._financial_values is None:
            return None
        return _CoordinateIndex(
            self._financial_values,
            session_column="session",
            sessions=self.sessions,
            instruments=self._instrument_axis,
        )

    @cached_property
    def instruments(self) -> Mapping[str, InstrumentProfile]:
        return _InstrumentProfiles(self._instruments, self._instrument_axis)

    @cached_property
    def universe_members(self) -> Mapping[str, tuple[str, ...]]:
        return _UniverseMembers(self._universes, self._eod_index)

    @cached_property
    def fields(self) -> Mapping[str, Mapping[tuple[str, str], object]]:
        market = {
            field_id: _CoordinateValues(
                self._eod_index,
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
                        self._financial_index,
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
            self._eod_index,
            value_columns=("open_raw", "open_adj"),
            convert=lambda raw, adjusted: ExecutionPrice(str(raw), str(adjusted)),
        )

    @cached_property
    def trading_states(self) -> Mapping[tuple[str, str], str]:
        return _CoordinateValues(
            self._trading_state_index,
            value_columns=("state",),
            convert=str,
        )

    @cached_property
    def price_limits(self) -> Mapping[tuple[str, str], PriceLimit]:
        return _CoordinateValues(
            self._price_limit_index,
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
                    self._financial_index,
                    value_column=field_id,
                    instruments=instruments,
                    shape=shape,
                )
                continue
            matrices[field_id] = _numeric_matrix(
                self._eod_index,
                value_column=self._field_columns[field_id],
                instruments=instruments,
                shape=shape,
            )
        return matrices

    def adjusted_open_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        axis = self._adjusted_open_axis
        matrix = self._adjusted_open_numeric_matrix
        if instruments != axis:
            positions = [axis.index(instrument_id) for instrument_id in instruments]
            return matrix[positions]
        return matrix

    def adjusted_open_decimal_matrix(self, instruments: tuple[str, ...]) -> np.ndarray:
        axis = self._adjusted_open_axis
        matrix = self._adjusted_open_decimal_matrix
        if instruments != axis:
            positions = [axis.index(instrument_id) for instrument_id in instruments]
            return matrix[positions]
        return matrix

    @cached_property
    def _adjusted_open_axis(self) -> tuple[str, ...]:
        return tuple(sorted(self.instruments))

    @cached_property
    def _adjusted_open_numeric_matrix(self) -> np.ndarray:
        return _numeric_matrix(
            self._eod_index,
            value_column="open_adj",
            instruments=self._adjusted_open_axis,
            shape=(len(self._adjusted_open_axis), len(self.sessions)),
        )

    @cached_property
    def _adjusted_open_decimal_matrix(self) -> np.ndarray:
        return _decimal_matrix(
            self._eod_index,
            value_column="open_adj",
            instruments=self._adjusted_open_axis,
        )

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


def _numeric_matrix(
    index: _CoordinateIndex,
    *,
    value_column: str,
    instruments: tuple[str, ...],
    shape: tuple[int, int],
) -> np.ndarray:
    matrix = np.full(shape, np.nan, dtype=np.float64)
    if index.table.num_rows == 0:
        return matrix
    translated_positions, included = _translated_instrument_positions(index, instruments)
    values_column = index.table[value_column].combine_chunks()
    if pa.types.is_decimal(values_column.type):
        values = _decimal_binary64_values(values_column)
    else:
        values = pc.cast(values_column, pa.float64()).to_numpy(zero_copy_only=False)
    matrix[
        translated_positions[included],
        index.row_session_indices[included],
    ] = values[included]
    return matrix


def _decimal_binary64_values(values: pa.Array) -> np.ndarray:
    # ADR-0083 forbids Arrow's direct decimal-to-float cast because it can
    # select the adjacent binary64 value. Arrow renders the exact decimal
    # strings, then Python's string-to-float operation supplies the same
    # correctly rounded result as float(Decimal) without materializing Python
    # Decimal objects for every Canonical value.
    strings = pc.cast(values, pa.string()).to_numpy(zero_copy_only=False)
    return np.fromiter(
        (np.nan if value is None else float(value) for value in strings),
        dtype=np.float64,
        count=len(strings),
    )


def _decimal_matrix(
    index: _CoordinateIndex,
    *,
    value_column: str,
    instruments: tuple[str, ...],
) -> np.ndarray:
    shape = (len(instruments), len(index.sessions))
    decimal_matrix = np.full(shape, None, dtype=object)
    translated_positions, included = _translated_instrument_positions(index, instruments)
    decimal_values = np.asarray(
        index.table[value_column].combine_chunks().to_pylist(), dtype=object
    )
    coordinates = (
        translated_positions[included],
        index.row_session_indices[included],
    )
    decimal_matrix[coordinates] = decimal_values[included]
    return decimal_matrix


def _translated_instrument_positions(
    index: _CoordinateIndex,
    instruments: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray]:
    if instruments == index.instruments:
        return index.row_instrument_indices, np.ones(
            len(index.row_instrument_indices), dtype=np.bool_
        )
    requested_positions = {
        instrument_id: position for position, instrument_id in enumerate(instruments)
    }
    translated = np.fromiter(
        (
            requested_positions.get(index.instruments[int(position)], -1)
            for position in index.row_instrument_indices
        ),
        dtype=np.int32,
        count=len(index.row_instrument_indices),
    )
    return translated, translated >= 0
