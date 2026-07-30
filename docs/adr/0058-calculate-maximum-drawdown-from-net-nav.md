---
status: accepted
---

# Calculate Maximum Drawdown from Net NAV

Strategy Backtest derives Maximum Drawdown from the retained post-trade Net NAV series and reports it as a non-negative loss magnitude with its peak, trough, and recovery status. Gross NAV does not define the primary drawdown because it excludes the Transaction Costs experienced by the Strategy, and the full drawdown series is derived on demand rather than stored.
