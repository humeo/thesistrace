# 23 — Contract DailyTrack Release-coordinate compatibility

**What to build:** Remove DailyTrack's application, codec, and runtime
dependence on Release identifiers and predecessor traversal once every active
tracking behavior uses session coordinates and attempt-scoped Generations.

**Blocked by:** 18 — Recover DailyTrack without duplicate or partial history; 19 — Keep DailyTrack forward-only across overlap corrections; 20 — Collect retired Data Generations safely.

**Status:** ready-for-agent

- [ ] Active Tracking Origin, progression, Attempt, Checkpoint, Working Cache, detail, retry, stop, and equivalence paths no longer read or write Release identifiers or predecessor chains.
- [ ] Tracking progress is expressed by the last successful Checkpoint session and current Head session frontier; Generation identity remains internal Attempt pin and provenance metadata only.
- [ ] Activation reconstructs from the seed Result's Terminal Strategy State, and cache rebuild uses the latest authoritative Checkpoint plus current Canonical Data without needing the seed Release or a collected Generation.
- [ ] Release history, Release links, and Generation browsing are absent from every DailyTrack public response and rendered projection.
- [ ] Checkpoint and Result publication continue to reject the transient Strategy Ledger, raw Alpha and Label values, orders, fills, and position history.
- [ ] Normal catch-up, failure recovery, Stop, Active DailyTrack Limit, working-cache rebuild, forward-only corrections, and Run/Advance equivalence all remain green after the application contract is removed.
- [ ] This ticket leaves isolated legacy physical rows and tables untouched; their guarded destructive removal belongs exclusively to the final permanent Dataset Release contract after Development Reset is available.
