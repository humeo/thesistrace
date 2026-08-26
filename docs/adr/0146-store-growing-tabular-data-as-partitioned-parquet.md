# Store growing tabular data as partitioned Parquet

Canonical and retained product tables that grow by session, instrument, or event use partitioned ZSTD Parquet, while bounded manifests, provenance, and summaries use canonical JSON. Exact-byte SHA-256 identity provides immutable publication, deduplication, and verification without retaining transient calculation tables.
