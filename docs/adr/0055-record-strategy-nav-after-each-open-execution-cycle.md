# Record Strategy NAV after each Open execution cycle

Each Strategy observation accrues prior holdings to the current Open, executes any scheduled rebalance, applies costs, and records post-trade Gross and Net NAV. The first investable observation includes entry costs and the final observation is terminal valuation without forced liquidation, keeping Strategy performance and Strategy Comparison on the same Open-to-Open coordinate.
