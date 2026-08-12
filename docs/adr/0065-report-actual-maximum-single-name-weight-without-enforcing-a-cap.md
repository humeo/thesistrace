---
status: accepted
---

# Report actual Maximum Single-Name Weight without enforcing a cap

After every Open NAV Cycle, V1 calculates each instrument's actual portfolio
weight from its Strategy valuation divided by Net NAV, then records:

```text
Maximum Single-Name Weight[t] =
    max(actual instrument weight[i,t])
```

The calculation uses each Actual Holding's Adjusted Holding Units multiplied by
Adjusted Research Price, including a suspended position marked by Valuation
Carry. It never substitutes Execution Share Quantity multiplied by Raw Market
Price. Cash is excluded from the maximum. An all-cash portfolio records zero.
Blocked sells, failed buys, rounding, and price movement may make the result
exceed `1 / holdings_count`.

Strategy Backtest retains the daily series and reports its Research Period
maximum with the corresponding date, plus its ending value. V1 does not treat
this diagnostic as a position cap or modify orders to satisfy it.
