---
status: accepted
---

# Continue DailyTrack from one fixed Tracking Origin

DailyTrack is a fixed-inception continuous simulated account, not a daily
rolling 504-session backtest. Its Tracking Origin fixes the seed ResearchRun's
`R1` Research Session coordinate, all-cash baseline, original Rebalance
schedule anchor, and seed Definition semantics. Market data is resolved through
the current Tracking Generation's Dataset Release rather than frozen into the
Origin. At Generation 0 activation, the DailyTrack continues from the seed
Result Bundle's Terminal Holdings, Execution Share Quantities, adjusted units,
Gross and Net Cash, Gross and Net NAV, Benchmark state, cumulative costs, and
Rebalance phase without resetting any of them.

The Activation Checkpoint must retain a seed Release post-close Alpha signal if
and only if that signal lies on the original Rebalance schedule and its
execution Research Session is strictly after the Activation Dataset Release's
final session. Future is determined by Dataset Release and Research Session
coordinates, never by the operator's wall clock. A signal whose execution
session lies inside the finite seed Research Window and was skipped by
ADR-0080 is never revived.

After activation, each new Research Session is processed in market order:

1. its Open executes any signal scheduled from an earlier close and records
   valuation and accounting state; and
2. its completed close produces that session's Alpha Cross-Section and, when
   scheduled, the next pending Strategy signal.

The finite-window post-execution cutoff in ADR-0080 does not apply to an active
DailyTrack. A standard ResearchRun remains a rolling 756-input/504-report
snapshot that starts from all cash; it is not the direct comparator for a
later continuous DailyTrack state.

The batch oracle for DailyTrack replays from the same Tracking Origin with the
same activation rules through the same target Dataset Release. It must equal
the incremental Tracking path. It does not re-anchor at the latest release's
new rolling `R1`.
