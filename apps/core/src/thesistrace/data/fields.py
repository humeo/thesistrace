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
    research_category: Literal["market", "financial"] = "market"
    display_name: str = ""
    research_purpose: str = ""
    source_unit: str = ""


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
        AlphaFieldCapability("open"),
        _row_series("open_adj"),
        display_name="复权开盘价",
        research_purpose="行情",
        source_endpoint="daily",
        source_column="open",
        source_unit="CNY/share",
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
        AlphaFieldCapability("high"),
        _row_series("high_adj"),
        display_name="复权最高价",
        research_purpose="行情",
        source_endpoint="daily",
        source_column="high",
        source_unit="CNY/share",
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
        AlphaFieldCapability("low"),
        _row_series("low_adj"),
        display_name="复权最低价",
        research_purpose="行情",
        source_endpoint="daily",
        source_column="low",
        source_unit="CNY/share",
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
        AlphaFieldCapability("close"),
        _row_series("close_adj"),
        display_name="复权收盘价",
        research_purpose="行情",
        source_endpoint="daily",
        source_column="close",
        source_unit="CNY/share",
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
        AlphaFieldCapability("volume"),
        _row_series("volume_shares"),
        display_name="成交股数",
        research_purpose="流动性",
        source_endpoint="daily",
        source_column="vol",
        source_unit="100 shares",
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
        AlphaFieldCapability("amount"),
        _row_series("turnover_cny"),
        display_name="成交金额",
        research_purpose="流动性",
        source_endpoint="daily",
        source_column="amount",
        source_unit="thousand CNY",
    ),
    FieldDefinition(
        "price.close.raw", "unadjusted close from the daily price source", "CNY/share", "decimal",
        "after_close", "instrument_by_research_session", "missing_when_no_valid_session_bar",
        "equity.eod_price", AlphaFieldCapability("close_raw"), _row_series("close_raw"),
        display_name="未复权收盘价", research_purpose="行情", source_endpoint="daily",
        source_column="close", source_unit="CNY/share", authoring_example="rank(close_raw)",
    ),
)


def _financial_field(
    field_id: str,
    identifier: str,
    description: str,
    *,
    display_name: str,
    research_purpose: str,
    endpoint: str,
    column: str,
    period_selection: str,
    company_types: tuple[str, ...] = ("1", "2", "3", "4"),
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
        alpha=AlphaFieldCapability(identifier),
        alpha_series_reader=_row_series(field_id),
        reporting_scope="report_type_1_consolidated",
        report_period_selection=period_selection,
        source_lineage=f"tushare.{endpoint}.{column}",
        applicable_company_types=company_types,
        authoring_example=f"rank({identifier})",
        source_endpoint=endpoint,
        source_column=column,
        research_category="financial",
        display_name=display_name,
        research_purpose=research_purpose,
        source_unit="CNY",
    )


