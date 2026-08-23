---
status: accepted
---

# Apply the six financial fields to all company types

The Financial Field Applicability of `revenue`, `net_profit`,
`operating_cash_flow`, `assets`, `liabilities`, and `equity` includes Tushare
`comp_type` 1, 2, 3, and 4: general industrial, banking, insurance, and
securities companies. These are consolidated-statement top-level monetary
quantities with a stable field meaning across those reporting company types;
economic interpretation belongs to research construction rather than a hidden
Data filter.

Applicability grants no value guarantee: a source null or missing accepted
statement remains a Missing Alpha Value and never falls back to another report
type, a company-specific field, zero, or a changed Liquidity Universe.
