# Use Net accounting state for all Strategy decisions

Target sizing, sells, buys, affordability, weights, and later Rebalances all read one Net portfolio state after Transaction Costs. Gross NAV is derived from the same fills for attribution only and never drives a decision.
