# Report Gross and Net NAV from one fill path

Strategy Backtest uses the Net portfolio after Transaction Costs for every target, affordability, and rebalance decision, and derives Gross NAV from those same holdings and fills. This isolates cost attribution without introducing a second hypothetical portfolio whose different decisions would confound the comparison.
