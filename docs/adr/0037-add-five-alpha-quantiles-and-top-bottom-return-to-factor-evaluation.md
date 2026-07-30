---
status: accepted
---

# Add five Alpha quantiles and Top-Bottom return to Factor Evaluation

For every valid signal session and each fixed Forward Return Label horizon, V1
sorts the Effective Factor Sample by final Alpha Value from lowest to highest
and divides it into five approximately equal-count groups:

```text
Q1: lowest Alpha Values
Q2
Q3
Q4
Q5: highest Alpha Values
```

Factor Evaluation calculates each group's equal-weight mean Forward Return
Label and the Top-Bottom Return defined as `Q5 - Q1`. The two-year report shows
the average Q1 through Q5 returns, their ordering, and the average Top-Bottom
Return separately for the 1-, 5-, and 20-session horizons. Stocks are never
sorted by their future returns.

ADR-0093 requires at least 30 valid Alpha-and-label pairs for one
session-horizon before any of its Five-Quantile Returns or Top-Bottom Return is
calculated.

These are predictive diagnostics, not Strategy portfolios. V1 does not infer
short positions, orders, transaction costs, or portfolio NAV from the
Top-Bottom Return. ADR-0038 defines treatment of equal Alpha Values at quantile
boundaries, and ADR-0085 defines the exact average-rank assignment formula.
