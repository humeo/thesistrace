---
status: accepted
---

# Report Gross and Net NAV from one fill path

Strategy Backtest derives Gross NAV and Net NAV from the same Actual Holdings and fill path, with Net NAV as the decision-bearing and Benchmark-comparison result and Gross NAV only as cost attribution. Both complete NAV series and bounded Transaction Cost aggregates are retained in Strategy Daily Observations, while raw orders and fills remain transient.
