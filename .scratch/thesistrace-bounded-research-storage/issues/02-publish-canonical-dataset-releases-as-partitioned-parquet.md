# 02 — Publish Canonical Dataset Releases as partitioned Parquet

**What to build:** Let operators bootstrap, increment, correct, and materialize
Dataset Releases whose growing Canonical tables use reusable ZSTD Parquet
partitions, so one new Research Session does not rewrite or copy historical
market data. This is a deliberate wide-refactor exception: expand the Release
reader beside the current representation, migrate every publication path and
consumer while checks stay green, then remove the legacy Canonical writer.

**Blocked by:** 01 — Write deterministic Parquet Physical Data Objects.

**Status:** ready-for-agent

- [ ] Fixture and live Dataset Publication store every Canonical table that grows with Research Sessions, instruments, or events as deterministic ZSTD Parquet rather than one nested JSON document.
- [ ] A normal one-session publication writes only the new session's required Canonical partitions and reuses every unchanged predecessor object by identity.
- [ ] An accepted correction replaces only affected Canonical partitions, preserves all unaffected object identities, and materializes the corrected and derived values exactly.
- [ ] Dataset Release manifests bind each Canonical object's Dataset Family, partition coordinates, schema version, writer-contract identifier, exact bytes, and checksum.
- [ ] Bootstrap, one-session increment, multi-session catch-up, correction, and idempotent replay remain atomic through the public Dataset Release lifecycle.
- [ ] Field Catalog, Dataset contract views, ResearchRun inputs, Universe membership, and adjustment semantics are canonically identical after materializing the Parquet-backed Release.
- [ ] During the expand step, Release materialization can read both legacy fixture objects and new Parquet partitions; after fixture, live, increment, catch-up, correction, and research consumers migrate, new Releases no longer write the legacy nested Canonical object.
- [ ] Bounded manifests, schemas, and configuration remain canonical JSON, and this ticket does not choose or migrate the encoding of accepted Tushare Source evidence.
