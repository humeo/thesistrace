---
status: accepted
---

# Gate long Research performance on the complete Production Image path

The Reference Long Research Workload evaluates both Research Kind variants of
`rank(pct_change(close, 20))` over the Top 3000 Liquidity Universe from
2010-01-04 through 2026-08-13 against one frozen representative Data Generation.
Each variant measures the complete ResearchRun path: admission and frozen plan
facts, columnar reads, Alpha, 1-, 5-, and 20-session Factor Evaluation, Chunk
Checkpoints, finalization, and atomic Result publication. The Strategy Backtest
variant additionally measures Strategy execution and its larger Result Bundle.

The benchmark runs the final Production Image in one 2 vCPU and 2 GiB
single-slot Worker. For each Research Kind, across five measured samples per
phase, cold execution P95 must not exceed 10 minutes and warm execution P95 must
not exceed 5 minutes. Peak process RSS must not exceed the 1.5 GiB execution
budget, the first durable Checkpoint must commit within 45 seconds of `running`,
and cooperative cancellation must reach confirmed terminal `cancelled` within
5 seconds while the owning Worker supervisor remains alive. ADR-0198 governs
the safety-first lease recovery path when that supervisor, container, or host is
lost.

Cold measurement starts without a prior scan of the referenced immutable data
objects in the benchmark environment. Warm measurement preloads those same
objects but creates and executes a fresh ResearchRun. Queue waiting time is
excluded; execution begins at successful claim and ends only after Result
publication commits.

These limits are implementation acceptance and regression gates, not a per-user
SLA or an ETA promise. An Alpha-only series benchmark, reduced Universe, shorter
period, source-tree execution, or unpublished prepared Result cannot satisfy the
gate. Product support for later sessions remains open-ended; this fixed range
keeps the regression workload reproducible while throughput telemetry exposes
growth beyond it.
