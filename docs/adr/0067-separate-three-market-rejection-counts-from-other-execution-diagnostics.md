---
status: accepted
---

# Separate three market-rejection counts from other execution diagnostics

V1's main Strategy report counts exactly three market-state reasons that block
an already created logical order:

```text
upper_limit_buy:  buy blocked at the published upper limit
lower_limit_sell: sell blocked at the published lower limit
suspension:       either side blocked by full-session suspension with no open
```

One logical order contributes one rejection even when it would have been split
into multiple Child Orders. The ResearchRun retains one daily count per reason
and the period totals, not date-instrument-side event details or an
unfilled-order ratio.

Conditions that prevent an order or target from being created are separate
Execution Diagnostics, including `insufficient_cash`, `below_board_lot`,
`insufficient_candidates`, and `ineligible`. They retain reason-specific counts
as bounded aggregates but no per-order details and do not increment a
market-rejection counter.

An unexplained missing market observation is neither a rejection nor an
execution diagnostic. It is a data-quality error that prevents a valid run.
Only `full_session_suspended` may produce the suspension rejection. A partial
suspension with a later valid daily open remains executable under ADR-0089.
