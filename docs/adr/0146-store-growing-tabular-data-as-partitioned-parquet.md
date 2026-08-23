---
status: accepted
---

# Store growing tabular data as partitioned Parquet

Canonical Market Data and retained Strategy tables that grow with Research
Sessions, instruments, or events use partitioned Parquet with ZSTD, while
manifests, configuration, provenance, bounded summaries, and accepted raw source
evidence use canonical JSON. Each immutable object is identified by SHA-256 over
its exact bytes so publication, deduplication, provenance, and byte budgets share
one identity; transient Alpha, Label, daily Factor, and raw execution values are
not retained.
