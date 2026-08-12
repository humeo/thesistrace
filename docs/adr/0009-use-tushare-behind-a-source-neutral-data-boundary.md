---
status: accepted
---

# Use Tushare behind a source-neutral data boundary

ThesisTrace uses Tushare Pro as its sole external data source. V1 does not
implement alternate providers, fallback retrieval, cross-source reconciliation,
or a general provider abstraction. If required Tushare inputs are unavailable
or invalid, the candidate Data Generation fails instead of substituting another source.

Data nevertheless owns one narrow private `DataSource.collect` seam because
Core has a real Tushare adapter and a deterministic Fixture adapter for product
acceptance. This is an internal external-system boundary, not a user-selectable
multi-provider framework; Tushare remains the only real source.

The Data module retains the accepted source responses, validates and translates
them into Canonical Market Data, and records their provenance in each Data
Generation. Research Definition and ResearchRun never call Tushare or
depend on its field names. This boundary stabilizes the research contract; it
is not a multi-source framework.
