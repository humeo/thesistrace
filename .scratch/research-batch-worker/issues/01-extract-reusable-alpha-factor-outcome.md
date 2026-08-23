# 01 — Extract a reusable Alpha-and-Factor execution outcome

**What to build:** Give the existing Research execution pipeline one validated
Alpha-and-Factor outcome that can either finish an ordinary Factor Evaluation or
continue into the existing Strategy calculation, without changing any current
ResearchRun answer.

**Blocked by:** None — can start immediately

**Status:** complete

## Plan

1. Add failing interface-level tests for an immutable Alpha-and-Factor execution
   binding and Chunk outcome, including canonical snapshots, Generation and
   calculation-contract mismatches, non-finite output rejection, final Factor
   Summary, and bounded continuation across real Chunk boundaries.
2. Introduce one deep in-process Research Kernel interface that owns common
   Alpha evaluation, pending Forward Return Labels, Factor aggregation, binding
   validation, and immutable outcome snapshots. Keep Strategy parameters and
   Research Kind outside this shared interface.
3. Recompose the existing ordinary Research Chunk journey around that interface:
   Factor Evaluation finalizes directly from the outcome, while Strategy
   Backtest consumes the same outcome before continuing through its unchanged
   Strategy implementation. Remove the former fused-only calculation segment.
4. Bind every production outcome explicitly to the immutable input's compiled
   Alpha facts, selected Research Period, fields, Universe, Neutralization,
   Numeric Execution Contract, semantic versions, and the claimed Data
   Generation without changing the child protocol or public Result contract.
5. Run focused Alpha/Factor/Strategy, row-columnar, Chunk-continuation, Result,
   and Research execution tests, followed by the complete fast repository gate.
6. Review the Ticket 01 diff independently against repository standards and the
   ticket/spec contract, fix every material finding, rerun affected gates,
   re-review to clean, check the acceptance criteria, update this tracker, and
   create one Ticket 01 commit.

- [x] One formal Research Kernel boundary returns the complete validated Alpha-and-Factor outcome needed by both Factor Evaluation and Strategy execution.
- [x] The outcome is bound to the frozen Research input, compiled Alpha plan, Data Generation, Numeric Execution Contract, field bindings, Universe, Label horizons, and calculation semantic versions.
- [x] The outcome retains the authoritative Factor Summary and only the bounded continuation data needed by the existing execution pipeline; it is not a new public Result, cache, or Product resource.
- [x] Ordinary Factor Evaluation still stops at this boundary and publishes exactly its current Factor-only Result contract.
- [x] Alpha, Forward Return Label, Neutralization, Factor metrics, Coverage, quantile, and Top-Bottom calculations continue to use one implementation rather than a Batch-specific copy.
- [x] Row-reference and columnar Alpha-and-Factor execution remain canonically equivalent across missing values, changing Universe membership, rolling and cross-sectional operators, and Decimal inputs.
- [x] Bounded Chunk continuation and uninterrupted calculation produce the same validated outcome at every supported boundary without duplicating or omitting matured Labels.
- [x] Invalid bindings, non-finite values, incompatible continuation, and calculation-contract mismatches fail closed before the outcome can be consumed or published.
- [x] Existing ordinary Factor Evaluation Result checksums, provenance, progress, retry, cancellation, and Publication behavior remain unchanged through the public ResearchRun boundary.
- [x] The previous fused-only internal path is removed once all current callers use the formal boundary; no compatibility seam, fallback executor, or second calculation implementation remains.

## Comments

- Parent: Research Batch Worker.
- Approved Prefactor that makes shared Strategy execution possible while keeping the current product green.
- Implemented one `AlphaFactorExecutionBinding` and one `AlphaFactorChunkOutcome`;
  ordinary Factor Evaluation and Strategy Backtest now consume the same
  Alpha/Label/Factor seam. Continuation records the binding checksum and fails
  closed on cross-Generation or cross-contract resume.
- Removed eager Alpha Matrix serialization and duplicate continuation/Factor
  State canonicalization from the per-Chunk hot path. One production execution
  constructs its Binding once and reuses it across Chunks.
- Repaired the minimal canonical fixture to select the authorable adjusted
  `close` field; the prior same-name raw field blocked real ResearchRun
  acceptance at admission.
- Review: final independent Standards re-review reported 0 HARD, 0 Judgment,
  and 0 Nit findings; final independent Spec re-review passed with no Wrong,
  Missing, Partial, or Scope Creep findings.
- Verification: Ruff passed; focused Kernel/Data tests passed (11); complete
  Python fast gate passed (536); isolated Worker-loss checkpoint recovery passed
  for Strategy Backtest and Factor Evaluation (2); complete isolated
  PostgreSQL/RustFS integration and acceptance gate passed (195 plus 1 database
  restart test). Test Compose projects and volumes were cleaned successfully.
