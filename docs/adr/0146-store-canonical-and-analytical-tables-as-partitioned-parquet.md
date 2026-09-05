# Store Canonical and analytical tables as partitioned Parquet

Canonical data and retained analytical tables use partitioned ZSTD Parquet, while bounded manifests, provenance, and summaries use canonical JSON. Exact-byte SHA-256 identity supports immutable publication, deduplication, and verification without retaining transient calculation tables or making this format the store for operational records.
