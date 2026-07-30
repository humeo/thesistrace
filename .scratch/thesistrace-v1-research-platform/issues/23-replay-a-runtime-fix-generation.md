# 23 — Replay a runtime-fix Generation

**What to build:** Apply a result-changing calculation-kernel correction without
mixing versions inside one Tracking Generation or changing the DailyTrack's
research and numeric semantics.

**Blocked by:** 08 — Fix numeric execution and canonical serialization; 22 — Replay a corrected Tracking Generation.

**Status:** ready-for-agent

- [ ] Every Generation pins exactly one calculation-kernel semantic version and repeats the Track-pinned Numeric Execution Contract in its manifests.
- [ ] Compatible runtime build changes may continue one Generation only when they declare the same kernel and numeric semantics.
- [ ] A result-changing runtime fix creates a new predecessor-free Generation rooted at the current Head's target Release.
- [ ] The full replay uses the corrected kernel from Tracking Origin and records the superseded Generation and Head.
- [ ] Head moves atomically only after every new artifact and checksum succeeds.
- [ ] A changed research or Numeric Execution Contract is rejected as a Generation upgrade and requires a new ResearchRun and DailyTrack.
