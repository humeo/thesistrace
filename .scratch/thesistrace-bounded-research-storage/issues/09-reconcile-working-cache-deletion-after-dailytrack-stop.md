# 09 — Reconcile Working Cache deletion after DailyTrack stop

**What to build:** Let a research author stop Daily Tracking permanently while
preserving its immutable Head and history, and guarantee that its rebuildable
Working Cache is eventually deleted even if the stopping process crashes.

**Blocked by:** 08 — Fence concurrent Working Cache writers.

**Status:** ready-for-agent

- [ ] Stopping a DailyTrack first advances its authoritative fencing state, then atomically records terminal `stopped` status and a durable idempotent cache-deletion request.
- [ ] An in-flight or delayed Worker cannot publish a later Checkpoint, replace or delete a newer cache, or recreate a cache namespace after the stop boundary.
- [ ] A stopped Track cannot resume in V1, immediately stops receiving Advances and automatic retries, and no longer consumes an Active DailyTrack admission slot.
- [ ] Successful cleanup removes the complete Working Cache namespace without deleting or modifying the Track's Head, Checkpoints, Generations, Result Bundle, or visible history.
- [ ] If execution crashes after the `stopped` commit but before deletion, startup and scheduled reconciliation eventually remove the orphan namespace and complete the deletion request idempotently.
- [ ] Reconciliation also deletes namespaces whose DailyTrack is absent or no longer active and never creates cache state while inspecting or cleaning them.
- [ ] Repeated stop, cleanup, and reconciliation delivery is harmless and leaves one terminal Track with no committed Working Cache.
- [ ] Public API and Web state show the Track as stopped and preserve its final Head while cache-cleanup failures remain operational diagnostics rather than restored product activity.
