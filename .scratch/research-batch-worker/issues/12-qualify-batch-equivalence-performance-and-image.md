# 12 — Qualify Batch equivalence, performance, and the Production Image

**What to build:** Prove in the final Production Image that both Research Batch
Kinds are scientifically identical to equivalent serial ordinary Runs, actually
eliminate the intended repeated work, finish faster within the Worker resource
budget, and remain correct through restart, cancellation, and cleanup.

**Blocked by:** 10 — Preserve ordinary Run organization and granular deletion; 11 — Cancel a Research Batch after confirmed child exit

**Status:** ready-for-agent

- [ ] One reproducible final-image journey admits and executes both Batch Kinds through real HTTP, PostgreSQL, RustFS, Batch Research Worker, supervised child, Publication, restart, cancellation, and cleanup boundaries.
- [ ] Factor Batch and serial Factor baselines use the same frozen Data Generation, common research scope, ordered Alpha inputs, image identity, and single-slot resource envelope.
- [ ] Strategy Sweep and serial Strategy baselines use the same frozen Data Generation, shared Alpha, ordered parameter tuples, image identity, and single-slot resource envelope.
- [ ] Every Batch child and corresponding serial Run have exact calculation-payload and semantic-result checksums, equal calculation contracts and semantic versions, and their own correct ResearchRun provenance identity.
- [ ] Factor evidence proves one common Data, Universe, and Label preparation plus one independent Alpha-and-Factor execution per item.
- [ ] Strategy evidence proves one Data preparation, one Alpha execution, one Factor execution, and exactly one Strategy execution per parameter item.
- [ ] Representative multi-item Factor Batch and Strategy Sweep elapsed times are each lower than their strictly serial ordinary-Run baselines; queue waiting is reported separately.
- [ ] Peak child RSS stays within the configured execution budget, and evidence records phase timing, Data I/O, item count, object bytes, cleanup, and resource peaks.
- [ ] Repeated deterministic execution produces identical calculation Results and stable task ordering rather than relying on one favorable sample.
- [ ] Independent correctness checks cover Formula negation, Holdings Count and Rebalance Sessions sensitivity, finite values, NAV and drawdown validity, Factor Coverage, and independent Result recomputation.
- [ ] Advancing the Dataset Head during execution and retry leaves every child bound to the admitted Generation and cannot collect that Generation before terminal cleanup.
- [ ] Production evidence includes image identity, structured Worker events, request and response records, exit codes, Attempts, task acknowledgements, fences, timing, RSS, object references, Result checksums, and Product State before and after cleanup.
- [ ] Failure diagnostics use fixed clocks, UUID sources, random seeds, formulas, parameter sets, and bounded condition polling and retain enough state to locate timeouts without rerunning a failure into a pass.
- [ ] The final gate covers multi-replica FIFO claims, bounded retry, child and Worker loss, private-artifact reuse and rejection, queued and running cancellation, granular Run deletion, DailyTrack retention, restart, and durable garbage-collection retry.
- [ ] Current operational documentation exposes only the three fixed Worker roles and one current Batch contract; obsolete two-pool descriptions, fallback paths, compatibility aliases, and alternate schema or executor descriptions are removed.
- [ ] No Batch frontend, external scheduler, cross-Batch cache, parallel in-Batch execution, Batch-level Result, automatic best-parameter selection, migration path, or compatibility implementation ships in V1.
- [ ] The feature is complete only when every preceding ticket's focused gates, the complete real-dependency acceptance suite, and this final Production Image gate pass together.

## Comments

- Parent: Research Batch Worker.
- A timing improvement alone does not pass; semantic equivalence, intended stage sharing, recovery, memory, and cleanup evidence are all required.
