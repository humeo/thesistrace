# 23 — Contract DailyTrack Release-coordinate compatibility

**What to build:** Remove DailyTrack's application, codec, and runtime
dependence on Release identifiers and predecessor traversal once every active
tracking behavior uses session coordinates and attempt-scoped Generations.

**Blocked by:** 18 — Recover DailyTrack without duplicate or partial history; 19 — Keep DailyTrack forward-only across overlap corrections; 20 — Collect retired Data Generations safely.

**Status:** complete

- [x] Active Tracking Origin, progression, Attempt, Checkpoint, Working Cache, detail, retry, stop, and equivalence paths no longer read or write Release identifiers or predecessor chains.
- [x] Tracking progress is expressed by the last successful Checkpoint session and current Head session frontier; Generation identity remains internal Attempt pin and provenance metadata only.
- [x] Activation reconstructs from the seed Result's Terminal Strategy State, and cache rebuild uses the latest authoritative Checkpoint plus current Canonical Data without needing the seed Release or a collected Generation.
- [x] Release history, Release links, and Generation browsing are absent from every DailyTrack public response and rendered projection.
- [x] Checkpoint and Result publication continue to reject the transient Strategy Ledger, raw Alpha and Label values, orders, fills, and position history.
- [x] Normal catch-up, failure recovery, Stop, Active DailyTrack Limit, working-cache rebuild, forward-only corrections, and Run/Advance equivalence all remain green after the application contract is removed.
- [x] This ticket leaves isolated legacy physical rows and tables untouched; their guarded destructive removal belongs exclusively to the final permanent Dataset Release contract after Development Reset is available.

## Comments

- Implemented by `d841f0c`, `210788d`, and `2eea2cb` from base `f60915d`.
- TDD covered the session-coordinate migration/backfill, public Retry, activation capacity, live-owner fencing, working-cache invalidation, and checkpoint recovery at their real PostgreSQL/Worker or filesystem seams.
- Focused verification: session-coordinate persistence (12 passed), working cache (7 passed), architecture boundary (31 passed), plus the real acceptance cases for capacity, heartbeat ownership, Retry, and recovery.
- Spec review and Standards review both completed with no remaining material findings.
