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
example, `ts_mean(pct_change($close_adj, 5), 20)` has an effective lookback of
24 market sessions. A rolling length and a historical offset are distinct:
`ts_mean($close_adj, 252)` has offset 251, while
`lag($close_adj, 252)` has offset 252. The composed total must not exceed 252
market sessions. A Research Definition that exceeds the limit fails validation
when Run is requested. The current Definition is still saved, but no immutable
input or ResearchRun is created; Save by itself remains allowed. The runtime
neither expands the requested data range nor truncates the calculation.

Dataset Publication makes the 252 sessions immediately before the 504-session
Research Window available as calculation-only warm-up data under ADR-0068.
Warm-up outputs do not appear in Factor Evaluation or Strategy Backtest
results.
