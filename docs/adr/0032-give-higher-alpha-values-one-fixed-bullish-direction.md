---
status: accepted
---

# Give higher Alpha Values one fixed bullish direction

Every V1 Alpha uses one direction convention: a higher Alpha Value expresses a
stronger expectation of higher future return. Factor Evaluation reports signed
results without changing that convention, and Strategy ranks higher values
ahead of lower values.

The runtime never reverses an Alpha because its historical IC or backtest result
is negative. An author who intends a lower raw quantity to express a stronger
bullish view must negate it explicitly in the Alpha Expression, for example
`-pct_change($close_adj, 20)`. The explicit sign remains part of the frozen
Research Definition.
