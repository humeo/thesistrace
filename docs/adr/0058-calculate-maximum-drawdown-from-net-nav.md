---
status: accepted
---

# Calculate Maximum Drawdown from Net NAV

V1 calculates the Strategy drawdown series only from post-trade Net NAV:

```text
Drawdown[t] =
    1 - Net NAV[t] / max(Net NAV[s] for s <= t)

Maximum Drawdown = max(Drawdown[t])
```

Drawdown is reported as a non-negative loss magnitude, such as 23.5 percent,
not a negative return. The report retains the complete drawdown series and
identifies the prior peak date, trough date, and first later recovery date at
which Net NAV reaches or exceeds that peak. A drawdown not recovered by the
Research Window end is labeled `unrecovered`.

Gross NAV does not define the primary Maximum Drawdown because it omits the
Transaction Costs experienced by the Strategy.
