---
status: accepted
---

# Assign Factor quantiles from average Alpha rank

For one signal-session and Forward Return Label horizon, let `N` be the number
of instruments in the Effective Factor Sample. V1 assigns every instrument an
ascending average rank `r` from its Final Alpha Value and calculates:

```text
quantile = ceil(5 * r / N)
```

The result is Q1 through Q5, with Q1 containing lower Alpha Values and Q5
containing higher Alpha Values. With ten distinct values, ranks 1-2 enter Q1,
3-4 enter Q2, and so on.

An exact Alpha tie receives one average rank before the formula is applied.
For example, if positions 2 and 3 of a ten-instrument sample tie, both receive
rank 2.5 and both enter Q2. V1 does not split the tie by identity or row order
and does not rebalance the other groups to compensate.

As a result, group counts may differ and a group may be empty. An empty group
has no Five-Quantile Return, and Top-Bottom Return remains missing whenever
either Q1 or Q5 is empty, as defined by ADR-0038.
