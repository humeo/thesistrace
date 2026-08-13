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
    family_id: str
    alpha: AlphaFieldCapability | None = None
    alpha_series_reader: AlphaSeriesReader | None = None
    reporting_scope: str = "market-observation"
    report_period_selection: str = "research-session"
    source_lineage: str = "tushare.daily"
    applicable_company_types: tuple[str, ...] = ()
    authoring_example: str = ""
    source_endpoint: str = ""
    source_column: str = ""


def _row_series(column: str) -> AlphaSeriesReader:
    def read(rows: Sequence[Mapping[str, object] | None]) -> AlphaSeries:
        return tuple(
            None if row is None or row.get(column) is None else float(row[column])
            for row in rows
        )

    return read


MARKET_FIELDS = (
    FieldDefinition(
        "price.open.adjusted",
        "causal cumulative-adjusted open",
        "CNY/share",
        "decimal",
        "after_close",
        "instrument_by_research_session",
        "missing_when_no_valid_session_bar",
        "equity.eod_price",
        AlphaFieldCapability("open_adj"),
        _row_series("open_adj"),
    ),
    FieldDefinition(
        "price.high.adjusted",
        "causal cumulative-adjusted high",
        "CNY/share",
        "decimal",
        "after_close",
        "instrument_by_research_session",
        "missing_when_no_valid_session_bar",
        "equity.eod_price",
        AlphaFieldCapability("high_adj"),
        _row_series("high_adj"),
    ),
    FieldDefinition(
        "price.low.adjusted",
        "causal cumulative-adjusted low",
        "CNY/share",
        "decimal",
        "after_close",
        "instrument_by_research_session",
        "missing_when_no_valid_session_bar",
        "equity.eod_price",
        AlphaFieldCapability("low_adj"),
        _row_series("low_adj"),
    ),
    FieldDefinition(
        "price.close.adjusted",
        "causal cumulative-adjusted close",
        "CNY/share",
        "decimal",
        "after_close",
        "instrument_by_research_session",
        "missing_when_no_valid_session_bar",
        "equity.eod_price",
        AlphaFieldCapability("close_adj"),
        _row_series("close_adj"),
    ),
    FieldDefinition(
        "market.volume.shares",
        "traded share volume",
        "shares",
        "int64",
        "after_close",
        "instrument_by_research_session",
        "missing_when_no_valid_session_bar",
        "equity.eod_price",
        AlphaFieldCapability("volume_shares"),
        _row_series("volume_shares"),
    ),
    FieldDefinition(
        "market.turnover.cny",
        "turnover amount",
        "CNY",
        "decimal",
        "after_close",
        "instrument_by_research_session",
        "missing_when_no_valid_session_bar",
        "equity.eod_price",
        AlphaFieldCapability("turnover_amount_cny"),
        _row_series("turnover_cny"),
    ),
)


def _financial_field(
    field_id: str,
    description: str,
    *,
    endpoint: str,
    column: str,
    period_selection: str,
) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id,
        description=description,
        unit="CNY",
        physical_type="decimal",
        availability="next_research_session_after_source_publication",
        grain="instrument_by_research_session",
        missingness="missing_when_no_visible_eligible_fact",
        family_id="equity.financial_pit",
        alpha=AlphaFieldCapability(field_id),
        alpha_series_reader=_row_series(field_id),
        reporting_scope="report_type_1_consolidated",
        report_period_selection=period_selection,
        source_lineage=f"tushare.{endpoint}.{column}",
        applicable_company_types=("1", "2", "3", "4"),
        authoring_example=f"cs_rank({field_id})",
        source_endpoint=endpoint,
        source_column=column,
    )


FINANCIAL_FIELDS = (
    _financial_field(
        "total_revenue_latest_fy",
        "latest visible full-year consolidated total revenue",
        endpoint="income",
        column="total_revenue",
        period_selection="latest_visible_full_year",
    ),
    _financial_field(
        "net_profit_parent_latest_fy",
        "latest visible full-year consolidated net profit attributable to parent owners",
        endpoint="income",
        column="n_income_attr_p",
        period_selection="latest_visible_full_year",
    ),
    _financial_field(
        "operating_cash_flow_latest_fy",
        "latest visible full-year consolidated net operating cash flow",
        endpoint="cashflow",
        column="n_cashflow_act",
        period_selection="latest_visible_full_year",
    ),
    _financial_field(
        "total_assets_latest_reported",
        "latest visible quarterly or annual consolidated total assets",
        endpoint="balancesheet",
        column="total_assets",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "total_liabilities_latest_reported",
        "latest visible quarterly or annual consolidated total liabilities",
        endpoint="balancesheet",
        column="total_liab",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "equity_parent_latest_reported",
        "latest visible quarterly or annual consolidated equity attributable to parent owners",
        endpoint="balancesheet",
        column="total_hldr_eqy_exc_min_int",
        period_selection="latest_visible_quarterly_or_annual",
    ),
)

FIELD_DEFINITIONS = (*MARKET_FIELDS, *FINANCIAL_FIELDS)


def field_definitions() -> tuple[FieldDefinition, ...]:
    return FIELD_DEFINITIONS


def alpha_field_catalog() -> tuple[FieldDefinition, ...]:
    return tuple(field for field in FIELD_DEFINITIONS if field.alpha is not None)


def authorable_fields() -> tuple[FieldDefinition, ...]:
    return alpha_field_catalog()


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
