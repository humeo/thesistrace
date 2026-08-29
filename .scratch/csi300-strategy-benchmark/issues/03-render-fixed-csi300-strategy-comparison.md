# 03 — Render the fixed CSI 300 Strategy Comparison

**What to build:** Render the backend-assembled comparison consistently in
ResearchRun and DailyTrack Detail without financial calculations in the browser.

**Blocked by:** 02.

**Status:** complete

- [x] Both Detail contracts expose the same available/unavailable Comparison union.
- [x] Available metadata identifies 沪深300, Snapshot SHA-256, Coverage, publication time, Entry, and Terminal.
- [x] The chart begins at Entry Open and plots Net Strategy, 沪深300, and Net Excess without a pre-entry segment.
- [x] DailyTrack's bounded recent window does not reset the seed baseline.
- [x] The UI shows “沪深300” and “数据截至 YYYY-MM-DD”.
- [x] Unavailable comparison shows a clear state and never draws a Strategy-only comparison.
- [x] Existing `strategy.summary.metrics.annualized_excess_return` and list key metric paths remain unchanged.
- [x] TypeScript contract, components, ResearchRun, DailyTrack, 504-point, unavailable, and no-browser-formula tests pass.

## Comments

- ResearchRun and DailyTrack now share one typed Comparison union and one
  presentation component. The chart consumes only backend-provided Net
  Strategy, 沪深300, and Net Excess returns; a source boundary test forbids raw
  NAV, Benchmark Level, Initial Cash, and old Benchmark fields in the chart.
- Available Detail shows Snapshot identity, Coverage, publication time, Entry,
  Terminal, and three browser-rendered series. Unavailable Detail renders a
  status region and no comparison figure. The bounded 504-point DailyTrack
  test retains non-zero seed-relative values at its first visible point.
- Verification: `mise exec -- pnpm test` passed 684 backend tests, TypeScript
  typecheck, and 63 frontend tests. Focused Benchmark/lifecycle tests passed
  105 tests. Isolated Compose main phase
  `20260827t161221z-67644-c386b0da` passed 6 selected integration tests; the
  later restart phase had no selected tests under the same `-k` filter. Final
  isolated browser run `20260827t163159z-87225-f96c71f0` passed all 8 E2E
  scenarios and cleaned its containers and volumes.
- Initial Standards review findings were closed by updating the accessible E2E
  locator, observing all three series and both Detail unavailable paths in a
  real browser, and raising dense metadata typography to `DESIGN.md` limits.
  E2E also exposed and closed two stale fixtures: the controlled Worker now
  receives its required finalization calculator, and the 2026-08-11 Market
  Refresh replay carries the required append-only CSI 300 Open increment.
  Final Spec and Standards re-reviews were clean.
