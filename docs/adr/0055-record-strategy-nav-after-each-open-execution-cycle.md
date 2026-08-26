# Record Strategy NAV after each Open execution cycle

Each Strategy observation accrues prior holdings to the current Open, executes any scheduled rebalance, applies costs, and records post-trade Gross and Net NAV. The first observation is an all-cash baseline and the final observation is terminal valuation without forced liquidation, keeping Strategy and benchmark returns on the same Open-to-Open coordinate.
