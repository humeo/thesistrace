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
    _financial_field(
        'financial.cashflow.cash_paid_capex.ttm',
        'cash_paid_capex_ttm',
        '截至最新可见报告期的最近十二个月流量；'
        '含固定、无形及其他长期资产；'
        '经营现金流减它不直接称 FCFF/FCFE。',
        display_name='购建长期资产付现',
        research_purpose='现金流',
        endpoint='cashflow',
        column='c_pay_acq_const_fiolta',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_received_sales.ttm',
        'cash_received_sales_ttm',
        '截至最新可见报告期的最近十二个月流量；是收现总额，不是经营现金净流量。',
        display_name='销售商品及劳务收现',
        research_purpose='现金流',
        endpoint='cashflow',
        column='c_fr_sale_sg',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_paid_goods.ttm',
        'cash_paid_goods_ttm',
        '截至最新可见报告期的最近十二个月流量；不同于营业成本。',
        display_name='购买商品及劳务付现',
        research_purpose='现金流',
        endpoint='cashflow',
        column='c_paid_goods_s',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_received_asset_disposals.ttm',
        'cash_received_asset_disposals_ttm',
        '截至最新可见报告期的最近十二个月流量；是现金净额，不是处置利润。',
        display_name='处置长期资产收现净额',
        research_purpose='现金流',
        endpoint='cashflow',
        column='n_recp_disp_fiolta',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_paid_acquisitions.ttm',
        'cash_paid_acquisitions_ttm',
        '截至最新可见报告期的最近十二个月流量；'
        '源列含义为取得子公司及其他营业单位的现金净支出。',
        display_name='取得子公司等付现净额',
        research_purpose='现金流',
        endpoint='cashflow',
        column='n_disp_subs_oth_biz',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_paid_investments.ttm',
        'cash_paid_investments_ttm',
        '截至最新可见报告期的最近十二个月流量；不同于全部投资现金流出。',
        display_name='投资付现',
        research_purpose='现金流',
        endpoint='cashflow',
        column='c_paid_invest',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_received_borrowing.ttm',
        'cash_received_borrowing_ttm',
        '截至最新可见报告期的最近十二个月流量；不包含全部融资来源。',
        display_name='借款收现',
        research_purpose='现金流',
        endpoint='cashflow',
        column='c_recp_borrow',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.cash_paid_debt_repayment.ttm',
        'cash_paid_debt_repayment_ttm',
        '截至最新可见报告期的最近十二个月流量；不按 prepay 拼写解释为提前还款。',
        display_name='偿债付现',
        research_purpose='现金流',
        endpoint='cashflow',
        column='c_prepay_amt_borr',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.operating_revenue.ttm',
        'operating_revenue_ttm',
        '截至最新可见报告期的最近十二个月流量；与现有 revenue 的营业总收入分开。',
        display_name='营业收入',
        research_purpose='盈利',
        endpoint='income',
        column='revenue',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.consolidated_net_profit.ttm',
        'consolidated_net_profit_ttm',
        '截至最新可见报告期的最近十二个月流量；'
        '包含少数股东损益，与现有 net_profit 的归母口径分开。',
        display_name='合并净利润',
        research_purpose='盈利',
        endpoint='income',
        column='n_income',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.operating_cost.ttm',
        'operating_cost_ttm',
        '截至最新可见报告期的最近十二个月流量；不同于营业总成本。',
        display_name='营业成本',
        research_purpose='盈利',
        endpoint='income',
        column='oper_cost',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.rd_expense.ttm',
        'rd_expense_ttm',
        '截至最新可见报告期的最近十二个月流量；与 fina_indicator.rd_exp 的研发投入合计分开。',
        display_name='研发费用',
        research_purpose='盈利',
        endpoint='income',
        column='rd_exp',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.investment_income.ttm',
        'investment_income_ttm',
        '截至最新可见报告期的最近十二个月流量；不自动认定为非经常性损益。',
        display_name='投资净收益',
        research_purpose='盈利',
        endpoint='income',
        column='invest_income',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.fair_value_gain.ttm',
        'fair_value_gain_ttm',
        '截至最新可见报告期的最近十二个月流量；是损益组成项，不是现金流。',
        display_name='公允价值变动净收益',
        research_purpose='盈利',
        endpoint='income',
        column='fv_value_chg_gain',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.nonoperating_income.ttm',
        'nonoperating_income_ttm',
        '截至最新可见报告期的最近十二个月流量；不能全部等同于扣非事项。',
        display_name='营业外收入',
        research_purpose='盈利',
        endpoint='income',
        column='non_oper_income',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.nonoperating_expense.ttm',
        'nonoperating_expense_ttm',
        '截至最新可见报告期的最近十二个月流量；与净营业外收支及扣非计算分开。',
        display_name='营业外支出',
        research_purpose='盈利',
        endpoint='income',
        column='non_oper_exp',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.total_revenue.ttm',
        'revenue_ttm',
        '匹配可见报告重构 TTM；'
        '与 revenue 使用同一收入范围，期间改为最近十二个月；'
        '不同于 operating_revenue_ttm 的营业收入。',
        display_name='营业总收入 TTM',
        research_purpose='盈利',
        endpoint='income',
        column='total_revenue',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.income.net_profit_parent.ttm',
        'net_profit_ttm',
        '匹配可见报告重构 TTM；归母口径；与 consolidated_net_profit_ttm 的合并净利润分开。',
        display_name='归母净利润 TTM',
        research_purpose='盈利',
        endpoint='income',
        column='n_income_attr_p',
        period_selection='latest_visible_ttm',
    ),
    _financial_field(
        'financial.cashflow.operating_cash_flow.ttm',
        'operating_cash_flow_ttm',
        '匹配可见报告重构 TTM；'
        '与 operating_cash_flow 使用同一合并现金流口径，期间为最近十二个月。',
        display_name='经营现金流净额 TTM',
        research_purpose='现金流',
        endpoint='cashflow',
        column='n_cashflow_act',
        period_selection='latest_visible_ttm',
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

def _indicator_field(
    identifier: str, display_name: str, purpose: str, unit: str, source_unit: str,
    period: str, description: str, *, source_column: str | None = None,
) -> FieldDefinition:
    source_column = identifier if source_column is None else source_column
    return FieldDefinition(
        field_id=f"financial.indicator.{identifier}", description=description,
        unit=unit, physical_type="decimal",
        availability="announcement_aligned_with_observed_revisions",
        grain="instrument_by_research_session",
        missingness="missing_when_latest_report_value_absent_or_conflicting",
        family_id="equity.financial_indicator", alpha=AlphaFieldCapability(identifier),
        alpha_series_reader=_row_series(f"financial.indicator.{identifier}"),
        reporting_scope="supplier_defined", report_period_selection=period,
        source_lineage=f"tushare.fina_indicator.{source_column}",
        authoring_example=f"rank({identifier})", source_endpoint="fina_indicator",
        source_column=source_column, research_category="financial", display_name=display_name,
        research_purpose=purpose, source_unit=source_unit,
    )


FINANCIAL_INDICATOR_FIELDS = (
    _indicator_field("eps", "基本每股收益", "每股指标", "CNY/share", "CNY/share",
                     "latest_visible_report_cumulative", "supplier basic earnings per share"),
    _indicator_field("bps", "每股净资产", "每股指标", "CNY/share", "CNY/share",
                     "latest_visible_report_end", "supplier book value per share"),
    _indicator_field("current_ratio", "流动比率", "财务结构与偿债", "multiple", "multiple",
                     "latest_visible_report_end", "current assets divided by current liabilities"),
    _indicator_field("roe", "净资产收益率", "盈利能力", "ratio", "percent",
                     "latest_visible_supplier_report", "supplier return on equity; not annualized"),
    _indicator_field("q_roe", "单季净资产收益率", "单季度指标", "ratio", "percent",
                     "latest_visible_single_quarter", "supplier single-quarter return on equity"),
    _indicator_field("netprofit_yoy", "归母净利润同比增长率", "同比增长", "ratio", "percent",
                     "latest_visible_report_yoy", "parent-attributable net profit YoY growth"),
    _indicator_field(
        "gross_profit", "毛利", "盈利能力", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier cumulative operating revenue less operating cost; amount, not margin ratio",
        source_column="gross_margin",
    ),
    _indicator_field(
        "impai_ttm", "累计资产减值损失占营业总收入", "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier cumulative impairment loss / total revenue; source name does not mean TTM",
    ),
    _indicator_field(
        "q_impair_to_gr_ttm", "单季资产减值损失占营业总收入", "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single-quarter impairment loss / single-quarter total revenue",
    ),
    _indicator_field(
        "total_revenue_ps", "每股营业总收入", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative total revenue per ending share",
    ),
    _indicator_field(
        "revenue_ps", "每股营业收入", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative operating revenue per ending share",
    ),
    _indicator_field(
        "capital_rese_ps", "每股资本公积", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_end",
        "supplier ending capital reserve per share",
    ),
    _indicator_field(
        "surplus_rese_ps", "每股盈余公积", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_end",
        "supplier ending surplus reserve per share",
    ),
    _indicator_field(
        "undist_profit_ps", "每股未分配利润", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_end",
        "supplier ending undistributed profit per share",
    ),
    _indicator_field(
        "diluted2_eps", "期末摊薄每股收益", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative parent net profit per ending share; not diluted EPS",
    ),
    _indicator_field(
        "ocfps", "每股经营现金净流量", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative operating net cashflow per ending share",
    ),
    _indicator_field(
        "retainedps", "每股留存收益", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_end",
        "supplier ending retained earnings per share",
    ),
    _indicator_field(
        "cfps", "每股现金净流量", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative net cashflow per ending share; not operating cashflow",
    ),
    _indicator_field(
        "ebit_ps", "每股息税前利润", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative supplier EBIT per ending share",
    ),
    _indicator_field(
        "q_eps", "单季每股收益", "单季度指标", "CNY/share", "CNY/share",
        "latest_visible_single_quarter",
        "supplier supplier single-quarter earnings per share",
    ),
    _indicator_field(
        "salescash_to_or", "销售及劳务收现/营业收入", "现金流与资本支出比率", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier cumulative sales and service cash receipts / operating revenue",
    ),
    _indicator_field(
        "ocf_to_or", "经营现金净流量/营业收入", "现金流与资本支出比率", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier cumulative operating net cashflow / operating revenue",
    ),
    _indicator_field(
        "ocf_to_opincome", "经营现金净流量/经营活动净收益",
        "现金流与资本支出比率", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier cumulative operating net cashflow / operating activity net income",
    ),
    _indicator_field(
        "capitalized_to_da", "资本支出/折旧摊销", "现金流与资本支出比率", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier cumulative supplier capital expenditure / depreciation and amortization",
    ),
    _indicator_field(
        "ocf_to_profit", "经营现金净流量/营业利润", "现金流与资本支出比率", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier cumulative operating net cashflow / operating profit",
    ),
    _indicator_field(
        "q_salescash_to_or", "单季销售及劳务收现/营业收入", "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single-quarter sales and service cash receipts / operating revenue",
    ),
    _indicator_field(
        "q_ocf_to_sales", "单季经营现金净流量/营业收入", "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single-quarter operating net cashflow / operating revenue",
    ),
    _indicator_field(
        "q_ocf_to_or", "单季经营现金净流量/经营活动净收益", "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single-quarter operating net cashflow / operating activity net income",
    ),
    _indicator_field(
        "net_profit_margin", "销售净利率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: consolidated net income / operating revenue ",
        source_column="netprofit_margin",
    ),
    _indicator_field(
        "gross_profit_margin", "销售毛利率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: gross profit / operating revenue ",
        source_column="grossprofit_margin",
    ),
    _indicator_field(
        "profit_to_gr", "净利润/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: consolidated net income / total revenue ",
        source_column="profit_to_gr",
    ),
    _indicator_field(
        "cogs_of_sales", "销售成本占比",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating cost / operating revenue ",
        source_column="cogs_of_sales",
    ),
    _indicator_field(
        "expense_of_sales", "销售期间费用占比",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: period expenses / operating revenue; historical R&D "
        "classification retained ",
        source_column="expense_of_sales",
    ),
    _indicator_field(
        "saleexp_to_gr", "销售费用/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: selling expense / total revenue ",
        source_column="saleexp_to_gr",
    ),
    _indicator_field(
        "adminexp_of_gr", "管理费用/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: administrative expense / total revenue; historical R&D "
        "classification retained ",
        source_column="adminexp_of_gr",
    ),
    _indicator_field(
        "finaexp_of_gr", "财务费用/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: finance expense / total revenue ",
        source_column="finaexp_of_gr",
    ),
    _indicator_field(
        "gc_of_gr", "营业总成本/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: total operating cost / total revenue ",
        source_column="gc_of_gr",
    ),
    _indicator_field(
        "op_of_gr", "营业利润/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating profit / total revenue ",
        source_column="op_of_gr",
    ),
    _indicator_field(
        "ebit_of_gr", "息税前利润/营业总收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: EBIT / total revenue ",
        source_column="ebit_of_gr",
    ),
    _indicator_field(
        "opincome_of_ebt", "经营活动净收益/利润总额",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating activity net income / total profit ",
        source_column="opincome_of_ebt",
    ),
    _indicator_field(
        "investincome_of_ebt", "价值变动净收益/利润总额",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: value-change net income / total profit; not investment "
        "income alone ",
        source_column="investincome_of_ebt",
    ),
    _indicator_field(
        "n_op_profit_of_ebt", "营业外收支净额/利润总额",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: nonoperating receipts less expenses / total profit ",
        source_column="n_op_profit_of_ebt",
    ),
    _indicator_field(
        "tax_to_ebt", "所得税/利润总额",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: income tax / total profit ",
        source_column="tax_to_ebt",
    ),
    _indicator_field(
        "dtprofit_to_profit", "扣非净利润/净利润",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: deducted net profit / parent net income ",
        source_column="dtprofit_to_profit",
    ),
    _indicator_field(
        "op_to_ebt", "营业利润/利润总额",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating profit / total profit ",
        source_column="op_to_ebt",
    ),
    _indicator_field(
        "nop_to_ebt", "非营业利润/利润总额",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: supplier nonoperating net profit / total profit ",
        source_column="nop_to_ebt",
    ),
    _indicator_field(
        "profit_to_op", "利润总额/营业收入",
        "收入与利润结构", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: total profit / total revenue in retained samples; "
        "supplier label says revenue ",
        source_column="profit_to_op",
    ),
    _indicator_field(
        "q_net_profit_margin", "单季销售净利率",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: consolidated net income / operating revenue ",
        source_column="q_netprofit_margin",
    ),
    _indicator_field(
        "q_gross_profit_margin", "单季销售毛利率",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: gross profit / operating revenue ",
        source_column="q_gsprofit_margin",
    ),
    _indicator_field(
        "q_exp_to_sales", "单季销售期间费用占比",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: period expenses / operating revenue; historical expense "
        "classification retained ",
        source_column="q_exp_to_sales",
    ),
    _indicator_field(
        "q_profit_to_gr", "单季净利润/营业总收入",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: consolidated net income / total revenue ",
        source_column="q_profit_to_gr",
    ),
    _indicator_field(
        "q_saleexp_to_gr", "单季销售费用/营业总收入",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: selling expense / total revenue ",
        source_column="q_saleexp_to_gr",
    ),
    _indicator_field(
        "q_adminexp_to_gr", "单季管理费用/营业总收入",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: administrative expense / total revenue; historical expense "
        "classification retained ",
        source_column="q_adminexp_to_gr",
    ),
    _indicator_field(
        "q_finaexp_to_gr", "单季财务费用/营业总收入",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: finance expense / total revenue ",
        source_column="q_finaexp_to_gr",
    ),
    _indicator_field(
        "q_gc_to_gr", "单季营业总成本/营业总收入",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: total operating cost / total revenue ",
        source_column="q_gc_to_gr",
    ),
    _indicator_field(
        "q_op_to_gr", "单季营业利润/营业总收入",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: operating profit / total revenue ",
        source_column="q_op_to_gr",
    ),
    _indicator_field(
        "q_opincome_to_ebt", "单季经营活动净收益/利润总额",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: operating activity net income / total profit ",
        source_column="q_opincome_to_ebt",
    ),
    _indicator_field(
        "q_investincome_to_ebt", "单季价值变动净收益/利润总额",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: value-change net income / total profit ",
        source_column="q_investincome_to_ebt",
    ),
    _indicator_field(
        "q_dtprofit_to_profit", "单季扣非净利润/净利润",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: deducted net profit / parent net income ",
        source_column="q_dtprofit_to_profit",
    ),
    _indicator_field(
        "debt_to_assets", "资产负债比率",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: total liabilities / total assets ",
        source_column="debt_to_assets",
    ),
    _indicator_field(
        "ca_to_assets", "流动资产占总资产比",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: current assets / total assets ",
        source_column="ca_to_assets",
    ),
    _indicator_field(
        "nca_to_assets", "非流动资产占总资产比",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: noncurrent assets / total assets ",
        source_column="nca_to_assets",
    ),
    _indicator_field(
        "tbassets_to_totalassets", "有形净资产/总资产（供应商口径）",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: supplier tangible net-equity amount / total assets ",
        source_column="tbassets_to_totalassets",
    ),
    _indicator_field(
        "int_to_talcap", "有息债务/全部投入资本",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: interest-bearing debt / invested capital ",
        source_column="int_to_talcap",
    ),
    _indicator_field(
        "eqt_to_talcapital", "归母权益/全部投入资本",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: parent equity / invested capital ",
        source_column="eqt_to_talcapital",
    ),
    _indicator_field(
        "currentdebt_to_debt", "流动负债占总负债比",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: current liabilities / total liabilities ",
        source_column="currentdebt_to_debt",
    ),
    _indicator_field(
        "longdeb_to_debt", "非流动负债占总负债比",
        "财务结构与偿债", "ratio", "percent",
        "latest_visible_report_end",
        "supplier report end: noncurrent liabilities / total liabilities ",
        source_column="longdeb_to_debt",
    ),
    _indicator_field(
        "assets_to_eqt", "权益乘数",
        "财务结构与偿债", "multiple", "multiple",
        "latest_visible_report_end",
        "supplier report end: total assets / consolidated equity ",
        source_column="assets_to_eqt",
    ),
    _indicator_field(
        "debt_to_eqt", "产权比率",
        "财务结构与偿债", "multiple", "multiple",
        "latest_visible_report_end",
        "supplier report end: total liabilities / consolidated equity ",
        source_column="debt_to_eqt",
    ),
    _indicator_field(
        "quick_ratio", "速动比率",
        "财务结构与偿债", "multiple", "multiple",
        "latest_visible_report_end",
        "supplier report end: current assets less inventory / current liabilities ",
        source_column="quick_ratio",
    ),
    _indicator_field(
        "eqt_to_debt", "归母权益/负债合计",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: parent equity / total liabilities ",
        source_column="eqt_to_debt",
    ),
    _indicator_field(
        "eqt_to_interestdebt", "归母权益/有息债务",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: parent equity / interest-bearing debt ",
        source_column="eqt_to_interestdebt",
    ),
    _indicator_field(
        "tangibleasset_to_debt", "有形净资产/负债合计（供应商口径）",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: supplier tangible net-equity amount / total liabilities ",
        source_column="tangibleasset_to_debt",
    ),
    _indicator_field(
        "tangasset_to_intdebt", "有形净资产/有息债务（供应商口径）",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: supplier tangible net-equity amount / interest-bearing debt ",
        source_column="tangasset_to_intdebt",
    ),
    _indicator_field(
        "tangibleasset_to_netdebt", "有形净资产/净债务（供应商口径）",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: supplier tangible net-equity amount / net debt ",
        source_column="tangibleasset_to_netdebt",
    ),
    _indicator_field(
        "cash_to_liqdebt", "货币资金/流动负债",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: monetary funds / current liabilities ",
        source_column="cash_to_liqdebt",
    ),
    _indicator_field(
        "cash_to_liqdebt_withinterest", "货币资金/有息流动负债",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: monetary funds / interest-bearing current liabilities ",
        source_column="cash_to_liqdebt_withinterest",
    ),
    _indicator_field(
        "ocf_to_shortdebt", "经营现金净流量/流动负债",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative operating net cashflow / ending current "
        "liabilities ",
        source_column="ocf_to_shortdebt",
    ),
    _indicator_field(
        "ocf_to_debt", "经营现金净流量/负债合计",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative operating net cashflow / ending total "
        "liabilities ",
        source_column="ocf_to_debt",
    ),
    _indicator_field(
        "ocf_to_interestdebt", "经营现金净流量/有息债务",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative operating net cashflow / ending interest- "
        "bearing debt ",
        source_column="ocf_to_interestdebt",
    ),
    _indicator_field(
        "ocf_to_netdebt", "经营现金净流量/净债务",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative operating net cashflow / ending net debt ",
        source_column="ocf_to_netdebt",
    ),
    _indicator_field(
        "ebitda_to_debt", "息税折旧摊销前利润/负债合计",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative EBITDA / ending total liabilities ",
        source_column="ebitda_to_debt",
    ),
    _indicator_field(
        "op_to_liqdebt", "营业利润/流动负债",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative operating profit / ending current liabilities ",
        source_column="op_to_liqdebt",
    ),
    _indicator_field(
        "op_to_debt", "营业利润/负债合计",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_cumulative",
        "supplier report cumulative: cumulative operating profit / ending total liabilities ",
        source_column="op_to_debt",
    ),
    _indicator_field(
        "basic_eps_yoy", "基本每股收益同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: basic EPS ",
        source_column="basic_eps_yoy",
    ),
    _indicator_field(
        "dt_eps_yoy", "稀释每股收益同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: diluted EPS ",
        source_column="dt_eps_yoy",
    ),
    _indicator_field(
        "ocfps_yoy", "每股经营现金净流量同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: operating net cashflow per share; not total net cashflow per "
        "share ",
        source_column="cfps_yoy",
    ),
    _indicator_field(
        "op_yoy", "营业利润同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: operating profit ",
        source_column="op_yoy",
    ),
    _indicator_field(
        "ebt_yoy", "利润总额同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: total profit ",
        source_column="ebt_yoy",
    ),
    _indicator_field(
        "dt_netprofit_yoy", "归母扣非净利润同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: parent deducted net profit; retain supplier rounding and "
        "adjustments ",
        source_column="dt_netprofit_yoy",
    ),
    _indicator_field(
        "ocf_yoy", "经营现金净流量同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: operating net cashflow ",
        source_column="ocf_yoy",
    ),
    _indicator_field(
        "roe_yoy", "摊薄净资产收益率同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: diluted ROE; not percentage-point change or ordinary ROE growth ",
        source_column="roe_yoy",
    ),
    _indicator_field(
        "tr_yoy", "营业总收入同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: total revenue ",
        source_column="tr_yoy",
    ),
    _indicator_field(
        "or_yoy", "营业收入同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: operating revenue ",
        source_column="or_yoy",
    ),
    _indicator_field(
        "equity_yoy", "净资产同比增长率",
        "同比增长", "ratio", "percent",
        "latest_visible_report_yoy",
        "supplier report yoy: supplier net assets; parent-equity sample has a historical "
        "adjustment discrepancy ",
        source_column="equity_yoy",
    ),
    _indicator_field(
        "bps_ytd_growth", "每股净资产较年初增长率",
        "较年初增长", "ratio", "percent",
        "latest_visible_report_year_start_growth",
        "supplier report year start growth: book value per share compared with preceding year "
        "end ",
        source_column="bps_yoy",
    ),
    _indicator_field(
        "assets_ytd_growth", "总资产较年初增长率",
        "较年初增长", "ratio", "percent",
        "latest_visible_report_year_start_growth",
        "supplier report year start growth: total assets compared with preceding year end ",
        source_column="assets_yoy",
    ),
    _indicator_field(
        "equity_parent_ytd_growth", "归母权益较年初增长率",
        "较年初增长", "ratio", "percent",
        "latest_visible_report_year_start_growth",
        "supplier report year start growth: parent equity compared with preceding year end ",
        source_column="eqt_yoy",
    ),
    _indicator_field(
        "q_gr_yoy", "单季营业总收入同比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_yoy",
        "supplier single quarter yoy: single-quarter total revenue versus same quarter last "
        "year ",
        source_column="q_gr_yoy",
    ),
    _indicator_field(
        "q_sales_yoy", "单季营业收入同比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_yoy",
        "supplier single quarter yoy: single-quarter operating revenue versus same quarter "
        "last year ",
        source_column="q_sales_yoy",
    ),
    _indicator_field(
        "q_op_yoy", "单季营业利润同比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_yoy",
        "supplier single quarter yoy: single-quarter operating profit versus same quarter last "
        "year ",
        source_column="q_op_yoy",
    ),
    _indicator_field(
        "q_profit_yoy", "单季净利润同比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_yoy",
        "supplier single quarter yoy: single-quarter consolidated net profit versus same "
        "quarter last year ",
        source_column="q_profit_yoy",
    ),
    _indicator_field(
        "q_netprofit_yoy", "单季归母净利润同比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_yoy",
        "supplier single quarter yoy: single-quarter parent net profit versus same quarter "
        "last year ",
        source_column="q_netprofit_yoy",
    ),
    _indicator_field(
        "q_gr_qoq", "单季营业总收入环比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_qoq",
        "supplier single quarter qoq: single-quarter total revenue versus preceding quarter ",
        source_column="q_gr_qoq",
    ),
    _indicator_field(
        "q_sales_qoq", "单季营业收入环比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_qoq",
        "supplier single quarter qoq: single-quarter operating revenue versus preceding "
        "quarter ",
        source_column="q_sales_qoq",
    ),
    _indicator_field(
        "q_op_qoq", "单季营业利润环比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_qoq",
        "supplier single quarter qoq: single-quarter operating profit versus preceding quarter ",
        source_column="q_op_qoq",
    ),
    _indicator_field(
        "q_profit_qoq", "单季净利润环比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_qoq",
        "supplier single quarter qoq: single-quarter consolidated net profit versus preceding "
        "quarter ",
        source_column="q_profit_qoq",
    ),
    _indicator_field(
        "q_netprofit_qoq", "单季归母净利润环比增长率",
        "单季度增长", "ratio", "percent",
        "latest_visible_single_quarter_qoq",
        "supplier single quarter qoq: single-quarter parent net profit versus preceding "
        "quarter ",
        source_column="q_netprofit_qoq",
    ),
    _indicator_field(
        "dt_eps", "稀释每股收益",
        "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier report cumulative: diluted EPS; distinct from profit divided by ending "
        "shares ",
        source_column="dt_eps",
    ),
    _indicator_field(
        "extra_item", "非经常损益额",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: nonrecurring profit or loss; retain supplier adjustment "
        "and rounding ",
        source_column="extra_item",
    ),
    _indicator_field(
        "profit_dedt", "扣非净利润",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: deducted net profit; retain supplier definition and "
        "adjustments ",
        source_column="profit_dedt",
    ),
    _indicator_field(
        "op_income", "经营活动净收益",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating activity net income; not operating profit or "
        "net cashflow ",
        source_column="op_income",
    ),
    _indicator_field(
        "valuechange_income", "价值变动净收益",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: value-change net income; distinct from investment income "
        "alone ",
        source_column="valuechange_income",
    ),
    _indicator_field(
        "interest_expense", "利息费用",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: interest expense, despite source spelling interst_income ",
        source_column="interst_income",
    ),
    _indicator_field(
        "daa", "折旧与摊销",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: depreciation and amortization ",
        source_column="daa",
    ),
    _indicator_field(
        "ebit", "息税前利润",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: earnings before interest and tax ",
        source_column="ebit",
    ),
    _indicator_field(
        "ebitda", "息税折旧摊销前利润",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: earnings before interest, tax, depreciation and "
        "amortization ",
        source_column="ebitda",
    ),
    _indicator_field(
        "profit_prefin_exp", "扣财务费用前营业利润",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating profit before finance expense ",
        source_column="profit_prefin_exp",
    ),
    _indicator_field(
        "non_op_profit", "非营业利润",
        "利润与现金流基础值", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier report cumulative: nonoperating net profit; not gross nonoperating receipts ",
        source_column="non_op_profit",
    ),
    _indicator_field(
        "current_exint", "无息流动负债",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: non-interest current liabilities; supplier component "
        "classification retained ",
        source_column="current_exint",
    ),
    _indicator_field(
        "noncurrent_exint", "无息非流动负债",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: non-interest noncurrent liabilities; supplier component "
        "classification retained ",
        source_column="noncurrent_exint",
    ),
    _indicator_field(
        "interestdebt", "有息债务额",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: interest-bearing debt; total liabilities less supplier non- "
        "interest liabilities ",
        source_column="interestdebt",
    ),
    _indicator_field(
        "netdebt", "净债务额",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: interest-bearing debt less monetary funds ",
        source_column="netdebt",
    ),
    _indicator_field(
        "tangible_asset", "有形净资产（供应商口径）",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: tangible net-equity amount; not total assets less intangible "
        "assets ",
        source_column="tangible_asset",
    ),
    _indicator_field(
        "working_capital", "营运资金额",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: current assets less current liabilities ",
        source_column="working_capital",
    ),
    _indicator_field(
        "networking_capital", "营运流动资本",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: current assets less monetary funds and non-interest current "
        "liabilities ",
        source_column="networking_capital",
    ),
    _indicator_field(
        "invest_capital", "全部投入资本",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: consolidated equity plus interest-bearing debt ",
        source_column="invest_capital",
    ),
    _indicator_field(
        "retained_earnings", "留存收益额",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: surplus reserve plus undistributed profit ",
        source_column="retained_earnings",
    ),
    _indicator_field(
        "fixed_assets", "固定资产合计",
        "资产与资本基础值", "CNY", "CNY",
        "latest_visible_report_end",
        "supplier report end: fixed-asset aggregate including construction and investment "
        "property in samples ",
        source_column="fixed_assets",
    ),
    _indicator_field(
        "q_opincome", "单季经营活动净收益",
        "单季度指标", "CNY", "CNY",
        "latest_visible_single_quarter",
        "supplier single quarter: single-quarter operating activity net income ",
        source_column="q_opincome",
    ),
    _indicator_field(
        "q_investincome", "单季价值变动净收益",
        "单季度指标", "CNY", "CNY",
        "latest_visible_single_quarter",
        "supplier single quarter: single-quarter value-change net income ",
        source_column="q_investincome",
    ),
    _indicator_field(
        "q_dtprofit", "单季扣非净利润",
        "单季度指标", "CNY", "CNY",
        "latest_visible_single_quarter",
        "supplier single quarter: single-quarter deducted net profit; supplier adjustments "
        "retained ",
        source_column="q_dtprofit",
    ),
    _indicator_field(
        "invturn_days", "存货周转天数",
        "营运效率", "day", "day",
        "latest_visible_report_cumulative",
        "supplier report cumulative: inventory turnover days; report months times30 divided by "
        "rounded turnover ",
        source_column="invturn_days",
    ),
    _indicator_field(
        "arturn_days", "应收账款周转天数",
        "营运效率", "day", "day",
        "latest_visible_report_cumulative",
        "supplier report cumulative: receivable turnover days; report months times30 divided "
        "by rounded turnover ",
        source_column="arturn_days",
    ),
    _indicator_field(
        "turn_days", "营业周转周期",
        "营运效率", "day", "day",
        "latest_visible_report_cumulative",
        "supplier report cumulative: inventory plus receivable turnover days; not cash "
        "conversion cycle ",
        source_column="turn_days",
    ),
    _indicator_field(
        "inv_turn", "存货周转率",
        "营运效率", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating cost / year-start and ending average inventory ",
        source_column="inv_turn",
    ),
    _indicator_field(
        "ar_turn", "应收账款周转率",
        "营运效率", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: operating revenue / year-start and ending average "
        "receivables ",
        source_column="ar_turn",
    ),
    _indicator_field(
        "ca_turn", "流动资产周转率",
        "营运效率", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: total revenue / year-start and ending average current "
        "assets ",
        source_column="ca_turn",
    ),
    _indicator_field(
        "fa_turn", "固定资产周转率",
        "营运效率", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: total revenue / year-start and ending average fixed "
        "assets ",
        source_column="fa_turn",
    ),
    _indicator_field(
        "assets_turn", "总资产周转率",
        "营运效率", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: total revenue / year-start and ending average total "
        "assets ",
        source_column="assets_turn",
    ),
    _indicator_field(
        "total_fa_trun", "固定资产合计周转率",
        "营运效率", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: total revenue / average supplier fixed-asset aggregate ",
        source_column="total_fa_trun",
    ),
    _indicator_field(
        "dp_assets_to_eqt", "杜邦权益乘数",
        "财务结构与偿债", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier report cumulative: year-start and ending average assets / average parent "
        "equity ",
        source_column="dp_assets_to_eqt",
    ),
    _indicator_field(
        "longdebt_to_workingcapital", "长期债务/营运资金",
        "财务结构与偿债", "ratio", "ratio",
        "latest_visible_report_end",
        "supplier report end: long-term debt / working capital; supplier debt classification "
        "retained ",
        source_column="longdebt_to_workingcapital",
    ),
    _indicator_field(
        "roe_dt", "扣非净资产收益率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: deducted net profit / year-start and ending average "
        "parent equity ",
        source_column="roe_dt",
    ),
    _indicator_field(
        "roa", "总资产报酬率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: EBIT / year-start and ending average total assets ",
        source_column="roa",
    ),
    _indicator_field(
        "npta", "总资产净利润指标",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: consolidated net profit / year-start and ending average "
        "total assets ",
        source_column="npta",
    ),
    _indicator_field(
        "roa_dp", "杜邦总资产净利率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: parent net profit / year-start and ending average total "
        "assets ",
        source_column="roa_dp",
    ),
    _indicator_field(
        "roic", "投入资本回报率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier report cumulative: after-tax EBIT / year-start and ending average invested "
        "capital ",
        source_column="roic",
    ),
    _indicator_field(
        "roe_yearly", "年化净资产收益率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_annualized",
        "supplier report annualized: annualized parent profit / average parent equity; not TTM ",
        source_column="roe_yearly",
    ),
    _indicator_field(
        "roa2_yearly", "年化总资产收益率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_annualized",
        "supplier report annualized: annualized EBIT / average total assets; not TTM ",
        source_column="roa2_yearly",
    ),
    _indicator_field(
        "roa_yearly", "年化总资产净利率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_annualized",
        "supplier report annualized: annualized consolidated net profit / average total "
        "assets; not TTM ",
        source_column="roa_yearly",
    ),
    _indicator_field(
        "roic_yearly", "年化投入资本回报率",
        "盈利能力", "ratio", "percent",
        "latest_visible_report_annualized",
        "supplier report annualized: annualized after-tax EBIT / average invested capital; not "
        "TTM ",
        source_column="roic_yearly",
    ),
    _indicator_field(
        "q_dt_roe", "单季扣非净资产收益率",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: single-quarter deducted net profit / previous-quarter and "
        "ending average parent equity ",
        source_column="q_dt_roe",
    ),
    _indicator_field(
        "q_npta", "单季总资产净利润指标",
        "单季度指标", "ratio", "percent",
        "latest_visible_single_quarter",
        "supplier single quarter: single-quarter consolidated net profit / previous-quarter "
        "and ending average assets ",
        source_column="q_npta",
    ),
    _indicator_field(
        "rd_exp", "研发投入总额", "利润与现金流金额", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier cumulative research investment including expensed and capitalized spending; "
        "not income statement R&D expense alone",
    ),
    _indicator_field(
        "roe_waa", "加权平均净资产收益率", "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier cumulative weighted return on equity; not simple average-balance ROE",
    ),
    _indicator_field(
        "roe_avg", "增发条件平均净资产收益率", "盈利能力", "ratio", "percent",
        "latest_visible_report_cumulative",
        "supplier issuance-condition average ROE for the report period; "
        "not a three-year rolling average or an alias of weighted ROE",
    ),
    _indicator_field(
        "cash_ratio", "保守速动比率", "财务结构与偿债", "multiple", "multiple",
        "latest_visible_report_end",
        "supplier conservative quick ratio at report end; liquid-asset component scope "
        "is supplier-defined, not monetary funds alone divided by liabilities",
    ),
    _indicator_field(
        "ebit_to_interest", "息税前利润/利息费用", "财务结构与偿债", "multiple", "multiple",
        "latest_visible_report_cumulative",
        "supplier cumulative interest coverage; sampled denominator includes capitalized "
        "interest and deducts interest income, unlike expensed interest alone",
    ),
    _indicator_field(
        "fcff", "企业自由现金流", "利润与现金流金额", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier cumulative free cashflow to firm; not operating cashflow minus capex alone; "
        "historical differences from the statement free-cashflow column are retained",
    ),
    _indicator_field(
        "fcfe", "股权自由现金流", "利润与现金流金额", "CNY", "CNY",
        "latest_visible_report_cumulative",
        "supplier cumulative free cashflow to equity; sampled firm cashflow plus borrowing "
        "and bond proceeds less debt repayment; not interchangeable with FCFF",
    ),
    _indicator_field(
        "fcff_ps", "每股企业自由现金流", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative free cashflow to firm per ending share; read the original "
        "per-share value without reconstructing it from other fields",
    ),
    _indicator_field(
        "fcfe_ps", "每股股东自由现金流", "每股指标", "CNY/share", "CNY/share",
        "latest_visible_report_cumulative",
        "supplier cumulative free cashflow to equity per ending share; read the original "
        "per-share value without reconstructing it from other fields",
    ),
)


FIELD_DEFINITIONS = (
    *MARKET_FIELDS, *DAILY_BASIC_FIELDS, *FINANCIAL_FIELDS, *FINANCIAL_INDICATOR_FIELDS,
)


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
