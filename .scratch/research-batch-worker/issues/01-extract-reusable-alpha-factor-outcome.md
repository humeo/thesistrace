# 01 — Extract a reusable Alpha-and-Factor execution outcome

**What to build:** Give the existing Research execution pipeline one validated
Alpha-and-Factor outcome that can either finish an ordinary Factor Evaluation or
continue into the existing Strategy calculation, without changing any current
ResearchRun answer.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] One formal Research Kernel boundary returns the complete validated Alpha-and-Factor outcome needed by both Factor Evaluation and Strategy execution.
- [ ] The outcome is bound to the frozen Research input, compiled Alpha plan, Data Generation, Numeric Execution Contract, field bindings, Universe, Label horizons, and calculation semantic versions.
- [ ] The outcome retains the authoritative Factor Summary and only the bounded continuation data needed by the existing execution pipeline; it is not a new public Result, cache, or Product resource.
- [ ] Ordinary Factor Evaluation still stops at this boundary and publishes exactly its current Factor-only Result contract.
- [ ] Alpha, Forward Return Label, Neutralization, Factor metrics, Coverage, quantile, and Top-Bottom calculations continue to use one implementation rather than a Batch-specific copy.
- [ ] Row-reference and columnar Alpha-and-Factor execution remain canonically equivalent across missing values, changing Universe membership, rolling and cross-sectional operators, and Decimal inputs.
- [ ] Bounded Chunk continuation and uninterrupted calculation produce the same validated outcome at every supported boundary without duplicating or omitting matured Labels.
- [ ] Invalid bindings, non-finite values, incompatible continuation, and calculation-contract mismatches fail closed before the outcome can be consumed or published.
- [ ] Existing ordinary Factor Evaluation Result checksums, provenance, progress, retry, cancellation, and Publication behavior remain unchanged through the public ResearchRun boundary.
- [ ] The previous fused-only internal path is removed once all current callers use the formal boundary; no compatibility seam, fallback executor, or second calculation implementation remains.

## Comments

- Parent: Research Batch Worker.
- Approved Prefactor that makes shared Strategy execution possible while keeping the current product green.
