---
status: accepted
---

# Defer TTM and start flow fields from latest annual reports

The initial flow-valued financial fields are `total_revenue_latest_fy`,
`net_profit_parent_latest_fy`, and `operating_cash_flow_latest_fy`, each a
Latest Annual Financial Field sourced from the most recent available full-year
Consolidated Reporting Scope. The initial stock-valued fields remain
`total_assets_latest_reported`, `total_liabilities_latest_reported`, and
`equity_parent_latest_reported`, each selecting the most recent available
quarterly or annual balance-sheet fact. ThesisTrace does not construct TTM in
the first financial slice: rolling-twelve-month convenience does not justify
adding cumulative-period reconstruction before immutable ingestion, PIT
availability, and annual/report-point projection work end to end. TTM may later
be introduced only as new derived Field Identifiers over the already retained
Financial Facts.