FINANCIAL_FIELDS = (
    _financial_field(
        "financial.income.total_revenue.latest_fy",
        "revenue",
        "latest visible full-year consolidated total revenue",
        display_name="营业总收入",
        research_purpose="盈利",
        endpoint="income",
        column="total_revenue",
        period_selection="latest_visible_full_year",
    ),
    _financial_field(
        "financial.income.net_profit_parent.latest_fy",
        "net_profit",
        "latest visible full-year consolidated net profit attributable to parent owners",
        display_name="归母净利润",
        research_purpose="盈利",
        endpoint="income",
        column="n_income_attr_p",
        period_selection="latest_visible_full_year",
    ),
    _financial_field(
        "financial.cashflow.operating_cash_flow.latest_fy",
        "operating_cash_flow",
        "latest visible full-year consolidated net operating cash flow",
        display_name="经营现金流净额",
        research_purpose="现金流",
        endpoint="cashflow",
        column="n_cashflow_act",
        period_selection="latest_visible_full_year",
    ),
    _financial_field(
        "financial.balance_sheet.total_assets.latest_reported",
        "assets",
        "latest visible quarterly or annual consolidated total assets",
        display_name="资产总计",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="total_assets",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.total_liabilities.latest_reported",
        "liabilities",
        "latest visible quarterly or annual consolidated total liabilities",
        display_name="负债合计",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="total_liab",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.equity_parent.latest_reported",
        "equity",
        "latest visible quarterly or annual consolidated equity attributable to parent owners",
        display_name="归母权益",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="total_hldr_eqy_exc_min_int",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.monetary_funds.latest_reported",
        "monetary_funds",
        "最新可见报告期的期末存量；不自动等于无限制可用现金。",
        display_name="货币资金",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="money_cap",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.accounts_receivable.latest_reported",
        "accounts_receivable",
        "最新可见报告期的期末存量；不同于应收票据及应收账款合计。",
        display_name="应收账款",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="accounts_receiv",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.notes_receivable.latest_reported",
        "notes_receivable",
        "最新可见报告期的期末存量；不以应收融资等相近科目替代。",
        display_name="应收票据",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="notes_receiv",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.other_receivables.latest_reported",
        "other_receivables",
        "最新可见报告期的期末存量；不同于其他应收款合计列。",
        display_name="其他应收款",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="oth_receiv",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.prepayments.latest_reported",
        "prepayments",
        "最新可见报告期的期末存量；报告期余额，不是当期采购现金。",
        display_name="预付款项",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="prepayment",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.inventories.latest_reported",
        "inventories",
        "最新可见报告期的期末存量；行业适用性与源非空覆盖需分别核验。",
        display_name="存货",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="inventories",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.accounts_payable.latest_reported",
        "accounts_payable",
        "最新可见报告期的期末存量；不同于应付票据及应付账款合计。",
        display_name="应付账款",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="acct_payable",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.contract_assets.latest_reported",
        "contract_assets",
        "最新可见报告期的期末存量；不自动并入应收账款；科目出现前缺失不填零。",
        display_name="合同资产",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="contract_assets",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.contract_liabilities.latest_reported",
        "contract_liabilities",
        "最新可见报告期的收入合同负债；不是订单总额或必然实现的收入。不适用于保险公司，来源列可能表示保险合同负债。",
        display_name="合同负债",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="contract_liab",
        period_selection="latest_visible_quarterly_or_annual",
        company_types=("1", "2", "4"),
    ),
    _financial_field(
        "financial.balance_sheet.goodwill.latest_reported",
        "goodwill",
        "最新可见报告期的期末存量；余额不同于当期减值损失。",
        display_name="商誉",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="goodwill",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.short_term_borrowings.latest_reported",
        "short_term_borrowings",
        "最新可见报告期的期末存量；不是全部短期到期债务。",
        display_name="短期借款",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="st_borr",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.long_term_borrowings.latest_reported",
        "long_term_borrowings",
        "最新可见报告期的期末存量；不是全部非流动负债。",
        display_name="长期借款",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="lt_borr",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.bonds_payable.latest_reported",
        "bonds_payable",
        "最新可见报告期的期末存量；报告期余额，不含逐笔到期日。",
        display_name="应付债券",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="bond_payable",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.noncurrent_liabilities_due_1y.latest_reported",
        "noncurrent_liabilities_due_1y",
        "最新可见报告期的期末存量；不能全部当作有息借款。",
        display_name="一年内到期的非流动负债",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="non_cur_liab_due_1y",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.balance_sheet.other_equity_instruments.latest_reported",
        "other_equity_instruments",
        "最新可见报告期的期末存量；不同于其他权益工具投资，且不只包含优先股。",
        display_name="其他权益工具",
        research_purpose="资产负债",
        endpoint="balancesheet",
        column="oth_eqt_tools",
        period_selection="latest_visible_quarterly_or_annual",
    ),
    _financial_field(
        "financial.cashflow.cash_equivalents.latest_reported",
        "cash_equivalents",
        "最新可见报告期的期末存量；现金流量表中的期末存量，仍选最新季报或年报。",
        display_name="期末现金及现金等价物",
        research_purpose="资产负债",
        endpoint="cashflow",
        column="c_cash_equ_end_period",
        period_selection="latest_visible_quarterly_or_annual",
    ),
)



