# 04 — Execute Factor Evaluation Batches with shared preparation

**What to build:** Let the dedicated Batch Research Worker execute an admitted
Factor Evaluation Batch in request order, preparing the common research data
once while publishing one ordinary, scientifically equivalent Factor Result per
submitted Alpha.

**Blocked by:** 01 — Extract a reusable Alpha-and-Factor execution outcome; 03 — Admit and inspect Research Batches atomically

**Status:** complete

## Implementation plan

1. Add a `batch-research` Worker role and a Research Batch-owned claim/attempt
   boundary that claims only the oldest queued Factor Evaluation Batch, freezes
   its admitted Generation, and fences all child Run state transitions.
2. Add one supervised Batch child protocol. The child opens the frozen
   Generation once, reads one canonical columnar slice using the union of item
   field bindings and maximum effective lookback, then executes independent
   `AlphaFactorChunkOutcome` calculations sequentially by item ordinal.
3. Add narrow ResearchRun-owned methods for Batch execution to start, publish,
   and fail Batch-owned child Runs through the existing Result serialization,
   Publication, provenance, metrics, and status contracts. Keep Batch tables
   out of the ResearchRun module and do not create a Batch-level Result.
4. Acknowledge each validated item before the child releases item-local state;
   isolate deterministic item failures and continue later items. Finish the
   Batch as succeeded, completed_with_failures, or failed from child outcomes.
5. Verify with contract/unit tests plus real PostgreSQL/RustFS acceptance tests:
   shared Data I/O and stage evidence, semantic equivalence to ordinary Runs,
   failure isolation, 1/20 ordering, frozen Generation, memory enforcement,
   dedicated-vs-ordinary Worker separation, and Production Image role smoke.

- [x] A fixed batch-research Worker role can claim one complete Factor Evaluation Batch and execute it through the same executable, Production Image, Research Kernel, supervised child model, and Publication system as ordinary Research.
- [x] The Batch builds one canonical Data slice from the union of required field bindings and maximum effective lookback and resolves the common Liquidity Universe and Forward Return Labels once.
- [x] Each submitted Alpha uses its own compiled plan and completes one independent Alpha-and-Factor calculation; values from different Alphas are never blended or inferred as one model.
- [x] Items execute sequentially in submitted ordinal order, and item-local working state is released after its complete task has been validated and acknowledged.
- [x] Every successful item publishes an ordinary Factor Evaluation Result containing only its Factor Summary and its own correct ResearchRun identity and provenance.
- [x] Against the same frozen Generation, each Batch item has the exact semantic Result checksum, calculation contract, and semantic versions as the equivalent separately admitted ordinary Factor Evaluation.
- [x] Stage events and Data I/O evidence prove one common Data, Universe, and Label preparation and one Alpha-and-Factor execution per submitted item without asserting private helper call counts.
- [x] A deterministic failure in one Alpha or Factor fails only that child Run, records a sanitized item-aware diagnostic, and allows later independent Factor items to continue.
- [x] Aggregate completion distinguishes all-success, mixed-success, and no-success outcomes without manufacturing a Batch-level Result.
- [x] A one-item Batch and a twenty-item Batch use the same execution contract and preserve deterministic item ordering.
- [x] Advancing the Dataset Head during execution cannot change the Generation used by any child Run.
- [x] Peak child RSS remains inside the existing execution budget for the accepted plan, including the widest admitted shared Data slice.
- [x] Ordinary Research Workers remain able to execute interactive non-Batch Runs while the Factor Batch is active.
- [x] The implementation adds no cross-Batch cache, parallel execution within one Batch, second kernel, second image, external queue, or frontend Batch UI.

## Comments

- Parent: Research Batch Worker.
- This is the first complete Batch execution tracer bullet; bounded recovery is added separately.
- Final Standards review: PASS, P0/P1/P2 = 0/0/0.
- Final Spec review: PASS, P0/P1/P2 = 0/0/0.
- Fast gate: Ruff plus 561 Kernel/Architecture/Adapter/Data tests passed.
- Widest-slice and PostgreSQL partial-cleanup gate: 2 acceptance tests passed
  against isolated PostgreSQL/RustFS.
- Isolated PostgreSQL/RustFS gate: run `20260823t230608z-99651-98d654e5`,
  204 integration/acceptance tests passed and one database-restart test passed;
  cleanup completed.
- Production Image smoke: run `20260823t231252z-7289-9c2e4de7` passed with
  the fixed batch-research Worker role, full lifecycle fault probes, and cleanup.
