---
status: accepted
---

# Use a mounted current Dataset Head and Attempt-scoped Data Generations

ThesisTrace operates one current Dataset Head over a persistent mounted
Canonical Data Store. Service startup reads and validates the mounted Head and
never contacts Tushare or rebuilds Canonical Market Data. Explicit bootstrap of
an empty development store defaults to the latest one natural year, while a
stable deployment may mount an already prepared store with a longer coverage
range.

Each successful operator refresh builds a complete validated Data Generation
beside the active one and atomically moves the Dataset Head. A Generation is a
temporary consistency boundary, not a permanent product resource or a promise
of historical input reproducibility. ADR-0146's partitioned Parquet and bounded
manifest encoding remains in force, but the store need not retain predecessor
chains or old market-data bytes after no active execution references them.

Creating a ResearchRun freezes its Research Definition content, requested
dates, field bindings, Strategy and cost rules, and numeric and semantic
contract versions, but does not bind data. Each ResearchRun Attempt resolves
the latest Dataset Head when that Attempt starts and pins the resolved
Generation for the duration of that Attempt. ResearchRun and Attempt provenance
metadata record the Generation and data-through session used by a successful
execution without adding fields to the Result payload. A retry resolves the
then-current Head and recalculates Alpha, Factor, and Strategy completely from
the beginning; partial artifacts from a failed Attempt are never mixed with
another Generation.

A successful historical ResearchRun may explicitly start a DailyTrack. The
Track fixes the complete Research Definition and simulated account state, then
processes every later Research Session in order until it catches the Dataset
Head and continues forward. Each Advance uses the current data first available
to that calculation. Accepted changes to overlapping market data never rewrite
previously published Track orders, holdings, cash, or NAV, and create no user
notification; they affect only results first calculated afterward.

ThesisTrace retains completed Research results and DailyTrack state but does
not promise that a later execution can recover the exact historical market-data
bytes used by an earlier Attempt. ADR-0095's ResearchRun state machine,
idempotent creation, cancellation, and user-Rerun rules remain in force;
ADR-0103's explicit Track activation, Active DailyTrack Limit, and terminal Stop
rules also remain in force.

The current system has no permanent Dataset Release product resource or
immutable-data binding at ResearchRun creation. Wherever an older retained
market, calculation, or validation rule needs a data coordinate, that
coordinate is the Dataset Head or the execution-pinned Data Generation. State
machines, atomic publication, numeric rules, and the module-first architecture
remain independent of that coordinate.
