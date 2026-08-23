# 04 — Execute Factor Evaluation Batches with shared preparation

**What to build:** Let the dedicated Batch Research Worker execute an admitted
Factor Evaluation Batch in request order, preparing the common research data
once while publishing one ordinary, scientifically equivalent Factor Result per
submitted Alpha.

**Blocked by:** 01 — Extract a reusable Alpha-and-Factor execution outcome; 03 — Admit and inspect Research Batches atomically

**Status:** ready-for-agent

- [ ] A fixed batch-research Worker role can claim one complete Factor Evaluation Batch and execute it through the same executable, Production Image, Research Kernel, supervised child model, and Publication system as ordinary Research.
- [ ] The Batch builds one canonical Data slice from the union of required field bindings and maximum effective lookback and resolves the common Liquidity Universe and Forward Return Labels once.
- [ ] Each submitted Alpha uses its own compiled plan and completes one independent Alpha-and-Factor calculation; values from different Alphas are never blended or inferred as one model.
- [ ] Items execute sequentially in submitted ordinal order, and item-local working state is released after its complete task has been validated and acknowledged.
- [ ] Every successful item publishes an ordinary Factor Evaluation Result containing only its Factor Summary and its own correct ResearchRun identity and provenance.
- [ ] Against the same frozen Generation, each Batch item has the exact semantic Result checksum, calculation contract, and semantic versions as the equivalent separately admitted ordinary Factor Evaluation.
- [ ] Stage events and Data I/O evidence prove one common Data, Universe, and Label preparation and one Alpha-and-Factor execution per submitted item without asserting private helper call counts.
- [ ] A deterministic failure in one Alpha or Factor fails only that child Run, records a sanitized item-aware diagnostic, and allows later independent Factor items to continue.
- [ ] Aggregate completion distinguishes all-success, mixed-success, and no-success outcomes without manufacturing a Batch-level Result.
- [ ] A one-item Batch and a twenty-item Batch use the same execution contract and preserve deterministic item ordering.
- [ ] Advancing the Dataset Head during execution cannot change the Generation used by any child Run.
- [ ] Peak child RSS remains inside the existing execution budget for the accepted plan, including the widest admitted shared Data slice.
- [ ] Ordinary Research Workers remain able to execute interactive non-Batch Runs while the Factor Batch is active.
- [ ] The implementation adds no cross-Batch cache, parallel execution within one Batch, second kernel, second image, external queue, or frontend Batch UI.

## Comments

- Parent: Research Batch Worker.
- This is the first complete Batch execution tracer bullet; bounded recovery is added separately.
