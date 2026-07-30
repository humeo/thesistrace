---
status: accepted
---

# Use a minimal closed Alpha function set in V1

V1 Alpha Expressions support only the following operations:

```text
arithmetic:       +, -, *, /, unary -
scalar:           abs(x), log(x), sign(x)
time series:      lag(x,n), delta(x,n), pct_change(x,n)
rolling window:   ts_mean(x,n), ts_sum(x,n), ts_std(x,n),
                  ts_min(x,n), ts_max(x,n)
```

`delta(x,n)` subtracts `lag(x,n)` from `x`; `pct_change(x,n)` divides `x` by
`lag(x,n)` and subtracts one. Industry Neutralization remains a post-expression
Alpha-processing option and is not a function in this set.

ADR-0083 fixes the numeric contract: `float64` evaluation without configured
intermediate rounding, natural `log`, three-valued `sign`, and population
`ts_std` with `ddof=0`.

Every field operand must belong to the six-field allowlist in ADR-0072.
`pct_change($close_adj, 1)` is the canonical V1 one-session price-return
expression; the source-normalized `pct_change_ratio` field is not an Alpha
operand.

Every time-series or rolling `n` is an integer literal from 1 through 252.
ADR-0082 defines its exact syntax and coordinate semantics; ADR-0029 separately
caps the composed Effective Alpha Lookback.

V1 does not support comparisons, Boolean or conditional expressions,
correlation, covariance, regression, cross-sectional rank or standardization,
or user-defined functions. Adding an operation later requires an explicit
versioned extension rather than silently changing the meaning of a frozen
Research Definition.

ADR-0029 fixes Effective Alpha Lookback semantics, and ADR-0030 fixes
valid-observation and missing-value semantics.
