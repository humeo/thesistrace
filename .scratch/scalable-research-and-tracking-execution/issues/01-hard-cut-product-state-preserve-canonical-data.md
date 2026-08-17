# 01 — Hard-cut Product State while preserving Canonical Data

**What to build:** Let a developer adopt the new execution and schema contract without
downloading market and financial data again: the ordinary Development Product State
Reset removes every old product resource, preserves the mounted Canonical Data Store
and Dataset Head, and refuses Product State created under a result-changing old
Numeric Execution Contract.

**Blocked by:** None — can start immediately

**Status:** complete

- [x] The identity-checked development reset stops the canonical Compose project and removes only PostgreSQL and RustFS Product State volumes.
- [x] Reset preserves the canonical-data volume, every immutable Canonical Data object, and the exact Dataset Head identity.
- [x] Reset initializes the current schemas and starts a runtime that immediately validates and reuses the preserved Dataset Head without contacting Tushare.
- [x] Reset removes Research Folders, ResearchRuns, Attempts, Results, private execution state, DailyTracks, receipts, caches, and other Product State.
- [x] Browser references to removed Product resources are treated as stale local state rather than migrated server state.
- [x] A separate identity-checked development erase operation removes PostgreSQL, RustFS, and Canonical Data and makes the need to bootstrap or restore data explicit.
- [x] ResearchRuns and DailyTracks record the one current Numeric Execution Contract identity for provenance and validation.
- [x] Runtime startup or execution refuses Product State accepted under a result-changing different contract identity.
- [x] No schema migration, compatibility reader, fallback, Tracking Generation branch, old-contract dispatcher, or automatic reinterpretation path remains.
- [x] Isolated lifecycle tests prove reset preservation and erase destruction against real named volumes without public network access.
- [x] Existing ordinary development start, stop, watch, logs, and bootstrap behavior remains valid after the command boundary changes.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- This is the first ticket in the approved fully serial implementation chain.
- Plan: first lock reset/erase and Numeric Contract behavior with failing lifecycle,
  kernel, and real PostgreSQL/RustFS acceptance tests; then implement the smallest
  shared destructive boundary, validate it at the real Docker layer, and retain
  all ordinary lifecycle commands.
- Implemented: `dev:reset` now preserves Canonical Data while hard-cutting Product
  State; `dev:erase` explicitly removes all Development volumes; Research and
  Tracking execution reject a non-current Numeric Execution Contract.
- Verification: `pnpm test` passed 475 Python and 25 Web tests; isolated integration
  passed 155 tests plus the database-restart test. The real named-volume probe used
  the production boundary with networking disabled and left no volumes behind.
- Review: Standards and Spec reviews both found the missing real production-boundary
  volume proof; it was fixed, rerun, and both final re-reviews passed with no material
  findings.
- Delivery: implementation and this terminal tracker update are finalized together
  in the Ticket 01 commit.
