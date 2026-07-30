---
status: accepted
---

# Preserve Top 3000 with bounded-memory columnar execution

Hosted Platform V2 preserves the existing Top 300, Top 1000, Top 2000, and Top
3000 Liquidity Universe contract. The hosted release does not remove Top 3000,
silently truncate its membership, sample its instruments, or substitute a
smaller Universe in response to the single-node capacity boundary.

Top 3000 is the representative maximum Compute workload for launch acceptance.
One Top 3000 ResearchRun must complete within the single-Worker envelope in
ADR-0130, and four simultaneous Top 3000 heavy Activities must complete while
the full 6-core, 12-GiB Compose stack remains within its host and service
health thresholds.

Meeting this gate requires the Hosted Platform V2 data and calculation paths to
replace whole-Release JSON and object-heavy in-memory materialization with
partitioned Parquet, columnar operations, projection and partition pruning, and
bounded intermediate state. This physical rewrite must preserve the frozen
Alpha, Factor Evaluation, Strategy Backtest, missingness, checksum,
reproducibility, and release-sequence Batch-Incremental Equivalence semantics.

The resource rewrite is a hosted-release prerequisite rather than a later
performance optimization. If representative Top 3000 workloads cannot pass the
accepted resource envelope, Hosted Platform V2 is not ready to open to invited
Users.
