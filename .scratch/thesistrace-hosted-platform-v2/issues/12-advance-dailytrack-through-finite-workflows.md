# 12 — Advance DailyTrack through finite Workflows

**What to build:** After each successful Dataset Release, advance every active
DailyTrack only across newly available Research Sessions through finite,
recoverable Temporal Workflows and publish one complete immutable Checkpoint per
accepted target Release.

**Blocked by:** 10 — Publish Datasets on the independent Data Worker; 11 — Activate and stop a quota-bound DailyTrack; `thesistrace-bounded-research-storage/05 — Advance DailyTrack from the bounded Working Cache`; `thesistrace-bounded-research-storage/07 — Rebuild invalid Working Caches within bounded windows`; `thesistrace-bounded-research-storage/08 — Fence concurrent Working Cache writers`; `thesistrace-v1-research-platform/26 — Continue DailyTrack through a Historical Correction Boundary`.

**Status:** ready-for-agent

- [ ] A successful Dataset Release durably creates at most one Tracking Advance for each `(DailyTrack, Tracking Generation, target Dataset Release)` without waiting for that Advance to finish.
- [ ] Each Tracking Advance uses one finite Workflow and bounded Activities rather than one permanent Workflow for the lifetime of a DailyTrack.
- [ ] The Worker advances only new Research Sessions from the fenced Working Cache and publishes bounded Factor Summary Snapshots, retained Strategy deltas, and Terminal Strategy State.
- [ ] Missing, corrupt, mismatched, or oversized Working Cache state is discarded and rebuilt only within the specified bounded windows before calculation continues.
- [ ] Activity redelivery and two-Worker contention cannot publish duplicate Checkpoints or replace a cache whose authoritative basis has changed.
- [ ] Tracking Advance follows the shared resource-exhaustion policy: the first exhausted Activity may retry once, a second ends with stable `RESOURCE_EXHAUSTED`, and Tracking Head remains at the prior Checkpoint.
- [ ] An accepted historical correction creates an ordinary Correction Boundary in the same Tracking Generation and does not rewrite prior Checkpoints or replay all history.
- [ ] Current and historical product views are bounded, Workspace-isolated, and expose no Pending Alpha, stock Label, raw order, fill, or cache payload.
