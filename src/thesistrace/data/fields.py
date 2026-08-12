from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorableField:
    field_id: str
    evaluation_name: str
    definition: str
    unit: str
    family_id: str = "equity.eod_price"
    numeric_type: str = "decimal"
    information_time: str = "post-close"
    reporting_scope: str = "market-observation"
    report_period_selection: str = "research-session"
    missingness: str = "missing"
    source_lineage: str = "tushare.daily"
    applicable_company_types: tuple[str, ...] = ()


MARKET_FIELDS = (
    AuthorableField(
        "price.open.adjusted",
        "open_adj",
        "causal cumulative-adjusted open",
        "CNY/share",
    ),
    AuthorableField(
        "price.high.adjusted",
        "high_adj",
        "causal cumulative-adjusted high",
        "CNY/share",
    ),
    AuthorableField(
        "price.low.adjusted",
        "low_adj",
        "causal cumulative-adjusted low",
        "CNY/share",
    ),
    AuthorableField(
        "price.close.adjusted",
        "close_adj",
        "causal cumulative-adjusted close",
        "CNY/share",
    ),
    AuthorableField(
        "market.volume.shares",
        "volume_shares",
        "traded share volume",
        "shares",
    ),
    AuthorableField(
        "market.turnover.cny",
        "turnover_amount_cny",
        "turnover amount",
        "CNY",
    ),
)

FINANCIAL_FIELDS = (
    AuthorableField(
        "total_revenue_latest_fy",
        "total_revenue_latest_fy",
        "latest visible full-year consolidated total revenue",
        "CNY",
        family_id="equity.financial_pit",
        information_time="next-research-session",
        reporting_scope="report_type_1_consolidated",
        report_period_selection="latest_visible_full_year",
        source_lineage="tushare.income.total_revenue",
        applicable_company_types=("1", "2", "3", "4"),
    ),
    AuthorableField(
        "net_profit_parent_latest_fy",
        "net_profit_parent_latest_fy",
        "latest visible full-year consolidated net profit attributable to parent owners",
        "CNY",
        family_id="equity.financial_pit",
        information_time="next-research-session",
        reporting_scope="report_type_1_consolidated",
        report_period_selection="latest_visible_full_year",
        source_lineage="tushare.income.n_income_attr_p",
        applicable_company_types=("1", "2", "3", "4"),
    ),
    AuthorableField(
        "operating_cash_flow_latest_fy",
        "operating_cash_flow_latest_fy",
        "latest visible full-year consolidated net operating cash flow",
        "CNY",
        family_id="equity.financial_pit",
        information_time="next-research-session",
        reporting_scope="report_type_1_consolidated",
        report_period_selection="latest_visible_full_year",
        source_lineage="tushare.cashflow.n_cashflow_act",
        applicable_company_types=("1", "2", "3", "4"),
    ),
    AuthorableField(
        "total_assets_latest_reported",
        "total_assets_latest_reported",
        "latest visible quarterly or annual consolidated total assets",
        "CNY",
        family_id="equity.financial_pit",
        information_time="next-research-session",
        reporting_scope="report_type_1_consolidated",
        report_period_selection="latest_visible_quarterly_or_annual",
        source_lineage="tushare.balancesheet.total_assets",
        applicable_company_types=("1", "2", "3", "4"),
    ),
    AuthorableField(
        "total_liabilities_latest_reported",
        "total_liabilities_latest_reported",
        "latest visible quarterly or annual consolidated total liabilities",
        "CNY",
        family_id="equity.financial_pit",
        information_time="next-research-session",
        reporting_scope="report_type_1_consolidated",
        report_period_selection="latest_visible_quarterly_or_annual",
        source_lineage="tushare.balancesheet.total_liab",
        applicable_company_types=("1", "2", "3", "4"),
    ),
    AuthorableField(
        "equity_parent_latest_reported",
        "equity_parent_latest_reported",
        "latest visible quarterly or annual consolidated equity attributable to parent owners",
        "CNY",
        family_id="equity.financial_pit",
        information_time="next-research-session",
        reporting_scope="report_type_1_consolidated",
        report_period_selection="latest_visible_quarterly_or_annual",
        source_lineage="tushare.balancesheet.total_hldr_eqy_exc_min_int",
        applicable_company_types=("1", "2", "3", "4"),
    ),
)

AUTHORABLE_FIELDS = MARKET_FIELDS


def authorable_fields() -> tuple[AuthorableField, ...]:
    return AUTHORABLE_FIELDS


def authorable_field_bindings() -> dict[str, str]:
    """Return Data-owned stable field IDs bound to Kernel evaluation names."""
    return {field.field_id: field.evaluation_name for field in AUTHORABLE_FIELDS}
