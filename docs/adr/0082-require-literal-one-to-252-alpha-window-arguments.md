---
status: accepted
---

# Require literal one-to-252 Alpha window arguments

Every `n` argument to `lag`, `delta`, `pct_change`, `ts_mean`, `ts_sum`,
`ts_std`, `ts_min`, or `ts_max` must be an integer literal from 1 through 252
inclusive. V1 rejects zero, negative values, decimals, Field References, and
computed expressions as `n`, even when an expression could evaluate to an
integer.

The argument has function-specific coordinates:

- `lag(x,n)`, `delta(x,n)`, and `pct_change(x,n)` address exactly session
  `t-n`; and
- a rolling function of length `n` contains sessions `t-n+1` through `t`,
  including the current session.

The per-argument limit does not replace the nested Effective Alpha Lookback
limit. Validation composes historical offsets through the complete expression
and rejects a result above 252. For example:

```text
ts_mean(close, 252)                  # valid: offset 251
lag(close, 252)                      # valid: offset 252
ts_mean(pct_change(close, 5), 250)  # invalid: offset 254
```

This literal contract keeps frozen Alpha Expressions portable and makes their
required history statically decidable before a ResearchRun starts.