def _daily_basic_field(
    identifier: str, field_id: str, display_name: str, unit: str,
    source_unit: str, research_purpose: str, description: str,
) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id, description=description, unit=unit, physical_type="decimal",
        availability="after_close", grain="instrument_by_research_session",
        missingness="missing_when_no_exact_session_source_value", family_id="equity.daily_basic",
        alpha=AlphaFieldCapability(identifier), alpha_series_reader=_row_series(identifier),
        source_lineage=f"tushare.daily_basic.{identifier}", source_endpoint="daily_basic",
        source_column=identifier, display_name=display_name, research_purpose=research_purpose,
        source_unit=source_unit, authoring_example=f"rank({identifier})",
    )


DAILY_BASIC_FIELDS = (
    _daily_basic_field(
        'total_mv', 'market.capitalization.total', '总市值',
        'CNY', '10000 CNY', '估值',
        'total market capitalization',
    ),
    _daily_basic_field(
        'circ_mv', 'market.capitalization.float', '流通市值',
        'CNY', '10000 CNY', '估值',
        'circulating market capitalization',
    ),
    _daily_basic_field(
        'total_share', 'market.shares.total', '总股本',
        'shares', '10000 shares', '股本',
        'total outstanding shares',
    ),
    _daily_basic_field(
        'float_share', 'market.shares.float', '流通股本',
        'shares', '10000 shares', '股本',
        'unrestricted circulating shares',
    ),
    _daily_basic_field(
        'free_share', 'market.shares.free_float', '自由流通股本',
        'shares', '10000 shares', '股本',
        'free float shares under supplier definition',
    ),
    _daily_basic_field(
        'turnover_rate', 'market.turnover.float_ratio', '换手率',
        'ratio', 'percent', '流动性',
        'traded shares divided by unrestricted circulating shares',
    ),
    _daily_basic_field(
        'turnover_rate_f', 'market.turnover.free_float_ratio', '自由流通换手率',
        'ratio', 'percent', '流动性',
        'traded shares divided by free float shares',
    ),
    _daily_basic_field(
        'volume_ratio', 'market.volume.ratio', '量比',
        'multiple', 'multiple', '流动性',
        'supplier volume ratio against its moving average',
    ),
    _daily_basic_field(
        'pe', 'market.valuation.pe', '市盈率',
        'multiple', 'multiple', '估值',
        'market capitalization divided by supplier annual net profit; losses yield missing',
    ),
    _daily_basic_field(
        'pe_ttm', 'market.valuation.pe_ttm', '滚动市盈率',
        'multiple', 'multiple', '估值',
        'market capitalization divided by supplier TTM net profit; losses yield missing',
    ),
    _daily_basic_field(
        'pb', 'market.valuation.pb', '市净率',
        'multiple', 'multiple', '估值',
        'market capitalization divided by net assets excluding other equity instruments',
    ),
    _daily_basic_field(
        'ps', 'market.valuation.ps', '市销率',
        'multiple', 'multiple', '估值',
        'market capitalization divided by latest annual operating revenue',
    ),
    _daily_basic_field(
        'ps_ttm', 'market.valuation.ps_ttm', '滚动市销率',
        'multiple', 'multiple', '估值',
        'market capitalization divided by TTM operating revenue',
    ),
    _daily_basic_field(
        'dv_ratio', 'market.dividend.yield_annual', '股息率',
        'ratio', 'percent', '股息',
        'supplier yield from cash dividends with ex-dates in previous calendar year',
    ),
    _daily_basic_field(
        'dv_ttm', 'market.dividend.yield_ttm', '滚动股息率',
        'ratio', 'percent', '股息',
        'supplier trailing dividend yield with ex-date and report-period restrictions',
    ),
)

FIELD_DEFINITIONS = (*MARKET_FIELDS, *DAILY_BASIC_FIELDS, *FINANCIAL_FIELDS)


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
