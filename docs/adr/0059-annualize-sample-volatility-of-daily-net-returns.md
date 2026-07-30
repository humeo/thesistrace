---
status: accepted
---

# Annualize sample volatility of daily Net Returns

V1 defines each daily Strategy Net Return between consecutive post-trade open
Net NAV observations:

```text
Daily Net Return[t] = Net NAV[t] / Net NAV[t-1] - 1

Annualized Volatility =
    sample_std(Daily Net Return, ddof=1) * sqrt(252)
```

The series retains genuine zero-return intervals, including all-cash exposure
or a Valuation Carry that leaves the whole portfolio unchanged. V1 does not
drop them, calculate volatility from NAV levels, or use Gross Returns for the
primary Strategy volatility metric.
