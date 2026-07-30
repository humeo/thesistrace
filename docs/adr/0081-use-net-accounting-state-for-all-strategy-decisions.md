---
status: accepted
---

# Use Net accounting state for all Strategy decisions

V1 has one decision-bearing Strategy ledger: Actual Holdings, Execution Share
Quantities, Adjusted Holding Units, Net Cash, and Net NAV after Transaction
Costs. Every portfolio-construction and execution decision reads this Net
state.

At a scheduled execution open:

- each ideal equal-weight target value is pre-trade Net NAV divided by the
  actual selected-target count;
- sell sizing compares current adjusted position value with that Net target;
- buy sizing and affordability use Net Cash remaining after prior fills and
  their Transaction Costs; and
- actual instrument and cash weights use the corresponding pre- or post-trade
  Net NAV. Turnover uses those same Net weights.

Gross NAV is derived from the same orders, fills, and holdings before cost
deductions. It is a reporting-only cost-attribution series. Gross Cash or Gross
NAV never changes a target, order quantity, candidate priority, affordability
decision, Actual Holding, or later Rebalance.

Consequently, V1 does not run a second hypothetical cost-free Strategy. Past
costs reduce future deployable Net capital in the one real decision path, while
Gross results show the valuation effect of removing costs from that same path.
