from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypeVar, runtime_checkable

import numpy as np

type Coordinate = tuple[str, str]
type NumericValue = Decimal | int | float | str
SeriesValue = TypeVar("SeriesValue")


@dataclass(frozen=True)
class InstrumentProfile:
    board: str
    listed_to: str


@dataclass(frozen=True)
class ExecutionPrice:
    raw_open: str
    adjusted_open: str


@dataclass(frozen=True)
class PriceLimit:
    upper: str
    lower: str


@dataclass(frozen=True)
class AlignedResearchData:
    """Storage-independent Series resolved by Data for one calculation slice."""

    sessions: tuple[str, ...]
    instruments: dict[str, InstrumentProfile]
    fields: dict[str, dict[Coordinate, NumericValue]]
    universe_members: dict[str, tuple[str, ...]]
    industries: dict[Coordinate, str]
    execution_prices: dict[Coordinate, ExecutionPrice]
    trading_states: dict[Coordinate, str]
    price_limits: dict[Coordinate, PriceLimit]

    def snapshot(self) -> AlignedResearchData:
        return deepcopy(self)


@runtime_checkable
class ColumnarResearchSeries(Protocol):
    sessions: tuple[str, ...]
    instruments: Mapping[str, InstrumentProfile]
    universe_members: Mapping[str, tuple[str, ...]]
    industries: Mapping[Coordinate, str]
    execution_prices: Mapping[Coordinate, ExecutionPrice]
    trading_states: Mapping[Coordinate, str]
    price_limits: Mapping[Coordinate, PriceLimit]

    def snapshot(self) -> ColumnarResearchSeries: ...

    def slice_sessions(self, sessions: tuple[str, ...]) -> ColumnarResearchSeries: ...

    def append_sessions(self, later: ColumnarResearchSeries) -> ColumnarResearchSeries: ...

    def numeric_field_matrices(
        self,
        field_ids: tuple[str, ...],
        instruments: tuple[str, ...],
    ) -> Mapping[str, np.ndarray]: ...

    def adjusted_open_matrix(self, instruments: tuple[str, ...]) -> np.ndarray: ...

    def adjusted_open_decimal_matrix(self, instruments: tuple[str, ...]) -> np.ndarray: ...


def research_sessions(data: AlignedResearchData) -> list[str]:
    return list(data.sessions)


def slice_research_sessions(
    data: AlignedResearchData,
    sessions: list[str] | tuple[str, ...],
) -> AlignedResearchData:
    selected_sessions = tuple(str(session) for session in sessions)
    if not selected_sessions or selected_sessions != tuple(sorted(set(selected_sessions))):
        raise ValueError("Aligned Research Sessions are invalid")
    if any(session not in data.sessions for session in selected_sessions):
        raise ValueError("Aligned Research Sessions are outside the input slice")
    selected = set(selected_sessions)

    def selected_coordinates(
        values: dict[Coordinate, SeriesValue],
    ) -> dict[Coordinate, SeriesValue]:
        return {
            coordinate: value for coordinate, value in values.items() if coordinate[0] in selected
        }

    return AlignedResearchData(
        sessions=selected_sessions,
        instruments=deepcopy(data.instruments),
        fields={
            field_id: {
                coordinate: value
                for coordinate, value in values.items()
                if coordinate[0] in selected
            }
            for field_id, values in data.fields.items()
        },
        universe_members={
            session: tuple(data.universe_members[session]) for session in selected_sessions
        },
        industries={
            coordinate: value for coordinate, value in selected_coordinates(data.industries).items()
        },
        execution_prices=selected_coordinates(data.execution_prices),
        trading_states={
            coordinate: str(value)
            for coordinate, value in selected_coordinates(data.trading_states).items()
        },
        price_limits=selected_coordinates(data.price_limits),
    )


def research_data_identity(data: AlignedResearchData) -> dict[str, object]:
    """Return a deterministic storage-independent identity projection."""
    return {
        "sessions": list(data.sessions),
        "instruments": {
            instrument_id: {"board": value.board, "listed_to": value.listed_to}
            for instrument_id, value in sorted(data.instruments.items())
        },
        "fields": {
            field_id: [
                [session, instrument_id, str(value)]
                for (session, instrument_id), value in sorted(values.items())
            ]
            for field_id, values in sorted(data.fields.items())
        },
        "universe_members": {
            session: list(values) for session, values in sorted(data.universe_members.items())
        },
        "industries": [
            [session, instrument_id, value]
            for (session, instrument_id), value in sorted(data.industries.items())
        ],
        "execution_prices": [
            [session, instrument_id, value.raw_open, value.adjusted_open]
            for (session, instrument_id), value in sorted(data.execution_prices.items())
        ],
        "trading_states": [
            [session, instrument_id, value]
            for (session, instrument_id), value in sorted(data.trading_states.items())
        ],
        "price_limits": [
            [session, instrument_id, value.upper, value.lower]
            for (session, instrument_id), value in sorted(data.price_limits.items())
        ],
    }
