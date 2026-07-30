# 19 — Advance a DailyTrack by Research Session

**What to build:** Continue an active Track through each newly published
Research Session using the same Alpha and Strategy kernel as batch research and
publish one immutable Checkpoint per successful Advance.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 14 — Handle suspension, delisting, and Strategy Benchmark; 18 — Activate a DailyTrack.

**Status:** resolved

- [x] Each Advance identity is the unique Track, Generation, and target Release tuple.
- [x] Every new Research Session executes pending work at Open before producing the close Alpha and next scheduled signal.
- [x] The original all-cash baseline, rebalance phase, account, Benchmark, and cumulative costs never re-anchor to a rolling Research Window.
- [x] Active tracking has no moving finite-run terminal cutoff.
- [x] A successful Advance atomically publishes a Checkpoint binding its same-Generation predecessor, target Release, processed sessions, versions, events, state, objects, and checksums.
- [x] Head moves only after complete success; failure leaves the prior Head and Dataset Release unchanged.
- [x] Repeated successful delivery returns the existing Advance and Checkpoint without duplicating events.

## Comments

- Strategy execution now continues from the prior immutable account result,
  while Alpha appends only new sessions from a bounded complete lookback.
- One successful Advance publishes one immutable Checkpoint and atomically moves
  Head; duplicate execution returns the same successful identity.
