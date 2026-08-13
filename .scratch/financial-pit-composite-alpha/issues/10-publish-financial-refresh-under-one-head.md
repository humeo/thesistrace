# 10 — Publish Financial Refresh under one Dataset Head

**What to build:** Turn the complete Financial Refresh candidate into a private
operator action that atomically publishes one executable financial-capable Data
Generation alongside unchanged market families. Publication must be fenced
against concurrent refresh, preserve one consistency boundary for execution,
and expose family-specific Coverage and all-or-nothing Financial Research
Readiness without allowing an ingestion-only Head.

**Blocked by:** 09 — Lock 2010-scale I/O, Pin, and GC boundaries.

**Status:** complete

- [x] Market Refresh and Financial Refresh are distinct private Data Operator
  actions that both publish through one Dataset Head.
- [x] Each action materializes only its target family group and reuses
  unchanged family Manifest and Physical Data Object identities.
- [x] Financial Refresh publishes only a candidate with complete expected
  shards, Canonical financial tables, Financial Coverage, six executable field
  capabilities, ResearchRun readiness, DailyTrack readiness, and accepted
  performance evidence.
- [x] Raw-only, table-only, resolver-only, or ResearchRun-only financial
  candidates cannot move the Dataset Head or enter the Alpha Authoring Catalog.
- [x] Publication compares with the expected current Head and prevents a stale
  candidate root from overwriting a newer Generation.
- [x] When another refresh moves the Head first, the completed target family is
  recomposed with the latest unchanged family Manifests and all cross-family
  invariants are revalidated before a new publication attempt.
- [x] Concurrent Market Refresh is not delayed or failed by multi-hour
  Financial Refresh collection.
- [x] Partial financial collection, failed validation, failed object write, or
  failed compare-and-swap leaves the prior Head and freshness metadata
  authoritative.
- [x] Successful publication exposes Market Coverage, Financial Coverage Start,
  financial observation-through cutoff, reconciliation and revision limits,
  last successful refresh times, and Financial Research Readiness.
- [x] Data Overview reads those declarations from descriptors without opening
  Parquet and does not imply that every instrument has a non-null fact.
- [x] A published financial cutoff gates only Formulae and Tracks that
  reference financial fields.
- [x] Operator submission and publication are idempotent and concurrency tests
  use the real database, lifecycle fence, and immutable store.
- [x] No independent financial Head, automatic V1 schedule, public refresh API,
  or ordinary web update control is added.

## Comments

- Parent: Point-in-Time Financial Data and Composite Alpha.
- Verification: `bun run test` passed (366 Python tests, web typecheck, 10 shell
  tests); isolated `./scripts/test-runtime integration` run
  `20260813t054023z-6111-856dff71` passed 148 tests plus the database-restart
  acceptance and cleaned its environment.
- Review: final independent Spec and Standards re-reviews both returned CLEAN.
