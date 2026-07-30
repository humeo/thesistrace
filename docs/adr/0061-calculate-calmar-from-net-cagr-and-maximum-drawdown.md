---
status: accepted
---

# Calculate Calmar from Net CAGR and Maximum Drawdown

V1 calculates:

```text
Calmar Ratio = Net Annualized Return / Maximum Drawdown
```

The numerator is the Net NAV trading-day CAGR defined by ADR-0056, and the
denominator is the non-negative Maximum Drawdown defined by ADR-0058. A
negative Net Annualized Return produces a negative Calmar Ratio. A zero or
unavailable Maximum Drawdown produces no Calmar Ratio rather than infinity.

Gross Annualized Return does not enter the primary Calmar Ratio.
