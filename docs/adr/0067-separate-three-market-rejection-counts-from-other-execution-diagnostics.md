---
status: accepted
---

# Separate three market-rejection counts from other execution diagnostics

Strategy Backtest reports separate counts for upper-limit buy rejection, lower-limit sell rejection, and full-session suspension rejection, while conditions that prevent order creation remain distinct Execution Diagnostics. Only bounded daily and period counts are retained; per-order rejection, order, child-order, and fill events remain transient because they can be regenerated from the frozen research inputs.
