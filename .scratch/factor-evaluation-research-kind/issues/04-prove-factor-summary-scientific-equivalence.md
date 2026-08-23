# 04 — Prove Factor Summary scientific equivalence

**What to build:** Make Factor Evaluation a scientifically trustworthy outcome by
proving that it reports the same Factor evidence as Strategy Backtest for the same
frozen inputs, including missing evidence, changing Universes, retained diagnostics,
and Chunk boundaries.

**Blocked by:** 03 — Resume and cancel long Factor Evaluation safely

**Status:** complete

## Plan

1. Freeze the scientific contract at its existing public and durable boundaries:
   horizons 1/5/20, correlation summaries and coverage, retained quantile and
   Top-Bottom diagnostics, checksums, and the absence of transient daily Alpha
   or Label evidence from the Result Bundle.
2. Strengthen the independent row/columnar and Chunked/uninterrupted kernel
   equivalence matrix across changing Universe membership, missing values,
   rolling and cross-sectional operators, Decimal execution prices, and every
   relevant fixed Chunk boundary; round-trip Factor continuation at each
   boundary to model private Checkpoint recovery.
3. Add insufficient-sample Factor Evaluation acceptance that proves null metrics
   and zero valid-session counts are a successful scientific outcome rather
   than fabricated zero or a failed Run.
4. Add one real public ResearchRun scenario that admits Factor Evaluation and
   Strategy Backtests with identical frozen Factor inputs on the same Generation,
   varies Strategy parameters, and compares the published `factor_summary`
   payload bytes, retained diagnostics, Coverage, and checksums exactly.
5. Tighten the primary Factor UI regression so only Rank IC, Rank ICIR, IC,
   ICIR, and Coverage are emphasized while authoritative retained diagnostics
   remain outside the primary rendering.
6. Run focused scientific, Result-contract, frontend, and real-dependency gates,
   then the repository fast gate; complete independent Standards and Spec
   reviews, fix and re-review all material findings, mark the ticket complete,
   and create one Ticket 04 commit.

- [x] The Factor Summary retains fixed Forward Return Label horizons of 1, 5, and 20 Research Sessions.
- [x] Every Horizon retains mean Rank IC, Rank ICIR, mean IC, ICIR, Rank IC valid-session Coverage, and IC valid-session Coverage under the current scientific definitions.
- [x] Existing Five-Quantile Return and Top-Bottom Return calculations, Coverage, and checksums remain in the authoritative Factor Summary.
- [x] The primary Factor Evaluation view emphasizes only Rank IC, Rank ICIR, IC, ICIR, and Coverage while retained diagnostics remain available to the Result contract.
- [x] Insufficient valid samples produce null metrics and zero valid-session counts without failing an otherwise valid ResearchRun or fabricating numeric zero.
- [x] Daily Factor observations, Alpha Values, and stock-level Forward Return Labels remain transient and are not added to the Result Bundle.
- [x] Identical Formula, resolved Research Period, Universe, Neutralization, field bindings, calculation contracts, and Data Generation produce byte-equivalent `factor_summary` content for Factor Evaluation and Strategy Backtest.
- [x] Strategy parameters and Strategy outcomes cannot alter the shared Factor calculation or Factor Summary.
- [x] Chunked and uninterrupted Factor calculation are canonically equivalent across dynamic Universe membership, absent values, rolling operators, cross-sectional ranks, decimal inputs, and every Chunk boundary.
- [x] Factor-only retry from a private Checkpoint is equivalent to uninterrupted Factor Evaluation and does not duplicate or omit matured Forward Return Labels.
- [x] Result validation covers binary64 and decimal canonicalization, per-Horizon checksums, retained diagnostics, and public Result serialization rather than only comparing four displayed numbers.
- [x] A complete public acceptance scenario admits both Research Kinds against the same frozen Generation and compares their published Factor Summaries exactly.
- [x] Existing Strategy ledger, costs, Benchmark, holdings, rebalance, NAV, and terminal-state reference tests remain unchanged and passing.

## Comments

- Kept one shared Factor calculation and Result contract for both Research Kinds;
  this ticket adds scientific proof rather than a second execution path.
- Real PostgreSQL, RustFS, Publication, and supervised-child acceptance runs one
  Factor Evaluation and two Strategy Backtests on the same 130-session frozen
  Generation. Their raw published `factor_summary` bytes are identical while
  the two Strategy payloads differ under different holdings and rebalance inputs.
- Kernel equivalence covers dynamic Universe membership, missing values,
  rolling and cross-sectional operators, Decimal execution inputs, binary64
  canonicalization, 40/60, 63, and 64 boundaries, and canonical Checkpoint
  continuation round trips without duplicate or omitted matured labels.
- Insufficient samples remain successful with null metrics and zero valid counts;
  the primary Factor UI renders only IC, Rank IC, their ICIRs, and Coverage while
  retained quantiles, Top-Bottom evidence, and checksums stay authoritative.
- Review: independent Standards/Test Ruler and Spec reviews both passed with no
  material findings.
- Verification: focused scientific gates passed 36 Python tests, TypeScript type
  checking, and 37 frontend shell tests; isolated integration run
  `20260819t191724z-74324-01e4d604` passed 195 ordinary tests plus the dedicated
  database-restart test; `pnpm test` passed 523 Python tests, TypeScript type
  checking, and 37 frontend shell tests.
