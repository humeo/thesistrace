---
status: accepted
---

# Apply the initial six financial fields to all company types

The Financial Field Applicability of `total_revenue_latest_fy`,
`net_profit_parent_latest_fy`, `operating_cash_flow_latest_fy`,
`total_assets_latest_reported`, `total_liabilities_latest_reported`, and
`equity_parent_latest_reported` includes Tushare `comp_type` 1, 2, 3, and 4:
general industrial, banking, insurance, and securities companies. These six
fields are consolidated-statement top-level monetary quantities with a stable
field meaning across those reporting company types. Differences in economic
interpretation belong to research construction rather than Data-owned field
validity. Applicability grants no value guarantee: a source null or missing
accepted statement remains a Missing Alpha Value and never falls back to
another report type, company-type-specific field, zero, or a changed Liquidity
Universe.
