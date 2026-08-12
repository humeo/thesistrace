---
status: accepted
---

# Record Strategy NAV after each open execution cycle

V1 uses one ordered accounting cycle at each market-session open:

1. accrue the prior Actual Holdings from the preceding open to the current open
   by valuing Adjusted Holding Units at Adjusted Research Price or an allowed
   Valuation Carry;
2. record pre-trade Gross NAV and Net NAV, with only Net NAV feeding Strategy
   decisions under ADR-0081;
3. execute scheduled sells and buys using integer Execution Shares, Raw Market
   Price constraints, and ADR-0070 Research Settlement;
4. deduct Transaction Costs; and
5. record post-trade Gross NAV and Net NAV.

Daily Strategy return is calculated between consecutive post-trade open NAV
observations. Alpha and Universe Membership produced after signal session `t`
first affect orders at the `t+1` open, and the resulting holding interval runs
from the `t+1` open to the `t+2` open.

At the first Research Period session `R1`, V1 records an all-cash post-trade
baseline without executing an order. The first signal forms after `R1` closes
and first deploys at the `R2` open. Consequently, the `R1`-to-`R2` Net Return
contains initial-deployment costs but no prior holding return; Gross Return is
zero. Warm-up Alpha Values never create Strategy orders.

The corresponding Strategy Benchmark return uses Universe Membership from
signal session `t` and the same `t+1`-open to `t+2`-open Adjusted Research Price
coordinate. Factor Evaluation, Strategy holdings, and Benchmark therefore do
not mix open-to-open and close-to-close return conventions.

The final Research Period open completes the last possible holding interval and
records Terminal Valuation without a Rebalance or forced liquidation. A
scheduled signal whose execution would occur at that final open is not used.
