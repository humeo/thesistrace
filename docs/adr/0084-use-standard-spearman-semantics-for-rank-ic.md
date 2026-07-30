---
status: accepted
---

# Use standard Spearman semantics for Rank IC

For one session-horizon Effective Factor Sample, V1 calculates Rank IC as the
standard Spearman correlation between Final Alpha Values and Forward Return
Labels. Equivalently, it assigns ascending ranks to both arrays and calculates
their Pearson correlation.

An exact tie receives the arithmetic mean of the positions it occupies. V1
does not break a tie by `instrument_id`, input row order, or random ordering,
and it does not implement a custom tie statistic. For example:

```text
values = [1, 1, 3]
ranks  = [1.5, 1.5, 3]
```

If either valid value array is constant, its rank array is also constant and
Rank IC is missing under ADR-0036. This remains true even when the valid-pair
count is at least 30.

An implementation may call a standard statistical-library Spearman routine,
provided its observable tie and constant-input behavior matches this contract.
