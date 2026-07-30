# 01 — Write deterministic Parquet Physical Data Objects

**What to build:** Let operators publish and reopen immutable tabular objects
whose exact ZSTD Parquet bytes, checksum, and recorded writer contract provide
one reproducible identity, while bounded control records continue to use
canonical JSON.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] One production writer stores a declared table as ZSTD Parquet and reads it back without changing its schema, logical values, or canonical row order.
- [x] Every immutable Parquet object is identified by the lowercase SHA-256 digest of its exact file bytes, and its manifest entry records the exact byte count and writer-contract identifier.
- [x] The writer contract fixes the explicit schema, column order, canonical sort keys, logical and null representations, one row group, concrete writer implementation and package/runtime version, Parquet version, ZSTD version and level, and all byte-affecting encoding options.
- [x] Writing the same logical table in fresh processes with different source row order and field insertion order produces byte-for-byte identical objects and the same identity.
- [x] Input that cannot be ordered under the declared object contract is rejected rather than written with process-dependent order.
- [x] A byte-affecting writer change requires a new writer-contract identifier, while objects written under the prior contract remain readable and retain their identities.
- [x] Existing canonical JSON manifests, configuration, provenance, and bounded summaries remain deterministic and readable through the same immutable-object boundary.

## Comments

- Added the pinned `ParquetWriterContract` and content-addressed Parquet
  read/write boundary to `ImmutableObjectStore`; canonical JSON behavior remains
  unchanged.
- `tests/acceptance/test_parquet_objects.py` proves exact-byte identity across
  fresh processes, canonical ordering, contract upgrades, and rejection of
  ambiguous row identity.
- Verification: `uv run python -m pytest -q
  tests/acceptance/test_parquet_objects.py` (`4 passed`), `uv run ruff check
  src/thesistrace/objects.py tests/acceptance/test_parquet_objects.py`, and the
  full backend suite (`43 passed`) completed successfully.
