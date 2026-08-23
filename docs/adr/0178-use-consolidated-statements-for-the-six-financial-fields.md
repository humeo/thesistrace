---
status: accepted
---

# Use consolidated statements for the six financial fields

The six Session-Aligned Financial Fields use only accepted Tushare
`report_type=1` Source Financial Versions, fixing one Consolidated Reporting
Scope across instruments and report periods. `net_profit` selects the amount
attributable to parent owners inside that consolidated statement; it does not
use a parent standalone report.

Other source report types remain retained for audit but never act as fallback
inputs or change these Field meanings. Keeping one reporting scope sacrifices
alternate views in exchange for comparable point-in-time series.
