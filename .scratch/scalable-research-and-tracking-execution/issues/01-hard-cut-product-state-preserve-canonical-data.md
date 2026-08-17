# 01 — Hard-cut Product State while preserving Canonical Data

**What to build:** Let a developer adopt the new execution and schema contract without
downloading market and financial data again: the ordinary Development Product State
Reset removes every old product resource, preserves the mounted Canonical Data Store
and Dataset Head, and refuses Product State created under a result-changing old
Numeric Execution Contract.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] The identity-checked development reset stops the canonical Compose project and removes only PostgreSQL and RustFS Product State volumes.
- [ ] Reset preserves the canonical-data volume, every immutable Canonical Data object, and the exact Dataset Head identity.
- [ ] Reset initializes the current schemas and starts a runtime that immediately validates and reuses the preserved Dataset Head without contacting Tushare.
- [ ] Reset removes Research Folders, ResearchRuns, Attempts, Results, private execution state, DailyTracks, receipts, caches, and other Product State.
- [ ] Browser references to removed Product resources are treated as stale local state rather than migrated server state.
- [ ] A separate identity-checked development erase operation removes PostgreSQL, RustFS, and Canonical Data and makes the need to bootstrap or restore data explicit.
- [ ] ResearchRuns and DailyTracks record the one current Numeric Execution Contract identity for provenance and validation.
- [ ] Runtime startup or execution refuses Product State accepted under a result-changing different contract identity.
- [ ] No schema migration, compatibility reader, fallback, Tracking Generation branch, old-contract dispatcher, or automatic reinterpretation path remains.
- [ ] Isolated lifecycle tests prove reset preservation and erase destruction against real named volumes without public network access.
- [ ] Existing ordinary development start, stop, watch, logs, and bootstrap behavior remains valid after the command boundary changes.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- This is the first ticket in the approved fully serial implementation chain.
