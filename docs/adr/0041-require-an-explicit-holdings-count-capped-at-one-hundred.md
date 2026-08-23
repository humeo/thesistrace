---
status: accepted
---

# Require an explicit Holdings Count capped at one hundred

Every Strategy Backtest ResearchRun freezes an explicit integer
`holdings_count` from 1 through 100, capped by its selected Liquidity Universe;
an invalid Browser Draft is rejected instead of receiving a runtime default.

At a Rebalance, if fewer than `holdings_count` instruments are
eligible for a new buy, the Strategy targets only those available candidates.
It does not backfill with ineligible instruments; capital without an eligible
target remains cash.
