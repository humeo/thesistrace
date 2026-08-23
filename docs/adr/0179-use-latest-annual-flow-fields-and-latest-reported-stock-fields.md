---
status: accepted
---

# Use latest annual flow fields and latest reported stock fields

`revenue`, `net_profit`, and `operating_cash_flow` are Latest Annual Financial
Fields sourced from the most recent visible full-year Consolidated Reporting
Scope. `assets`, `liabilities`, and `equity` are Latest Reported Stock Fields
from the most recent visible quarterly or annual consolidated balance sheet.

The current fields do not construct TTM values. Annual flows are less timely
than a correctly reconstructed trailing period, but avoid mixing cumulative
interim periods before immutable ingestion and point-in-time revision semantics
can support that separate meaning.
