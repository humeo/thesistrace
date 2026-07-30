# 09 — Reconcile Working Cache deletion after DailyTrack stop

**What to build:** Let a research author stop Daily Tracking permanently while
preserving its immutable Head and history, and guarantee that its rebuildable
Working Cache is eventually deleted even if the stopping process crashes.

**Blocked by:** 08 — Fence concurrent Working Cache writers.

**Status:** resolved

- [x] Stopping a DailyTrack first advances its authoritative fencing state, then atomically records terminal `stopped` status and a durable idempotent cache-deletion request.
- [x] An in-flight or delayed Worker cannot publish a later Checkpoint, replace or delete a newer cache, or recreate a cache namespace after the stop boundary.
- [x] A stopped Track cannot resume in V1, immediately stops receiving Advances and automatic retries, and no longer consumes an Active DailyTrack admission slot.
- [x] Successful cleanup removes the complete Working Cache namespace without deleting or modifying the Track's Head, Checkpoints, Generations, Result Bundle, or visible history.
- [x] If execution crashes after the `stopped` commit but before deletion, startup and scheduled reconciliation eventually remove the orphan namespace and complete the deletion request idempotently.
- [x] Reconciliation also deletes namespaces whose DailyTrack is absent or no longer active and never creates cache state while inspecting or cleaning them.
- [x] Repeated stop, cleanup, and reconciliation delivery is harmless and leaves one terminal Track with no committed Working Cache.
- [x] Public API and Web state show the Track as stopped and preserve its final Head while cache-cleanup failures remain operational diagnostics rather than restored product activity.

## Comments

- Stop now increments the authoritative Track fencing token and atomically
  records terminal status, cancels running Attempts, blocks their Advance, and
  upserts one durable idempotent `working_cache_deletions` request.
- The shared WorkingCacheStore persists a per-Track fencing tombstone. Fence
  updates and final cache installation/deletion serialize on a Track lock, so
  once stop's higher token is installed an older Worker cannot replace,
  delete, or recreate the namespace.
- Cleanup removes only the rebuildable `tracks/<id>` namespace. The permanent
  tiny fence tombstone and immutable Result, Head, Checkpoints, Generations,
  Strategy history, and current view remain intact.
- Stop attempts cleanup immediately without turning a volume failure back into
  product activity. Pending status, attempt count, and last error are exposed
  as operational `cache_deletion` state on the Track.
- App startup and every Worker loop reconcile pending requests. The reconciler
  also deletes unknown and non-active cache namespaces and never constructs
  cache content while inspecting them.
- Acceptance covers normal and repeated stop, durable cleanup failure followed
  by startup recovery, an in-flight token-2 Worker fenced by stop token 3, and
  unknown partial namespace cleanup.
- Verification: all Tracking acceptance `14 passed`; full backend suite `65
  passed`; `uv run ruff check src tests`; `bun run typecheck`; and `bun run
  build`.
