# 09 — Confirm DailyTrack Stop and reclaim Working Cache

**What to build:** Make DailyTrack Stop a confirmed termination operation. A running
Track remains `stopping` until its execution child exits and can no longer publish;
idle or blocked work stops atomically, retry state cannot resurrect it, disposable
Working Cache is reclaimed, and authoritative history remains until deletion.

**Blocked by:** 08 — Retry Tracking Advances fairly and explicitly

**Status:** ready-for-agent

- [ ] DailyTrack lifecycle exposes `active`, `blocked`, `stopping`, and `stopped`, with `stopping` non-terminal.
- [ ] Stopping a Track with a running Attempt atomically moves the Track, Advance, and Attempt to `stopping`, advances the fence, and signals the owning Tracking Worker supervisor.
- [ ] The supervisor requests cooperative child shutdown and escalates to termination when the grace interval expires.
- [ ] While the supervisor remains healthy, child exit confirmation, Pin release, and terminal persistence complete within one five-second total budget.
- [ ] Track `stopped`, Attempt and Advance `cancelled`, and Pin release occur only after the child is confirmed exited.
- [ ] A stopped or stale child has no authority to publish a Tracking Checkpoint or move the Head.
- [ ] When the supervisor, container, or host is lost, durable Stop intent survives and replacement recovery waits until the old lease and ownership cannot remain live, even when that exceeds five seconds.
- [ ] Stopping an active Track with no running Attempt or a blocked Track completes immediately in one transaction.
- [ ] Immediate Stop cancels the unresolved Advance, current Attempt Cycle, retry eligibility, and every pending claim so no Worker can start later work.
- [ ] Stop is irreversible, never creates another Attempt, and is idempotent for repeated request identifiers.
- [ ] A `stopping` Track cannot Retry, Delete, or Advance and continues to count toward the limit of ten non-stopped DailyTracks.
- [ ] Concurrent activation enforces the ten-Track limit transactionally across `active`, `blocked`, and `stopping` Tracks.
- [ ] Reaching `stopped` deletes the disposable Working Cache while preserving authoritative Tracking Head and Checkpoints until explicit DailyTrack Deletion.
- [ ] Public and browser views distinguish `stopping` from `stopped` and do not expose optimistic terminal status.
- [ ] Process and integration tests cover cooperative Stop, forced termination, stale publication, no-child Stop, blocked Stop, retry-wait Stop, lost-supervisor recovery, cache deletion, and activation races.
- [ ] The previous immediate terminal Stop behavior and any cache-as-recovery path are deleted.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 08.
