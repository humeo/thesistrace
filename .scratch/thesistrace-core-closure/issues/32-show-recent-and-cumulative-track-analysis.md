# 32 — Show recent and cumulative DailyTrack analysis

**What to build:** Present the bounded recent analysis and fixed-origin
cumulative Strategy view on DailyTrack detail.

**Blocked by:** 27.

**Status:** ready-for-agent

- [ ] Detail shows status, Tracking Origin, current Head Release, and lag or a
  readable blocked reason.
- [ ] Factor Summary uses the latest 504 valid signal sessions for each required
  horizon.
- [ ] Strategy and its selected-Universe Benchmark chart use the latest 504
  Research Sessions.
- [ ] Cumulative Strategy metrics remain measured from the fixed Tracking
  Origin rather than the recent chart window.
- [ ] The Benchmark belongs to this Track's Strategy and is not a cross-Run or
  cross-Track comparison.
- [ ] Checkpoint chain, Generation, Advance, Attempt, manifest, object key, and
  raw continuation state are not returned.
- [ ] The page has observable loading, refresh, success, empty, and error states
  and reopens after process restart.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` with history longer
  than both retained windows and verify the two different cutoffs plus
  origin-based cumulative metrics.
- Run `bun run --cwd web typecheck` and `bun run --cwd web test:e2e`; refresh the
  Track detail and inspect the visible status, Head, Factor, and Strategy views.

## Comments
