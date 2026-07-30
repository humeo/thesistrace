---
status: accepted
---

# Report Turnover as one event series and two aggregates

At every scheduled execution open, V1 calculates one-way Turnover from Actual
Holdings immediately before and after execution:

```text
Turnover[t] =
    0.5 * sum(abs(post_weight[a] - pre_weight[a]))
```

The assets `a` include every held instrument and cash. Only actual fills affect
post-execution weights; blocked or otherwise unfilled orders do not. Initial
deployment from cash is included, and a scheduled Rebalance with no fills
records zero rather than disappearing.

Each instrument weight uses its Adjusted Holding Units multiplied by Adjusted
Research Price; it is not Execution Share Quantity multiplied by Raw Market
Price. Each pre- and post-trade weight divides by the corresponding Net NAV,
and cash uses the corresponding Net Cash balance. Gross accounting values never
enter Turnover.

Strategy Backtest retains the per-Rebalance Turnover event series and reports
two scalar aggregates:

```text
Average Rebalance Turnover =
    arithmetic mean of every scheduled Rebalance observation, including zero

Annualized Turnover =
    sum(Turnover) * 252 / return_interval_count
```

Child Orders for one logical order contribute only through their combined
effect on Actual Holdings, not as independent Turnover events.
