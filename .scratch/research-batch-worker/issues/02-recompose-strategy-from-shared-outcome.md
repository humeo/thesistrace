# 02 — Recompose Strategy execution from the shared outcome

**What to build:** Let the ordinary Strategy Backtest consume the validated
Alpha-and-Factor outcome and produce the same complete Strategy Result as today,
while making that upstream outcome safe to consume repeatedly with different
Strategy parameters.

**Blocked by:** 01 — Extract a reusable Alpha-and-Factor execution outcome

**Status:** complete

## Plan

1. Add failing interface tests that consume one completed Alpha-and-Factor
   outcome repeatedly with different Strategy parameter tuples and prove the
   shared Factor evidence remains unchanged while portfolio paths differ.
2. Extract one Strategy consumer boundary from the ordinary fused Chunk path.
   It validates the shared outcome binding, owns Strategy continuation and
   terminal-state calculation, and returns one defensive Strategy outcome.
3. Recompose ordinary Strategy Backtest through the new consumer while Factor
   Evaluation continues to stop at the Alpha-and-Factor boundary. Remove the
   inlined Strategy block after all callers use the consumer.
4. Cover wrong Generation/scope/Alpha/Numeric/Semantic binding, Strategy
   continuation, repeated consumption, row-columnar, Chunked/uninterrupted,
   result bytes, provenance, and Start Tracking behavior at the lowest real
   seams that exercise each invariant.
5. Run focused tests, the complete fast gate, and isolated real-dependency
   ResearchRun acceptance; then perform independent Standards and Spec review,
   fix and re-review to clean, update this tracker, and create the independent
   Ticket 02 commit.

- [x] Ordinary Strategy Backtest continues from the formal Alpha-and-Factor outcome through the one existing Strategy calculation and terminal-state path.
- [x] The shared outcome is immutable from the Strategy consumer's perspective, so running one Strategy cannot alter the Factor evidence or a later Strategy calculation.
- [x] Repeating Strategy calculation from one outcome with different Holdings Count and Rebalance Sessions produces one independently validated Strategy outcome per parameter tuple.
- [x] The same frozen ordinary Strategy Backtest input produces byte-equivalent Factor Summary, Strategy Summary, Strategy Daily Observations, Terminal Strategy State, and semantic checksums before and after the prefactor.
- [x] Every ordinary Strategy Result retains its own correct ResearchRun identity and calculation provenance.
- [x] Changing Strategy parameters cannot alter the shared Factor Summary, while deliberate Holdings Count and Rebalance Sessions changes affect the applicable portfolio path.
- [x] Row-reference, columnar, bounded-Chunk, and uninterrupted Alpha/Factor/Strategy equivalence remain covered through the new consumer boundary.
- [x] Strategy validation rejects an outcome with the wrong Generation, frozen scope, compiled Alpha identity, Numeric Execution Contract, or semantic versions.
- [x] Factor Evaluation still performs no Strategy calculation, and successful Strategy Backtest still retains its ordinary Start Tracking authority.
- [x] The obsolete fused Strategy entry path is removed; there is no alternate Strategy math, compatibility adapter, fallback, or Batch-only kernel.

## Comments

- Parent: Research Batch Worker.
- Approved Prefactor that preserves ordinary Strategy behavior before Batch orchestration is introduced.
- Implemented one `StrategyChunkOutcome` consumer over the validated shared
  Alpha-and-Factor outcome. Strategy continuation is bound to both the shared
  execution binding and the canonical Strategy input, and mismatches fail
  closed before calculation.
- Repeated Strategy consumers reuse the same immutable Factor evidence while
  producing independent portfolio paths. Ordinary full-history and compact
  checkpoint contracts share the single `_execute_strategy` math core; the
  Batch seam requires metric state and has no reconstruction fallback.
- Removed the fused inline Strategy block. The core now returns unwrapped
  components and each caller constructs and canonical-serializes only the one
  envelope it needs. The representative 80-session by 40-instrument performance
  guard proves one large Strategy serialization per consumer and rejects shared
  Alpha/Factor recalculation or payload serialization.
- Review: final independent Standards re-review passed with P0 0, P1 0, P2 0;
  final independent Spec re-review passed with no Wrong, Missing, Partial, or
  Scope Creep findings.
- Verification: Ruff passed; focused Strategy/continuation and explicit-period
  gates passed (41); complete Python fast gate passed (539); complete isolated
  PostgreSQL/RustFS integration and acceptance gate passed (195 plus 1 database
  restart test), run `20260823t200612z-57621-bb2e64bf`. Test Compose project,
  network, and volumes were cleaned successfully (`cleanup_status=0`).
