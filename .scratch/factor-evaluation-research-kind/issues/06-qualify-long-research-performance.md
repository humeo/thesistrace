# 06 — Qualify long Research performance for both kinds

**What to build:** Establish a repeatable final-image performance gate showing that
Factor Evaluation and Strategy Backtest both support the complete 2010-to-latest,
Top 3000 research journey within the declared single-Worker resource envelope.

**Blocked by:** 05 — Verify the current-schema Production Image journey

**Status:** complete

## Plan

1. Replace the single-kind qualification evidence in place with one current
   dual-kind contract: Factor Evaluation and Strategy Backtest use the same
   frozen 2010-to-latest Top 3000 workload, final image, fixed 2C/2GiB
   single-slot Worker envelope, deterministic percentile rule, and threshold
   definitions.
2. Parameterize the existing qualification runner by immutable Research Kind;
   reset and prove empty Product State before every cold sample, every warm
   sample, and each cancellation sample, while preserving the exact Canonical
   Generation and using one Canonical-only preload for warm reads.
3. Capture per-Chunk phase timings, peak RSS, first durable Checkpoint,
   cumulative Canonical I/O, child exit, exact Result object set, and canonical
   Factor Summary identity from the real supervised child and Publication
   boundaries. Make Factor evidence fail if any Strategy phase, continuation,
   observation partition, or Result object appears.
4. Qualify each kind independently with five cold and five warm fresh Runs and
   one confirmed cancellation, then enforce the warm/cold P95, memory,
   first-Checkpoint, cancellation, cleanup, and exact cross-kind Factor Summary
   equivalence gates without retrying a failed sample into a pass.
5. Update focused deterministic report tests and the one existing
   `pnpm benchmark:long-research` final-image command; run focused gates and the
   complete qualification, then complete independent Standards and Spec
   reviews, fix and re-review every material finding, mark the ticket complete,
   and create one Ticket 06 commit.

- [x] The reference workload for each Research Kind covers 2010 through the latest covered Research Session, uses Top 3000, and is pinned to one frozen Data Generation.
- [x] Qualification runs in the final Production Image with one Research Worker execution slot, 2 vCPU, 2 GiB cgroup memory, at most two calculation threads, and a 1.5-GiB execution budget.
- [x] Each Research Kind is measured with five cold and five warm fresh ResearchRuns using fresh Product State for every sample.
- [x] Warm preload reads only the same immutable Canonical Data objects and never reuses a prior Run, Attempt, Checkpoint, Result, Publication object, or other Product State.
- [x] Cold and warm measurements include admission, data reads, applicable calculation phases, Chunk Checkpoints, finalization, and atomic Result publication while excluding queue waiting.
- [x] Factor Evaluation warm P95 is at most five minutes and cold P95 is at most ten minutes under the declared reference workload.
- [x] Strategy Backtest warm P95 is at most five minutes and cold P95 is at most ten minutes under the declared reference workload.
- [x] Every sample stays within the 1.5-GiB execution budget, produces its first durable Checkpoint within 45 seconds, and retains confirmed cooperative cancellation within five seconds for a healthy owner.
- [x] Factor Evaluation evidence contains no Strategy phase work, Strategy continuation, Strategy observation partitions, or Strategy Result objects.
- [x] Strategy Backtest evidence retains the complete current Alpha, Factor, Strategy, Result, and terminal-state journey.
- [x] Qualification reports deterministic nearest-rank duration percentiles, per-phase timings, peak RSS, first-Checkpoint latency, cancellation latency, Result manifests, child exits, and cleanup evidence for both kinds.
- [x] A performance or scientific-equivalence regression fails the gate; rerunning a failed sample is diagnostic evidence and does not convert the failure into a pass.

## Verification

- `pnpm test`: 525 Python tests and 37 Browser shell tests passed.
- `pnpm test:benchmark`: run `20260819t214507z-39121-18c214ae` passed in the
  final Production Image with cleanup status 0.
- Factor Evaluation cold/warm P95: 128721.083 / 122981.938 ms; peak RSS:
  716709888 bytes; first durable Checkpoint: 1984.673 ms; cancellation:
  420.873 ms.
- Strategy Backtest cold/warm P95: 155861.43 / 149478.029 ms; peak RSS:
  735514624 bytes; first durable Checkpoint: 2245.387 ms; cancellation:
  425.863 ms.
- All 20 fresh samples produced the same Factor Summary SHA-256
  `331264d99131736a561859ad989ad2ddfae81956008ce9ec31d441a81b4ca9d6`.
- Independent Standards and Spec reviews both passed after material findings
  were fixed and re-reviewed.
