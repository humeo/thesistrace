# 06 — Contract to the one-MiB Result Bundle

**What to build:** Make the compact Result Bundle the sole durable
ResearchRun result, remove the migration-only intermediate objects, and reject
any Run that cannot publish every required conclusion within one exact MiB.

**Blocked by:** 03 — Add the compact Result Bundle projection; 05 — Advance DailyTrack from the bounded Working Cache.

**Status:** ready-for-agent

- [ ] New Result Manifests, Activation Checkpoints, and Tracking Checkpoints contain no Alpha Matrix, stock-level Forward Return Label, daily Factor observation or curve, target history, raw order, Child Order, fill, rejection-event detail, or growing diagnostic object.
- [ ] The exact bytes of every ResearchRun-owned manifest and payload total no more than `1,048,576`, and the published manifest exposes the independently verifiable logical total.
- [ ] Shared Dataset Release objects are excluded from the Run budget, while content-addressed deduplication never reduces the logical bytes charged to an individual Run.
- [ ] A valid but oversized complete result fails publication without a succeeded ResearchRun, Result Bundle identifier, Result Manifest, or product-visible partial report.
- [ ] Cancellation or a stale Attempt cannot publish a prepared compact bundle after losing ownership of the ResearchRun.
- [ ] The production writer capacity gate retains 756 Strategy sessions, daily Rebalance and execution aggregates, and up to 3,000 Terminal Positions below the one-MiB limit.
- [ ] Factor summaries and all confirmed Strategy reports remain exactly reconstructible after every legacy compatibility object and reader has been removed.
- [ ] Development fixture artifacts may be rebuilt under the compact contract, and no production migration subsystem or general raw-artifact download product is introduced.
