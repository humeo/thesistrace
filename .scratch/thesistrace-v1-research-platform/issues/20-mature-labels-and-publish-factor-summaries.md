# 20 — Mature Labels and publish Factor summaries

**What to build:** Resolve pending tracking labels at their fixed maturity
frontiers and append current Factor observations and rolling summary snapshots
without editing earlier truth.

**Blocked by:** 11 — Calculate complete Factor Evaluation; 19 — Advance a DailyTrack by Research Session.

**Status:** resolved

- [x] The 1-, 5-, and 20-session maturities occur only at `t+2`, `t+6`, and `t+21`.
- [x] Entry unavailability, terminal -100%, exit suspension, valid return, and unexplained data failure resolve in the accepted precedence.
- [x] An event remains pending before its nominal frontier even when later unavailability can already be inferred.
- [x] Every Label Maturation event binds Generation, signal and maturity sessions, originating Alpha, basis Release, result or reason, and publishing Checkpoint.
- [x] Catch-up and replay never invent a historical Dataset Release identity.
- [x] Newly valid IC, Rank IC, quantile, and Top-Bottom observations append under the same sample rules as ResearchRun.
- [x] Each Checkpoint publishes immutable per-horizon summaries over the latest 504 signal sessions while retaining older observations.

## Comments

- Added per-instrument immutable Label resolutions and maturity events at the
  fixed frontiers, including governed missingness and hard unexplained-data
  failure.
- Checkpoints retain full ordered Factor history and separately publish current
  504-signal summaries for all three horizons.
