---
status: accepted
---

# Store growing tabular data as partitioned Parquet

Canonical Market Data and retained Strategy tables that grow with Research Sessions, instruments, or events use partitioned Parquet with ZSTD, while manifests, configuration, provenance, and bounded summaries use canonical JSON and transient Alpha, Label, daily Factor, and raw execution values are not stored. Each immutable Parquet Physical Data Object is produced by a pinned deterministic writer contract and identified by SHA-256 over its exact file bytes so publication, deduplication, and byte budgets share one unambiguous identity. The physical encoding of accepted Tushare source evidence remains deferred.
