# 22 — Replay a corrected Tracking Generation

**What to build:** When a new Release correction intersects an active Track's
dependency closure, fully replay a new immutable Generation from the fixed
Origin and move Head only after complete success.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 20 — Mature Labels and publish Factor summaries; 21 — Manage Tracking frontiers, retries, and catch-up.

**Status:** ready-for-agent

- [ ] Release correction change-sets deterministically identify whether Alpha, Universe, Label, Benchmark, execution, or accounting dependencies intersect the Track.
- [ ] Replay resolves the complete Origin-to-target closure from the corrected cumulative Release and never uses old seed or Checkpoint state as calculation input.
- [ ] The new Generation root has no predecessor and records Origin, corrected basis Release, superseded Generation, and superseded Head.
- [ ] Checkpoints, maturation events, summaries, and other provenance-bearing artifacts are republished under the new Generation.
- [ ] Only generation-and-release-neutral content payloads may be reused by hash.
- [ ] Failure leaves the old Head readable and marks the Track behind or blocked.
- [ ] Success atomically moves Head while every prior as-known Generation remains queryable and immutable.
