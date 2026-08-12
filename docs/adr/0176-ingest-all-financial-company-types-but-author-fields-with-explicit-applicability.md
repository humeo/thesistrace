---
status: accepted
---

# Ingest all financial company types but author fields with explicit applicability

ThesisTrace ingests accepted Tushare financial statement fields for general
industrial, banking, insurance, and securities companies instead of excluding a
company type from Point-in-Time Financial Data. A Session-Aligned Financial
Field becomes Alpha-authorable only with an explicit Financial Field
Applicability declaring the company types over which its meaning is comparable.
Non-applicable instruments produce missing inputs and visible coverage loss;
they are never filled with zero or silently removed by changing the selected
Liquidity Universe. Cross-company fields may be opened first, while retained
sector-specific Financial Facts remain non-authorable until their applicability
and research semantics are defined.
