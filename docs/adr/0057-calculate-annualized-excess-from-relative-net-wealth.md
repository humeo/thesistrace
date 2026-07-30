---
status: accepted
---

# Calculate Annualized Excess Return from relative Net wealth

V1 reports Strategy Benchmark Cumulative Return and Annualized Return over the
same open-to-open intervals used by Strategy. It constructs Net Excess NAV as:

```text
Net Excess NAV[t] =
    (Net NAV[t] / Net NAV[start])
    /
    (Benchmark NAV[t] / Benchmark NAV[start])
```

Annualized Excess Return is the compound annual growth rate of that relative
wealth series:

```text
Annualized Excess Return =
    Net Excess NAV[end] ^ (252 / return_interval_count) - 1
```

V1 does not define Annualized Excess Return as Net Annualized Return minus
Benchmark Annualized Return, because subtracting two independent CAGR values
does not preserve compounded relative wealth. Gross NAV is not used for excess
metrics.
