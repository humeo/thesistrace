---
status: superseded by ADR-0068
---

# Report two years from three years of research input

V1 Factor Evaluation and Strategy Backtest report only the trailing two-year
Research Window ending at the last completed market session available in the
pinned Dataset Release. Dataset Publication additionally provides the preceding
252 completed market sessions as calculation-only warm-up data. Together, the
Research Window and warm-up form the approximately three years of Research
Input History consumed by a run.

Warm-up sessions support liquidity ranking and the maximum Effective Alpha
Lookback defined by ADR-0029 but do not appear in reported results. V1 does not
expose an unbounded historical date range.
