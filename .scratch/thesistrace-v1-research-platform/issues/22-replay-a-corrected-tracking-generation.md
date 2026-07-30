# 22 — Replay a corrected Tracking Generation

**What to build:** When a new Release correction intersects an active Track's
dependency closure, fully replay a new immutable Generation from the fixed
Origin and move Head only after complete success.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 20 — Mature Labels and publish Factor summaries; 21 — Manage Tracking frontiers, retries, and catch-up.

**Status:** resolved

- [x] Release correction change-sets deterministically identify whether Alpha, Universe, Label, Benchmark, execution, or accounting dependencies intersect the Track.
- [x] Replay resolves the complete Origin-to-target closure from the corrected cumulative Release and never uses old seed or Checkpoint state as calculation input.
- [x] The new Generation root has no predecessor and records Origin, corrected basis Release, superseded Generation, and superseded Head.
- [x] Checkpoints, maturation events, summaries, and other provenance-bearing artifacts are republished under the new Generation.
- [x] Only generation-and-release-neutral content payloads may be reused by hash.
- [x] Failure leaves the old Head readable and marks the Track behind or blocked.
- [x] Success atomically moves Head while every prior as-known Generation remains queryable and immutable.

## Comments

- A correction-bearing canonical price change-set creates a predecessor-free
  Generation and replays the corrected cumulative Release from the fixed
  Tracking Origin.
- Generation-bearing manifests and maturations are republished; old Head and
  old Generation stay readable until the new root succeeds atomically.
- Historical note: ADR-0144 supersedes this issue for historical data
  corrections. A correction now creates a visible Tracking Correction Boundary
  in the same Generation and continues from committed state; only a
  result-changing calculation-kernel correction may rebuild a Generation.
