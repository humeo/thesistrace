---
status: accepted
---

# Sell before buying target deficits in Alpha order

At each Rebalance, Strategy Backtest sells eligible excess positions before buying selected target deficits in descending Final Alpha order with `instrument_id` as the exact-tie break. Every buy is bounded by its ideal target value and available Net Cash, blocked targets are not replaced, and raw order and fill details remain transient because retained Strategy Daily Observations and aggregates preserve their result effects.
