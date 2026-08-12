---
status: accepted
---

# Preserve complete financial source data but author only session-aligned fields

ThesisTrace retains every field from each in-scope Tushare income statement,
balance sheet, and cash-flow Source Financial Version; all returned numeric
fields on those versions enter Canonical Point-in-Time Financial Data rather
than being filtered to the first factors the product exposes. An accepted Raw
Financial Batch remains immutable source evidence even when its complete-history
response also contains rows outside Financial Coverage and its required seeds;
those out-of-scope rows do not become Financial Facts. Source metadata and
Financial Facts remain available for audit, but a raw report column does not
become Alpha-authorable merely because it is numeric. Only a stable
Session-Aligned Financial Field whose definition fixes report-period selection,
reporting scope, aggregation, revision availability, unit, and missingness may
receive an Alpha Field Capability. This preserves full source breadth without
misrepresenting differently grained or cumulative report values as comparable
daily Numeric Series.
