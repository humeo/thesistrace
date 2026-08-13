---
status: accepted
---

# Build initial financial fields only from latest consolidated statements

The first six Session-Aligned Financial Fields use only accepted Tushare
`report_type=1` Source Financial Versions, fixing one Consolidated Reporting
Scope across instruments and report periods. The
`net_profit_parent_latest_fy` Alpha Identifier selects the
parent-owner-attributable amount inside that consolidated statement;
it does not use a parent standalone report. Every other source report type
remains retained for audit but does not enter these six fields. Single-quarter,
adjusted, pre-adjustment, or parent-only reporting scopes may later receive
distinct Field Identifiers, but they never act as fallback inputs or change the
meaning of the initial fields.
