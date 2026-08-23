---
status: accepted
---

# Cap Effective Alpha Lookback at 252 market sessions

Every window or lag argument `n` in a V1 Alpha Expression counts market
sessions from the exchange calendar. A rolling window of length `n` contains
the current session and the preceding `n-1` sessions; `lag(x,n)` addresses the
session exactly `n` positions earlier. Missing instrument observations do not
cause either operation to search farther back. ADR-0082 requires every `n` to
be a positive integer literal no greater than 252.

Validation calculates the Effective Alpha Lookback across nested functions. For
example, `ts_mean(pct_change(close, 5), 20)` has an effective lookback of
24 market sessions. A rolling length and a historical offset are distinct:
`ts_mean(close, 252)` has offset 251, while
`lag(close, 252)` has offset 252. The composed total must not exceed 252
market sessions. A submitted Browser Draft that exceeds the limit fails
validation when Run is requested. The local Draft remains intact, but no
immutable input or ResearchRun is created. The runtime neither expands the
requested data range nor truncates the calculation.

The runtime derives Calculation Warm-up from the expression's effective
lookback and loads it from the Attempt's pinned Data Generation. It never
requires a fixed 252-session prefix or a fixed Research Period length. Warm-up
outputs do not appear in Factor Evaluation or Strategy Backtest results.
