---
status: accepted
---

# Report daily actual Cash Ratio and three aggregates

After every Open NAV Cycle, V1 records:

```text
Cash Ratio[t] = Net Cash[t] / Net NAV[t]
```

Cash Ratio is an Actual Holdings result rather than a target allocation.
Candidate shortages, Blocked Orders, Board-Lot Rounding, incomplete allocation
after sells, Transaction Costs, and the non-negative-cash constraint can all
leave cash.

Strategy Backtest derives the daily series from the Net Cash and Net NAV
columns retained in Strategy Daily Observations and reports its arithmetic
mean, Research Window maximum with the corresponding date, and ending value.
It does not store a duplicate Cash Ratio series or enforce a separate cash
target.
