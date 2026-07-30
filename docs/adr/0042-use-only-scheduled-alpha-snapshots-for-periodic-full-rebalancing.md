---
status: accepted
---

# Use only scheduled Alpha snapshots for periodic full rebalancing

For a Strategy rebalance interval of N market sessions, V1 uses the Alpha
snapshots produced after signal sessions `D0`, `DN`, `D2N`, and so on. It
recalculates the complete Top-N equal-weight target after each scheduled signal
session and first attempts the resulting orders at the next session's open:
`D1`, `DN+1`, `D2N+1`, and so on.

Alpha Values continue to be produced every session for Factor Evaluation.
Those from intermediate, non-rebalance sessions do not enter Strategy, queue
for later execution, or create overlapping holding cohorts. The portfolio
continues to hold its positions between scheduled rebalances, subject to
separately defined execution and existing-position rules.

The first signal session of the reported Research Window is `D0`, providing a
deterministic schedule anchor. A scheduled signal creates orders only when its
execution open and one subsequent holding-valuation open both remain inside
the Research Window; ADR-0080 defines the terminal cutoff. ADR-0043 defines the
allowed range of N.

ADR-0104 preserves that original `D0` phase when DailyTrack continues past its
seed Research Window. Later Dataset Releases do not re-anchor the schedule.
