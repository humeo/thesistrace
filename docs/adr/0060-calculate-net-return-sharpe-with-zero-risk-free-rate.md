---
status: accepted
---

# Calculate Net Return Sharpe with zero risk-free rate

V1 explicitly records `risk_free_rate: 0` and calculates:

```text
Sharpe Ratio =
    mean(Daily Net Return)
    / sample_std(Daily Net Return, ddof=1)
    * sqrt(252)
```

The numerator is the arithmetic mean Daily Net Return, not Net Annualized
Return or CAGR. Transaction Costs are therefore included through Net NAV. If
fewer than two valid return intervals exist or the sample standard deviation is
zero, Sharpe Ratio is missing rather than infinite.

V1 does not ingest or select a separate risk-free-rate series.
