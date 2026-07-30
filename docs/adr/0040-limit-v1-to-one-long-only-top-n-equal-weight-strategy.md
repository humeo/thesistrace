---
status: accepted
---

# Limit V1 to one long-only Top-N equal-weight Strategy

V1 supports one Strategy type: `long_only_top_n_equal_weight`. At each
rebalance decision, it ranks instruments eligible for a new buy by their final
Alpha Values from highest to lowest, breaks exact ties by `instrument_id`
ascending, selects the first N, and assigns equal target portfolio weight to
each selected instrument. ADR-0078 defines this total order.

The Strategy is long-only and unlevered. It has no short positions, optimizer,
risk model, industry quota, or other portfolio-construction mode. Capital that
cannot be allocated remains cash.

ADR-0041 defines the value of N, ADR-0042 defines how scheduled Rebalances
consume Alpha Values, and ADR-0048 defines target-to-order sequencing.
Unfilled-order behavior is defined by ADR-0045.
