# 12 — Advance DailyTrack through finite Workflows

**What to build:** After each successful Dataset Release, advance every active
DailyTrack only across newly available Research Sessions through finite,
recoverable Temporal Workflows and publish one complete immutable Checkpoint per
accepted target Release.

**Blocked by:** 10 — Publish Datasets on the independent Data Worker; 11 — Activate and stop a quota-bound DailyTrack; `thesistrace-bounded-research-storage/05 — Advance DailyTrack from the bounded Working Cache`; `thesistrace-bounded-research-storage/07 — Rebuild invalid Working Caches within bounded windows`; `thesistrace-bounded-research-storage/08 — Fence concurrent Working Cache writers`; `thesistrace-v1-research-platform/26 — Continue DailyTrack through a Historical Correction Boundary`.

**Status:** resolved

- [x] A successful Dataset Release durably creates at most one Tracking Advance for each `(DailyTrack, Tracking Generation, target Dataset Release)` without waiting for that Advance to finish.
- [x] Each Tracking Advance uses one finite Workflow and bounded Activities rather than one permanent Workflow for the lifetime of a DailyTrack.
- [x] The Worker advances only new Research Sessions from the fenced Working Cache and publishes bounded Factor Summary Snapshots, retained Strategy deltas, and Terminal Strategy State.
- [x] Missing, corrupt, mismatched, or oversized Working Cache state is discarded and rebuilt only within the specified bounded windows before calculation continues.
- [x] Activity redelivery and two-Worker contention cannot publish duplicate Checkpoints or replace a cache whose authoritative basis has changed.
- [x] Tracking Advance follows the shared resource-exhaustion policy: the first exhausted Activity may retry once, a second ends with stable `RESOURCE_EXHAUSTED`, and Tracking Head remains at the prior Checkpoint.
- [x] An accepted historical correction creates an ordinary Correction Boundary in the same Tracking Generation and does not rewrite prior Checkpoints or replay all history.
- [x] Current and historical product views are bounded, Workspace-isolated, and expose no Pending Alpha, stock Label, raw order, fill, or cache payload.

## Comments

- Successful Dataset publication creates one idempotent outbox record per
  Workspace-scoped Advance. The Relay starts stable finite Temporal Workflow
  IDs and removes accepted Advance deliveries from the pending outbox.
- Ordinary calculation reads only intersecting Canonical partitions, processes
  at most 252 new sessions in 25-session chunks, and retains at most 252
  Strategy observations. A larger Advance fails before Canonical calculation
  with `TRACKING_ADVANCE_SESSION_LIMIT` and leaves Head and cache unchanged.
- Working Cache rebuild reads only the current Head plus the `504 + lookback`
  tail. Checkpoint publication, cache replacement, redelivery, and concurrent
  Workers share the authoritative fencing token.
- Correction fanout reads only the correction and origin Calendar
  neighborhoods and the affected Universe membership windows. It reuses a
  page-local cache and never materializes the complete Dataset Release.
- Product DTOs publish bounded current/history views and redact internal metric
  accumulators, cache payloads, stock Alpha/Label values, orders, and fills.
- Verification covered the full Python suite, Ruff, the Web production build,
  package build, real PostgreSQL Workspace/outbox behavior, resource
  exhaustion, multi-session catch-up, 253-session rejection, correction
  fanout, cache recovery, publication rollback, and two independent reviews.
