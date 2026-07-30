---
status: accepted
---

# Make batch-versus-incremental equivalence the V1 end-to-end goal

ThesisTrace V1 validates one end-to-end research chain:

```text
Tushare ingestion
  -> Dataset Publication
  -> immutable Dataset Release
  -> Research Definition validation and freezing
  -> Alpha Expression parsing and evaluation
  -> runtime Final Alpha Cross-Sections
       -> bounded Factor summaries
       -> retained minimal Strategy results
       -> bounded Daily Tracking state
```

Daily Tracking is inside V1. After each successfully published Dataset Release,
it incrementally:

- computes the new session's Final Alpha Cross-Section and keeps only the
  latest observations needed by the longest Label horizon in the Pending Alpha
  Cache;
- resolves pending Forward Return Labels whose nominal exit Research Sessions
  have reached their maturity frontier and updates the latest-504-session
  Rolling Factor Observation Cache for each of the three horizons; and
- advances the simulated Strategy's orders, Actual Holdings, cash, costs, and
  NAV through the new session.

ADR-0148's Working Cache is latest-only, bounded, and rebuildable from immutable
Dataset Releases and pinned research semantics. It is operational state, not
durable Result Bundle or Tracking Checkpoint observations. A normal Advance
updates or boundedly rebuilds it; it does not full-replay from Tracking Origin.

ADR-0103 starts an explicit DailyTrack from one successful seed ResearchRun,
and ADR-0104 keeps one fixed Tracking Origin instead of restarting a rolling
504-session account after every Release. The central correctness comparator is
therefore a batch replay and incremental replay that share that Origin,
research semantics, and target Dataset Release—not a fresh standard
ResearchRun on the target Release.

ADR-0108 requires canonically exact overlapping runtime Alpha Values and
matured Labels, orders, costs, holdings, cash, NAV, and derived results under
the pinned numeric contracts. Intermediate equality can be verified during
replay without making those values persistent product data. ADR-0105 publishes
immutable Checkpoints with bounded summaries and Strategy state, ADR-0148
defines the rebuildable Tracking caches and Factor Summary Snapshot, and
ADR-0107 creates a new immutable Generation and full replay when a historical
correction invalidates incremental continuation.

V1 still creates no Alpha compiler or separately persisted compiled plan.
Validation, parsing, and evaluation are formula-engine operations over the
structured Research Definition. Daily Tracking does not include notifications,
automated real-market trading, or a separate complex monitoring product.

This decision supersedes only ADR-0002's earlier exclusion of daily tracking.
AI Chat, MCP, multi-tenancy, notifications, and automated trading remain
outside V1.
