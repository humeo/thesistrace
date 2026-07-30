---
status: accepted
---

# Use Tushare behind a source-neutral data boundary

ThesisTrace uses Tushare Pro as its sole external data source. V1 does not
implement alternate providers, fallback retrieval, cross-source reconciliation,
or a general provider abstraction. If required Tushare inputs are unavailable
or invalid, Dataset Publication fails instead of substituting another source.

Dataset Publication retains the accepted source responses, validates and
translates them into Canonical Market Data, and records their provenance in
each Dataset Release. Research Definition and ResearchRun never call Tushare or
depend on its field names. This boundary stabilizes the research contract; it
is not a multi-source framework.
