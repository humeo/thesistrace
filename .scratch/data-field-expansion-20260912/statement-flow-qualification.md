# TTM flow source qualification

All 19 source columns have a non-null comparison against an independently read consolidated company report. This qualifies observed amount units and source mapping; it does not prove complete historical coverage or identical economics across company types.

| DSL | Source | Amount evidence |
| --- | --- | --- |
| cash_paid_capex_ttm | cashflow.c_pay_acq_const_fiolta | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| cash_received_sales_ttm | cashflow.c_fr_sale_sg | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| cash_paid_goods_ttm | cashflow.c_paid_goods_s | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| cash_received_asset_disposals_ttm | cashflow.n_recp_disp_fiolta | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| cash_paid_acquisitions_ttm | cashflow.n_disp_subs_oth_biz | [statement-flow-acquisition-crosscheck.json](statement-flow-acquisition-crosscheck.json) |
| cash_paid_investments_ttm | cashflow.c_paid_invest | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| cash_received_borrowing_ttm | cashflow.c_recp_borrow | [statement-flow-financing-crosscheck.json](statement-flow-financing-crosscheck.json) |
| cash_paid_debt_repayment_ttm | cashflow.c_prepay_amt_borr | [statement-flow-financing-crosscheck.json](statement-flow-financing-crosscheck.json) |
| operating_revenue_ttm | income.revenue | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| consolidated_net_profit_ttm | income.n_income | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| operating_cost_ttm | income.oper_cost | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| rd_expense_ttm | income.rd_exp | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| investment_income_ttm | income.invest_income | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| fair_value_gain_ttm | income.fv_value_chg_gain | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| nonoperating_income_ttm | income.non_oper_income | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| nonoperating_expense_ttm | income.non_oper_exp | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| revenue_ttm | income.total_revenue | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| net_profit_ttm | income.n_income_attr_p | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |
| operating_cash_flow_ttm | cashflow.n_cashflow_act | [statement-flow-unit-crosscheck.json](statement-flow-unit-crosscheck.json) |

## Scope and period

The source contract uses report_type 1 consolidated year-to-date statements. Calendar quarter-end targets and matching prior-year components are required for TTM. Core revenue and parent-profit fields preserve their original scope; consolidated net profit remains distinct. Source CNY amounts are retained without percentage conversion. Cash payment fields retain the supplier sign; parentheses for outflows in a company report are not an instruction to negate the supplier amount.

[TuShare cashflow definition](https://tushare.pro/wctapi/documents/44.md) explicitly distinguishes acquisition payments n_disp_subs_oth_biz from disposal receipts n_recp_disp_sobu, and borrowing receipts from bond issuance. These fields are not interchangeable.

Supported company categories remain 1/2/3/4 under the current financial contract. The annual/Q1 observations cover general industry, bank, insurer and securities companies. Bank, insurance and securities operating-cost/R&D columns are empty in the observed Q1 samples; empty values remain missing, and total operating expense is not substituted. Supplier revenue for these companies follows their consolidated financial-business revenue definition, rather than industrial sales. The catalog must not imply cross-industry comparability. Category 7 is not admitted by the existing source contract.

The Ping An Q1 consolidated income statement independently corroborates revenue 218405, consolidated profit 33263, parent profit 25022, investment gain 40913, fair-value loss -49952, nonoperating income 62 and expense 159 in million CNY; its cash-flow unit and financing amounts are recorded separately. Source observations can include multiple versions and nulls; observation alone does not establish their historical order.

Full-history completeness and per-year/company-type coverage remain ticket 07 work. Announcements and observed revisions retain the accepted evidence limits. The three qualification JSON files record source links, report pages, independent amounts and comparisons; the original raw observations remain unchanged.
