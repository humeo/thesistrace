---
status: accepted
---

# Require an explicit Holdings Count capped at one hundred

Every V1 Research Definition using `long_only_top_n_equal_weight` must contain
an explicit integer `holdings_count`. Its value is between 1 and 100 inclusive
and cannot exceed the selected Liquidity Universe size. A frozen definition
never depends on a runtime default for this value.

At a rebalance decision, if fewer than `holdings_count` instruments are
eligible for a new buy, the Strategy targets only those available candidates.
It does not backfill with ineligible instruments; capital without an eligible
target remains cash.
