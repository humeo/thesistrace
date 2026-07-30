# 19 — Advance a DailyTrack by Research Session

**What to build:** Continue an active Track through each newly published
Research Session using the same Alpha and Strategy kernel as batch research and
publish one immutable Checkpoint per successful Advance.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 14 — Handle suspension, delisting, and Strategy Benchmark; 18 — Activate a DailyTrack.

**Status:** ready-for-agent

- [ ] Each Advance identity is the unique Track, Generation, and target Release tuple.
- [ ] Every new Research Session executes pending work at Open before producing the close Alpha and next scheduled signal.
- [ ] The original all-cash baseline, rebalance phase, account, Benchmark, and cumulative costs never re-anchor to a rolling Research Window.
- [ ] Active tracking has no moving finite-run terminal cutoff.
- [ ] A successful Advance atomically publishes a Checkpoint binding its same-Generation predecessor, target Release, processed sessions, versions, events, state, objects, and checksums.
- [ ] Head moves only after complete success; failure leaves the prior Head and Dataset Release unchanged.
- [ ] Repeated successful delivery returns the existing Advance and Checkpoint without duplicating events.
