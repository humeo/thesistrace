---
status: superseded by ADR-0179
---

# Start financial Alpha with six composable base quantities

The first Alpha-authorable Session-Aligned Financial Fields are
`total_revenue_ttm`, `net_profit_parent_ttm`,
`operating_cash_flow_ttm`, `total_assets_latest_reported`,
`total_liabilities_latest_reported`, and
`equity_parent_latest_reported`. They map respectively from Tushare
`income.total_revenue`, `income.n_income_attr_p`,
`cashflow.n_cashflow_act`, `balancesheet.total_assets`,
`balancesheet.total_liab`, and
`balancesheet.total_hldr_eqy_exc_min_int`. ThesisTrace begins with these
composable reported quantities instead of simultaneously publishing vendor
ratios, per-share measures, or every retained numeric source column. Retained
Financial Facts may become authorable later only through new stable fields with
complete session-alignment and applicability semantics; the initial six names
never broaden or change meaning.
