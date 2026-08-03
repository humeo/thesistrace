---
status: accepted
---

# Require an explicit Holdings Count capped at one hundred

Every successful V1 Run using `long_only_top_n_equal_weight` must resolve an
explicit integer `holdings_count` from the saved Research Definition. Its value
is between 1 and 100 inclusive and cannot exceed the selected Liquidity
Universe size. A Definition may be saved before this value is valid, but an
admitted ResearchRun never depends on a runtime default for it.

At a rebalance decision, if fewer than `holdings_count` instruments are
eligible for a new buy, the Strategy targets only those available candidates.
It does not backfill with ineligible instruments; capital without an eligible
target remains cash.
