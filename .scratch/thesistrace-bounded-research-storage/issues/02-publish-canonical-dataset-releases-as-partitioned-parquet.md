# 02 — Publish Canonical Dataset Releases as partitioned Parquet

**What to build:** Let operators bootstrap, increment, correct, and materialize
Dataset Releases whose growing Canonical tables use reusable ZSTD Parquet
partitions, so one new Research Session does not rewrite or copy historical
market data. This is a deliberate wide-refactor exception: expand the Release
reader beside the current representation, migrate every publication path and
consumer while checks stay green, then remove the legacy Canonical writer.

**Blocked by:** 01 — Write deterministic Parquet Physical Data Objects.

**Status:** resolved

- [x] Fixture and live Dataset Publication store every Canonical table that grows with Research Sessions, instruments, or events as deterministic ZSTD Parquet rather than one nested JSON document.
- [x] A normal one-session publication writes only the new session's required Canonical partitions and reuses every unchanged predecessor object by identity.
- [x] An accepted correction replaces only affected Canonical partitions, preserves all unaffected object identities, and materializes the corrected and derived values exactly.
- [x] Dataset Release manifests bind each Canonical object's Dataset Family, partition coordinates, schema version, writer-contract identifier, exact bytes, and checksum.
- [x] Bootstrap, one-session increment, multi-session catch-up, correction, and idempotent replay remain atomic through the public Dataset Release lifecycle.
- [x] Field Catalog, Dataset contract views, ResearchRun inputs, Universe membership, and adjustment semantics are canonically identical after materializing the Parquet-backed Release.
- [x] During the expand step, Release materialization can read both legacy fixture objects and new Parquet partitions; after fixture, live, increment, catch-up, correction, and research consumers migrate, new Releases no longer write the legacy nested Canonical object.
- [x] Bounded manifests, schemas, and configuration remain canonical JSON, and this ticket does not choose or migrate the encoding of accepted Tushare Source evidence.

## Comments

- Added explicit per-family schemas and partition coordinates for the V1
  Canonical tables. New fixture, live-bootstrap, fixture-increment, live
  increment, catch-up, and correction Releases write only
  `canonical_partition` Parquet objects; Tushare Source evidence remains JSON.
- Materialization retains legacy `canonical_fixture` and `canonical_delta`
  reading, and the next publication from a legacy predecessor migrates the
  active Canonical state to Parquet without carrying legacy Canonical JSON into
  the new Release.
- Capacity evidence for the deterministic 35-instrument, 756-session fixture:
  legacy Canonical JSON was `19,684,882` bytes; the ten Canonical Parquet
  objects total `223,953` bytes. A one-session publication adds six Canonical
  objects totaling `11,228` bytes and reuses all ten predecessor objects by
  SHA-256 identity.
- Verification: `uv run python -m pytest --maxfail=1 -q` (`49 passed`), `uv
  run ruff check .`, and the five focused Parquet Release lifecycle tests all
  completed successfully.
