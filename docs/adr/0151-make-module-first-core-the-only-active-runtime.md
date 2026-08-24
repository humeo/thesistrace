---
status: accepted
---

# Make module-first Core the only active runtime

ThesisTrace is one module-first modular monolith spanning Data, Research
Folders, ResearchRuns, Results, and DailyTracks. PostgreSQL is authoritative for
Product State and claims, a mounted Canonical Data Store holds the current Data
Generation graph, RustFS holds immutable Product artifacts, a pure Research
Kernel performs calculations, and one Web/API surface is served by fixed-role
ordinary Research, Batch Research, and Tracking Workers.

A Browser Draft is compiled and admitted directly as an immutable ResearchRun
that freezes the current Data Generation; successful publication produces the
Result Bundle selected by Research Kind, and only a Strategy Backtest may seed
an independent DailyTrack. Lifecycle references become visible in PostgreSQL
only with the transaction that publishes their content-addressed objects.

The active product has no Local/Hosted runtime switch, SQLite Product State,
Temporal, event bus, login, tenancy, or alternate storage and execution ports.
Concrete PostgreSQL and object-storage coupling inside private module
interfaces is accepted in exchange for atomic locality and one fully tested
runtime; the complete current shape is documented in
[`docs/architecture/core.md`](../architecture/core.md).
