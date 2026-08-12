from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

AlphaValueType = Literal["numeric_series"]
type AlphaSeries = tuple[float | None, ...]
type AlphaSeriesReader = Callable[
    [Sequence[Mapping[str, object] | None]],
    AlphaSeries,
]


@dataclass(frozen=True)
class AlphaFieldCapability:
    identifier: str
    value_type: AlphaValueType = "numeric_series"


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    description: str
    unit: str
    physical_type: str
    availability: str
    grain: str
    missingness: str
    alpha: AlphaFieldCapability | None = None
    alpha_series_reader: AlphaSeriesReader | None = None


def _price_series(column: str) -> AlphaSeriesReader:
    def read(rows: Sequence[Mapping[str, object] | None]) -> AlphaSeries:
        return tuple(
            None if row is None or row.get(column) is None else float(row[column]) for row in rows
        )

    return read


FIELD_DEFINITIONS = (
    FieldDefinition(
        field_id="price.open.adjusted",
        description="causal cumulative-adjusted open",
        unit="CNY/share",
        physical_type="decimal",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_no_valid_session_bar",
        alpha=AlphaFieldCapability("open_adj"),
        alpha_series_reader=_price_series("open_adj"),
    ),
    FieldDefinition(
        field_id="price.high.adjusted",
        description="causal cumulative-adjusted high",
        unit="CNY/share",
        physical_type="decimal",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_no_valid_session_bar",
        alpha=AlphaFieldCapability("high_adj"),
        alpha_series_reader=_price_series("high_adj"),
    ),
    FieldDefinition(
        field_id="price.low.adjusted",
        description="causal cumulative-adjusted low",
        unit="CNY/share",
        physical_type="decimal",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_no_valid_session_bar",
        alpha=AlphaFieldCapability("low_adj"),
        alpha_series_reader=_price_series("low_adj"),
    ),
    FieldDefinition(
        field_id="price.close.adjusted",
        description="causal cumulative-adjusted close",
        unit="CNY/share",
        physical_type="decimal",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_no_valid_session_bar",
        alpha=AlphaFieldCapability("close_adj"),
        alpha_series_reader=_price_series("close_adj"),
    ),
    FieldDefinition(
        field_id="market.volume.shares",
        description="traded share volume",
        unit="shares",
        physical_type="int64",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_no_valid_session_bar",
        alpha=AlphaFieldCapability("volume_shares"),
        alpha_series_reader=_price_series("volume_shares"),
    ),
    FieldDefinition(
        field_id="market.turnover.cny",
        description="turnover amount",
        unit="CNY",
        physical_type="decimal",
        availability="after_close",
        grain="instrument_by_research_session",
        missingness="missing_when_no_valid_session_bar",
        alpha=AlphaFieldCapability("turnover_amount_cny"),
        alpha_series_reader=_price_series("turnover_cny"),
    ),
)


def field_definitions() -> tuple[FieldDefinition, ...]:
    return FIELD_DEFINITIONS


def alpha_field_catalog() -> tuple[FieldDefinition, ...]:
    return tuple(field for field in FIELD_DEFINITIONS if field.alpha is not None)


def alpha_identifier_by_field_id() -> dict[str, str]:
    return {
        field.field_id: field.alpha.identifier
        for field in alpha_field_catalog()
        if field.alpha is not None
    }


def read_alpha_field_series(
    field_id: str,
    rows: Sequence[Mapping[str, object] | None],
) -> AlphaSeries:
    field = next(
        (definition for definition in alpha_field_catalog() if definition.field_id == field_id),
        None,
    )
    if field is None or field.alpha_series_reader is None:
        raise KeyError(f"unknown Alpha field: {field_id}")
    return field.alpha_series_reader(rows)
