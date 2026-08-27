# Fixed CSI 300 Strategy Benchmark

**Status:** complete

## Objective

Use one project-owned CSI 300 price-index Open series as the fixed Strategy
comparison for every ResearchRun and DailyTrack. Benchmark data is independent
of Canonical Data, Dataset Families, and Data Generations.

## Contract

- The Data Operator publishes one complete `csi300-price-index-open.json`
  Benchmark Snapshot from Tushare `index_daily`, `399300.SZ`, `open`.
- The Snapshot starts at `2010-01-04`, preserves every published historical
  Level, and only appends newly required Research Sessions.
- Dataset Bootstrap and Market Refresh require Snapshot coverage before a new
  Market Head can publish. A Snapshot may lead the Head.
- Strategy execution and immutable Results contain Strategy facts only.
  ResearchRun finalization persists the existing
  `key_metrics.annualized_excess_return` once; Detail read models assemble the
  fixed comparison from Strategy facts plus the Snapshot.
- ResearchRun and DailyTrack expose the same available/unavailable comparison
  union. Snapshot failure never blocks Strategy execution, Tracking, or the API.
- The browser renders backend-provided Net Strategy, 沪深300, and Net Excess
  curves and contains no financial alignment or compounding formulas.
- There is no public Raw Benchmark API, alternate index, carry, migration,
  compatibility reader, or runtime remote fallback.

## Delivery map

1. Publish the independent append-only Benchmark Snapshot.
2. Hard-cut execution Benchmark state and add Strategy Comparison.
3. Render the fixed comparison in ResearchRun and DailyTrack Detail.
4. Qualify the release and perform the preserved Development cutover.

## Comments

- The approved Development cutover uses one `dev:reset`, preserves Canonical
  Data and its Dataset Head, runs one ordinary live Market Refresh, and never
  runs Dataset Bootstrap or `dev:erase`.
