# 03 — Render the fixed CSI 300 Strategy Comparison

**What to build:** Render the backend-assembled comparison consistently in
ResearchRun and DailyTrack Detail without financial calculations in the browser.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] Both Detail contracts expose the same available/unavailable Comparison union.
- [ ] Available metadata identifies 沪深300, Snapshot SHA-256, Coverage, publication time, Entry, and Terminal.
- [ ] The chart begins at Entry Open and plots Net Strategy, 沪深300, and Net Excess without a pre-entry segment.
- [ ] DailyTrack's bounded recent window does not reset the seed baseline.
- [ ] The UI shows “沪深300” and “数据截至 YYYY-MM-DD”.
- [ ] Unavailable comparison shows a clear state and never draws a Strategy-only comparison.
- [ ] Existing `strategy.summary.metrics.annualized_excess_return` and list key metric paths remain unchanged.
- [ ] TypeScript contract, components, ResearchRun, DailyTrack, 504-point, unavailable, and no-browser-formula tests pass.
