# 06 — Materialize and reopen a mounted Data Generation

**What to build:** Materialize one complete immutable Canonical Market Data
Generation in a Mounted Canonical Data Store and reopen it after process
restart without depending on a Dataset Release row or a remote DataSource.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] One Generation stores its growing Canonical Market Data tables as deterministic partitioned Parquet objects with bounded manifests and explicit schema and writer contracts.
- [x] The Generation manifest records Dataset Coverage, data-through Research Session, required table/object identities, field availability, and internal preparation metadata.
- [x] A Generation is immutable once finalized; reopening validates manifest identity, object byte counts and checksums, table schemas, canonical ordering, and required cross-table invariants.
- [x] Writing the same canonical content from reordered source rows produces the same canonical table bytes, checksums, manifest data identity, and reusable content-addressed Physical Data Objects without requiring a stable Generation identifier.
- [x] A fresh process can reopen the prepared mount and read the same calendar, instruments, market facts, adjusted prices, and Universe snapshots without a PostgreSQL Dataset Release lookup.
- [x] Missing, corrupt, incompatible, or partially written objects fail validation and are never presented as a complete Generation.
- [x] Materialization and reopening perform no Tushare or other remote DataSource call.
- [x] During the expand stage, the existing Release reader can still reopen an already-published Release through its established seam with an unchanged projection; adding a mounted Generation does not mutate that Release.

## Comments

- Implemented by `0df0e29 feat(data): materialize mounted generations`; review hardening is in `bfd930a`, `fc07493`, `221acd2`, and `072a51f`.
- The store writes deterministic session/row-partitioned Parquet behind bounded content-addressed manifests, reopens without PostgreSQL or a DataSource, and validates complete Canonical cross-table, adjustment, listing-lifecycle, and writer contracts.
- Addressed files use bounded pre-read metadata checks, streamed hashes, component-by-component `dirfd` access with `O_NOFOLLOW`, nonblocking regular-file validation, atomic hard-link installation, and directory synchronization on winner and loser paths.
- Focused mounted-store verification passed `20 passed in 1.59s`; all Data and adapter tests passed `73 passed in 15.85s`; the complete Kernel suite passed `118 passed in 190.98s`. Ruff and diff checks passed.
- A real isolated PostgreSQL/RustFS acceptance proved the legacy queued ResearchRun can publish and reopen through the unchanged Release reader (`1 passed in 13.52s`); its dedicated containers, network, and volumes were removed afterward.
- Standards and Spec reviews used fixed point `072a51f` and both ended with zero findings after correction of adjusted-price derivation, resource bounds, filesystem durability/concurrency, symlink/FIFO safety, pre-Coverage Anchors, and listing lifecycles.
