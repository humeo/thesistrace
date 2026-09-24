# Report Gross and Net NAV from one fill path

Strategy Backtest uses the Net portfolio after Transaction Costs for every target, affordability and rebalance decision, and derives Gross NAV from the same holdings, fills and execution prices. Both views therefore include any modeled Price Slippage; their difference attributes explicit Transaction Costs and accounting-rounding residuals, not all trading friction. This avoids a second hypothetical frictionless portfolio whose different quantities and decisions would confound the comparison.
