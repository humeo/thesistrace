---
status: accepted
---

# Use 756 input sessions and a 504-session report window

A V1 ResearchRun consumes exactly the 756 completed Research Sessions defined
by ADR-0069, ending at the last completed session available in its pinned
Dataset Release:

```text
first 252 sessions: calculation-only warm-up
last 504 sessions:  reported Research Window
```

The warm-up supports the maximum Effective Alpha Lookback and Liquidity
Universe calculation but contributes no Factor Evaluation or Strategy
Backtest result. V1 counts Research Sessions rather than natural years, so
every run has the same intended input and report lengths despite holidays or
leap years. A pinned Dataset Release without all 756 sessions cannot start a
V1 ResearchRun.

Warm-up Alpha inputs may make the first Research Window Alpha Expression
complete, but a warm-up Final Alpha Cross-Section never creates Strategy
orders. ADR-0079 starts Strategy Backtest from all cash at the first Research
Window open and uses the first Research Window close as its first signal.

Release-owned metadata and lineage are not counted as Research Input History.
In particular, an Adjustment Anchor may predate these 756 sessions without
extending the Alpha calculation window or the reported Research Window.

An instrument listed after the input window begins retains its shorter
available history and resulting missing values; the runtime never extends the
shared window for one instrument. At the report-window end, Forward Return
Labels whose future exit open is not yet available remain missing rather than
shortening or moving the window. ADR-0086 classifies this expected coverage
loss as `right_censored_by_release_end`.

Strategy has a separate terminal rule: a scheduled signal creates orders only
when both its execution open and one following valuation open are inside these
504 sessions. The final session is a valuation boundary, not a forced
liquidation. ADR-0080 defines the exact cutoff.

This decision supersedes ADR-0021's approximate natural-year wording.

The exact 756/504 shape applies to each standard ResearchRun, including the
seed run from which Daily Tracking may start. ADR-0104 then continues a
DailyTrack from the seed's fixed Tracking Origin without rolling its account
baseline or limiting its forward state to another 504-session ResearchRun.
