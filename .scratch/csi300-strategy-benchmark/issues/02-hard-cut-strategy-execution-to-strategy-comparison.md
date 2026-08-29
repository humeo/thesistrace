# 02 — Hard-cut Strategy execution to Strategy Comparison

**What to build:** Execute and persist only Strategy facts. Persist the existing
list `key_metrics.annualized_excess_return` once at successful ResearchRun
finalization, and assemble Detail comparison from the Benchmark Snapshot.

**Blocked by:** 01.

**Status:** complete

- [x] Row, columnar, continuation, retry, Terminal Strategy State, Tracking Origin, Checkpoint, and immutable Result contain no benchmark calculation or state.
- [x] Immutable Strategy facts include first investable Entry Open, Initial Cash, daily Net NAV, and Terminal coordinate.
- [x] Successful finalization persists the existing annualized excess key metric; Snapshot unavailability stores `null` without failing the Run.
- [x] ResearchRun and DailyTrack Detail return the same available/unavailable Strategy Comparison union.
- [x] Strategy growth uses Initial Cash, Benchmark uses Entry Open, and Net Excess NAV is their ratio with 252-session annualization over the same interval.
- [x] DailyTrack permanently uses its seed Entry Open and Initial Cash even for a bounded 504-observation response.
- [x] Snapshot unavailability affects only comparison and invokes no old, carried, alternate, or remote fallback.
- [x] ResearchRun, Batch, continuation, retry, and DailyTrack equivalence tests pass under the hard cut.

## Comments

- Removed selected-universe equal-weight calculation and every Benchmark field
  from Kernel, continuation, retry, Checkpoint, Terminal Strategy State,
  Tracking Origin account state, Result Parquet, and immutable Result schemas.
  Result facts now retain Entry Open, Initial Cash, daily Net NAV, Terminal
  coordinate, and the Strategy session interval needed for exact alignment.
- ResearchRun finalization persists the existing annualized excess list metric
  through the private scalar service. ResearchRun and DailyTrack Detail build
  the same Snapshot-backed Comparison union; DailyTrack derives its interval
  from the full seed-relative history before returning the latest 504 points.
- Verification: `mise exec -- pnpm test` passed 683 backend tests, TypeScript
  typecheck, and 63 frontend tests. Final isolated Compose run
  `20260827t153350z-42122-73f34aaf` passed 291 integration tests and all six
  restart/recovery sentinels. Post-review focused Compose main phases also
  passed 10, 2, and 6 tests; their later restart phases were intentionally
  deselected by `-k`.
- Spec and Standards reviews completed clean after enforcing exact Strategy
  interval coverage, explicit dependency wiring failures, deterministic
  outage/recovery behavior, and per-test internal fake-server cleanup.
