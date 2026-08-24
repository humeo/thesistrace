# 12 — Qualify Batch equivalence, performance, and the Production Image

**What to build:** Prove in the final Production Image that both Research Batch
Kinds are scientifically identical to equivalent serial ordinary Runs, actually
eliminate the intended repeated work, finish faster within the Worker resource
budget, and remain correct through restart, cancellation, and cleanup.

**Blocked by:** 10 — Preserve ordinary Run organization and granular deletion; 11 — Cancel a Research Batch after confirmed child exit

**Status:** complete

## Implementation plan

1. Inventory the existing final-image smoke, benchmark, Result checksum,
   Worker-event, Product State, and cleanup evidence contracts; keep one
   canonical qualification path rather than adding a parallel harness.
2. Add deterministic Batch-versus-serial HTTP journeys for both Batch Kinds,
   with exact calculation/semantic checksum and provenance comparison,
   independent correctness checks, shared-stage/task-order evidence, repeated
   execution, timing, object bytes, and peak child RSS.
3. Extend the Production Image orchestration to enforce a single Research and
   Batch Worker slot, capture image/request/response/Worker/Attempt/fence and
   cleanup evidence, and exercise restart/cancellation without arbitrary waits.
4. Remove stale operational descriptions so documentation exposes exactly the
   three current Worker roles and one V1 Batch contract, with no frontend,
   scheduler, cache, compatibility, or migration path.
5. Run the complete focused, real-dependency, frontend, Production Image, and
   benchmark gates; close independent Standards and Spec review findings, mark
   the tracker complete, and commit this ticket separately.

- [x] One reproducible final-image journey admits and executes both Batch Kinds through real HTTP, PostgreSQL, RustFS, Batch Research Worker, supervised child, Publication, restart, cancellation, and cleanup boundaries.
- [x] Factor Batch and serial Factor baselines use the same frozen Data Generation, common research scope, ordered Alpha inputs, image identity, and single-slot resource envelope.
- [x] Strategy Sweep and serial Strategy baselines use the same frozen Data Generation, shared Alpha, ordered parameter tuples, image identity, and single-slot resource envelope.
- [x] Every Batch child and corresponding serial Run have exact calculation-payload and semantic-result checksums, equal calculation contracts and semantic versions, and their own correct ResearchRun provenance identity.
- [x] Factor evidence proves one common Data, Universe, and Label preparation plus one independent Alpha-and-Factor execution per item.
- [x] Strategy evidence proves one Data preparation, one Alpha execution, one Factor execution, and exactly one Strategy execution per parameter item.
- [x] Representative multi-item Factor Batch and Strategy Sweep elapsed times are each lower than their strictly serial ordinary-Run baselines; queue waiting is reported separately.
- [x] Peak child RSS stays within the configured execution budget, and evidence records phase timing, Data I/O, item count, object bytes, cleanup, and resource peaks.
- [x] Repeated deterministic execution produces identical calculation Results and stable task ordering rather than relying on one favorable sample.
- [x] Independent correctness checks cover Formula negation, Holdings Count and Rebalance Sessions sensitivity, finite values, NAV and drawdown validity, Factor Coverage, and independent Result recomputation.
- [x] Advancing the Dataset Head during execution and retry leaves every child bound to the admitted Generation and cannot collect that Generation before terminal cleanup.
- [x] Production evidence includes image identity, structured Worker events, request and response records, exit codes, Attempts, task acknowledgements, fences, timing, RSS, object references, Result checksums, and Product State before and after cleanup.
- [x] Failure diagnostics use a fixed calendar, request IDs, formulas and parameter sets, no random source, bounded condition polling, and full records of real Production Image timestamps and UUIDs; semantic comparisons exclude those dynamic fields and retain enough state to locate timeouts without rerunning a failure into a pass.
- [x] The final gate covers multi-replica FIFO claims, bounded retry, child and Worker loss, private-artifact reuse and rejection, queued and running cancellation, granular Run deletion, DailyTrack retention, restart, and durable garbage-collection retry.
- [x] Current operational documentation exposes only the three fixed Worker roles and one current Batch contract; obsolete two-pool descriptions, fallback paths, compatibility aliases, and alternate schema or executor descriptions are removed.
- [x] No Batch frontend, external scheduler, cross-Batch cache, parallel in-Batch execution, Batch-level Result, automatic best-parameter selection, migration path, or compatibility implementation ships in V1.
- [x] The feature is complete only when every preceding ticket's focused gates, the complete real-dependency acceptance suite, and this final Production Image gate pass together.

## Comments

- Parent: Research Batch Worker.
- A timing improvement alone does not pass; semantic equivalence, intended stage sharing, recovery, memory, and cleanup evidence are all required.
- The original five-minute warm-P95 gate stayed unchanged. After optimizing exact Decimal-to-binary64 columnar materialization, long qualification run `20260824t163057z-11326-ce25b353` passed with Factor/Strategy warm P95 `233515.103/251503.579 ms`, peak RSS `678699008/694370304` bytes, and 20 deterministic samples.
- Final Production Image run `20260824t182417z-54309-82195d31` passed with cleanup `0`. Across one warmup and four measured samples, Factor Batch/serial medians were `0.3697505/2.430352 s` and Strategy Batch/serial medians were `0.8616365/3.2233605 s`; qualification peak RSS was `144130048` bytes.
- The final 30-instrument deterministic fixture produced non-zero IC, Rank IC, and quantile coverage at every 1/5/20-session horizon (`41/37/22` valid sessions), exact Formula-negation relationships, and distinct stable Factor and Strategy semantic checksums.
- Complete real-dependency integration run `20260824t173844z-29191-68795d84`, final E2E run `20260824t183357z-59314-f2c75091`, Python `563`, and frontend `57` tests all passed with cleanup `0` where applicable.
- Independent final Standards and Spec reviews both passed with `P0/P1/P2 = 0/0/0` after the non-degenerate Factor Coverage finding was fixed and re-reviewed.
