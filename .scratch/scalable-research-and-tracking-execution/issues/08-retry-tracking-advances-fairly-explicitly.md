# 08 — Retry Tracking Advances fairly and explicitly

**What to build:** Recover transient DailyTrack failures through bounded, fair Attempt
Cycles while making deterministic failures require deliberate user action. Retry keeps
the same frozen Target, recomputes from the unchanged Head, and never monopolizes a
Tracking Worker or silently reactivates after data and deployment changes.

**Blocked by:** 07 — Advance DailyTrack with bounded Head-only Targets

**Status:** complete

- [x] One Tracking Attempt Cycle contains the initial Attempt plus at most two automatic Attempts.
- [x] Only unexpected Worker loss and transient PostgreSQL, RustFS, network, timeout, or Publication unavailability are automatically retryable.
- [x] The second Attempt becomes eligible after five seconds and the third after 30 seconds using deterministic persisted eligibility rather than a sleeping Worker.
- [x] Canonical Data, calculation, domain, accepted-capacity, integrity, equivalence, and other permanent failures block immediately.
- [x] Exhausting the transient Cycle blocks the persistent Advance and Track.
- [x] A failed Attempt discards unpublished work, releases its slot and Pin safely, and a later Attempt recomputes the complete frozen Target from the unchanged Head.
- [x] Every Attempt may pin the then-current Data Generation but must validate the same predecessor and exact frozen Target.
- [x] Only an explicit idempotent user Retry can reactivate the same Advance.
- [x] Retry reevaluates the frozen Target against current Tracking Worker Capacity without expanding or shrinking it.
- [x] If the Target still cannot fit, Retry leaves the Track blocked without creating a Cycle or Attempt.
- [x] If the Target fits, Retry starts a new bounded Cycle; Dataset Head movement, capacity change, service restart, and container restart never do so automatically.
- [x] Tracking Workers rotate eligible DailyTracks fairly: one Track receives at most one Attempt before other eligible Tracks, and a successful still-lagging Track returns to the tail.
- [x] A transiently failed Track releases the slot during retry waiting and rejoins the tail when eligible.
- [x] Separate Tracking Workers may own different Tracks, while claims and fences prevent concurrent Advances for the same Track.
- [x] Public progress shows Cycle Attempt position, retry-wait state, next eligibility, frozen Target, Head, lag, phase, and current session without marking uncommitted work complete.
- [x] Retry controls are available only for blocked work, replay the same outcome for the same request identifier, and reject conflicting request reuse.
- [x] Deterministic integration tests prove delay ordering, Cycle exhaustion, explicit reactivation, no automatic unblock, fair rotation, absence of starvation, and same-Track concurrency fencing.
- [x] Tests use fixed clocks, leases, barriers, and condition polling rather than arbitrary sleep or public network access.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 07.
- Verification: `pnpm test` passed (499 Python tests and 28 web tests).
- Verification: `./scripts/test-runtime integration` passed (178 integration tests plus the database-restart recovery test).
- Review: independent Spec and Standards reviews both passed after closing heartbeat-failure classification and capacity-blocked no-Cycle semantics.
