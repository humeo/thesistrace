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
  -> Alpha Matrix
       -> Factor Evaluation
       -> Strategy Backtest
       -> Daily Tracking
```

Daily Tracking is inside V1. After each successfully published Dataset Release,
it incrementally:

- appends the new session's Final Alpha Cross-Section;
- resolves previously pending Forward Return Labels whose nominal exit
  Research Sessions have reached their maturity frontier; and
- advances the simulated Strategy's orders, Actual Holdings, cash, costs, and
  NAV through the new session.

ADR-0103 starts an explicit DailyTrack from one successful seed ResearchRun,
and ADR-0104 keeps one fixed Tracking Origin instead of restarting a rolling
504-session account after every Release. The central correctness comparator is
therefore a reference execution and incremental execution that share that
Origin, research semantics, and ordered sequence of Advance Dataset Releases,
not a fresh standard ResearchRun on the Head Release. When no accepted
historical correction changes a dependency, the sequence is equivalent to the
target Release's cumulative snapshot. After a correction boundary, ADR-0144
requires the reference execution to apply the same Release sequence at the same
Advance boundaries rather than pretending the latest corrected Release was
known from the Origin.

ADR-0108 requires canonically exact overlapping Alpha Values, matured Labels,
orders, costs, holdings, cash, NAV, and derived results under the pinned numeric
contracts. Every incremental observation remains attributable to its exact
DailyTrack, Definition semantics, and Dataset Release. ADR-0105 publishes
immutable Checkpoints, ADR-0106 appends Label maturation, and ADR-0144
continues prospectively across a historical correction without modifying old
observations.

V1 still creates no Alpha compiler or separately persisted compiled plan.
Validation, parsing, and evaluation are formula-engine operations over the
structured Research Definition. Daily Tracking does not include notifications,
automated real-market trading, or a separate complex monitoring product.

This decision supersedes only ADR-0002's earlier exclusion of daily tracking.
AI Chat, MCP, multi-tenancy, notifications, and automated trading remain
outside V1.
