---
status: accepted
---

# Use one ordinary per-instrument Tushare financial collector

ThesisTrace collects the initial income statement, balance sheet, and cash-flow
statement families only through Tushare's ordinary per-instrument endpoints,
using one resumable `endpoint × instrument` shard contract. The collector does
not implement VIP endpoints or switch transport after a permission, rate, or
completeness failure. Every accepted response batch is retained as evidence,
and a candidate Data Generation remains unpublished until the complete expected
shard set passes schema, truncation, and coverage validation. This accepts a
slower bootstrap and refresh path in exchange for one deployable 2000-point
permission contract with deterministic provenance and failure behavior.
