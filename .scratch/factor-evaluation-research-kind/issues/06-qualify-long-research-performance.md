# 06 — Qualify long Research performance for both kinds

**What to build:** Establish a repeatable final-image performance gate showing that
Factor Evaluation and Strategy Backtest both support the complete 2010-to-latest,
Top 3000 research journey within the declared single-Worker resource envelope.

**Blocked by:** 05 — Verify the current-schema Production Image journey

**Status:** ready-for-agent

- [ ] The reference workload for each Research Kind covers 2010 through the latest covered Research Session, uses Top 3000, and is pinned to one frozen Data Generation.
- [ ] Qualification runs in the final Production Image with one Research Worker execution slot, 2 vCPU, 2 GiB cgroup memory, at most two calculation threads, and a 1.5-GiB execution budget.
- [ ] Each Research Kind is measured with five cold and five warm fresh ResearchRuns using fresh Product State for every sample.
- [ ] Warm preload reads only the same immutable Canonical Data objects and never reuses a prior Run, Attempt, Checkpoint, Result, Publication object, or other Product State.
- [ ] Cold and warm measurements include admission, data reads, applicable calculation phases, Chunk Checkpoints, finalization, and atomic Result publication while excluding queue waiting.
- [ ] Factor Evaluation warm P95 is at most five minutes and cold P95 is at most ten minutes under the declared reference workload.
- [ ] Strategy Backtest warm P95 is at most five minutes and cold P95 is at most ten minutes under the declared reference workload.
- [ ] Every sample stays within the 1.5-GiB execution budget, produces its first durable Checkpoint within 45 seconds, and retains confirmed cooperative cancellation within five seconds for a healthy owner.
- [ ] Factor Evaluation evidence contains no Strategy phase work, Strategy continuation, Strategy observation partitions, or Strategy Result objects.
- [ ] Strategy Backtest evidence retains the complete current Alpha, Factor, Strategy, Result, and terminal-state journey.
- [ ] Qualification reports deterministic nearest-rank duration percentiles, per-phase timings, peak RSS, first-Checkpoint latency, cancellation latency, Result manifests, child exits, and cleanup evidence for both kinds.
- [ ] A performance or scientific-equivalence regression fails the gate; rerunning a failed sample is diagnostic evidence and does not convert the failure into a pass.
