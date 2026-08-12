---
status: accepted
---

# Report daily Actual Holdings Count and four aggregates

At every post-trade open NAV observation, V1 records:

```text
Actual Holdings Count[t] =
    count(instruments whose Execution Share Quantity is greater than zero)
```

The count uses Actual Holdings rather than the Target Portfolio. It therefore
includes off-target positions retained by Blocked Orders and may exceed the
configured Holdings Count. Cash is not an instrument and does not enter the
count.

Strategy Backtest retains the daily Holdings Count series and reports its
arithmetic mean, minimum, maximum, and ending value over the Research Period.
