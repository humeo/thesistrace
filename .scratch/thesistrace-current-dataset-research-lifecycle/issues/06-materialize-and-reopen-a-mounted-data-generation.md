# 06 — Materialize and reopen a mounted Data Generation

**What to build:** Materialize one complete immutable Canonical Market Data
Generation in a Mounted Canonical Data Store and reopen it after process
restart without depending on a Dataset Release row or a remote DataSource.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] One Generation stores its growing Canonical Market Data tables as deterministic partitioned Parquet objects with bounded manifests and explicit schema and writer contracts.
- [ ] The Generation manifest records Dataset Coverage, data-through Research Session, required table/object identities, field availability, and internal preparation metadata.
- [ ] A Generation is immutable once finalized; reopening validates manifest identity, object byte counts and checksums, table schemas, canonical ordering, and required cross-table invariants.
- [ ] Writing the same canonical content from reordered source rows produces the same canonical table bytes, checksums, manifest data identity, and reusable content-addressed Physical Data Objects without requiring a stable Generation identifier.
- [ ] A fresh process can reopen the prepared mount and read the same calendar, instruments, market facts, adjusted prices, and Universe snapshots without a PostgreSQL Dataset Release lookup.
- [ ] Missing, corrupt, incompatible, or partially written objects fail validation and are never presented as a complete Generation.
- [ ] Materialization and reopening perform no Tushare or other remote DataSource call.
- [ ] During the expand stage, the existing Release reader can still reopen an already-published Release through its established seam with an unchanged projection; adding a mounted Generation does not mutate that Release.
