---
status: accepted
---

# Bound each ResearchRun to a minimal one-MiB Result Bundle

Each successful ResearchRun publishes only the smallest immutable result needed
to render the confirmed Factor and Strategy conclusions and seed a DailyTrack.
Its durable bundle contains:

- one canonical JSON Result Manifest and provenance;
- one canonical JSON Factor Evaluation summary for each of the 1-, 5-, and
  20-session horizons;
- one canonical JSON Strategy summary;
- one ZSTD Parquet Strategy Daily Observation table;
- bounded ZSTD Parquet rebalance and execution aggregate tables;
- one ZSTD Parquet Terminal Positions table; and
- the bounded Terminal Strategy State needed to continue tracking.

The bundle never contains an Alpha Matrix, stock-level Forward Return Labels,
daily Factor observations or curves, target-weight history, raw orders, child
orders, fills, rejection-event details, duplicated drawdown or Cash Ratio
series, or other calculation diagnostics. Those values may exist transiently
inside one execution and can be regenerated deterministically from the frozen
Research Definition, Dataset Release, and pinned calculation contracts when an
investigation requires them.

The sum of the exact bytes of every ResearchRun-owned manifest and payload
object must not exceed `1,048,576` bytes. Shared Dataset Release objects are
outside that per-Run budget; content-addressed deduplication does not excuse an
oversized logical bundle. A Run fails result publication rather than silently
dropping a required metric or moving excluded intermediates into another
durable object.

This decision supersedes ADR-0035. Daily IC, Rank IC, Five-Quantile, and
Top-Bottom observations are still calculated in canonical signal-session order
to produce the retained summaries, but a ResearchRun neither publishes them nor
shows their curves.
