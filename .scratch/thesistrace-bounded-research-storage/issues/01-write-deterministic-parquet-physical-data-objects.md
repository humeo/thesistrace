# 01 — Write deterministic Parquet Physical Data Objects

**What to build:** Let operators publish and reopen immutable tabular objects
whose exact ZSTD Parquet bytes, checksum, and recorded writer contract provide
one reproducible identity, while bounded control records continue to use
canonical JSON.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] One production writer stores a declared table as ZSTD Parquet and reads it back without changing its schema, logical values, or canonical row order.
- [ ] Every immutable Parquet object is identified by the lowercase SHA-256 digest of its exact file bytes, and its manifest entry records the exact byte count and writer-contract identifier.
- [ ] The writer contract fixes the explicit schema, column order, canonical sort keys, logical and null representations, one row group, concrete writer implementation and package/runtime version, Parquet version, ZSTD version and level, and all byte-affecting encoding options.
- [ ] Writing the same logical table in fresh processes with different source row order and field insertion order produces byte-for-byte identical objects and the same identity.
- [ ] Input that cannot be ordered under the declared object contract is rejected rather than written with process-dependent order.
- [ ] A byte-affecting writer change requires a new writer-contract identifier, while objects written under the prior contract remain readable and retain their identities.
- [ ] Existing canonical JSON manifests, configuration, provenance, and bounded summaries remain deterministic and readable through the same immutable-object boundary.
