# 07 — Advance DailyTrack with bounded Head-only Targets

**What to build:** Advance a DailyTrack through one bounded, frozen Target while keeping
the authoritative Tracking Head as the only recovery truth. A Tracking Worker uses one
supervised child and one stable current Data Generation per Attempt, then either
atomically publishes the whole Target or discards every unpublished value.

**Blocked by:** 06 — Resume long Research across bounded Attempts

**Status:** ready-for-agent

- [ ] Advance creation freezes the exact contiguous oldest unpublished Target using the then-current Data Generation and declared Tracking Worker Capacity.
- [ ] The planner selects the largest Target from 1 through 63 sessions that fits the 75-percent memory budget and is estimated within the 30-second sizing target.
- [ ] When one session fits memory but exceeds the time target, the Advance freezes that one session.
- [ ] When the oldest one session cannot fit memory, the system creates a blocked one-session Advance and no Attempt.
- [ ] The frozen Target never expands or shrinks; Dataset Head growth is handled only by a later Advance after success.
- [ ] A Tracking Attempt is created only when a Tracking Worker claims eligible execution and starts exactly one child.
- [ ] The supervisor exclusively owns claim, lease, fence, Data Generation Pin, Working Cache mutation, Tracking Checkpoint, and Publication authority.
- [ ] The child reads only the pinned mounted Data Generation, has no PostgreSQL or RustFS write authority, and returns one bounded all-or-nothing Target result.
- [ ] Each Attempt resolves the current Data Generation exactly once and uses it for the complete Target.
- [ ] The Generation must contain the frozen predecessor and exact ordered Target; predecessor or calendar mismatch blocks as a permanent integrity failure.
- [ ] Success atomically publishes one immutable Tracking Checkpoint and moves the Tracking Head to the Target boundary.
- [ ] Failure, recovered ownership loss, or cancellation discards every unpublished value, leaves the Head unchanged, and releases the Pin only after child ownership is dead.
- [ ] Tracking creates no private cross-Attempt execution Checkpoint and Working Cache never becomes recovery truth.
- [ ] A later eligible Attempt can recompute the same Target from the unchanged Head using its own then-current Generation without rewriting published history or mixing Generations.
- [ ] Tracking Progress exposes authoritative Head and lag, frozen Target, transient phase, and current session; only successful publication marks sessions complete.
- [ ] Batch Research and incremental Tracking remain canonically exact for the same Origin, contracts, ordered sessions, and Canonical inputs.
- [ ] API, persistence, process, and browser tests cover successful one- and 63-session Targets, one-session capacity block, Head atomicity, prepared-output discard, Generation mismatch, and restart recovery.
- [ ] The previous whole-backlog or one-session-at-a-time implicit progression path is removed rather than retained as a fallback.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 06.
