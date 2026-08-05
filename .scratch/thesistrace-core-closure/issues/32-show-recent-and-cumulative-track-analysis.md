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

Run the ticket verification against real PostgreSQL and RustFS, then remove the
isolated runtime even if a check fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_daily_track_detail.py \
  tests/architecture/test_core_runtime_boundaries.py
bun run --cwd web typecheck
./scripts/core-test-runtime run bun run --cwd web test:e2e:core-shell -- \
  --grep "shows recent and cumulative DailyTrack analysis"
```

The acceptance test must build one persisted Track history with more than 504
Research Sessions and prove all of the following from `GET
/api/daily-tracks/{track_id}` before and after constructing a fresh Core runtime:

- each 1-, 5-, and 20-session Factor Summary reports exactly the latest 504
  valid signal sessions, rather than a 504-Release or latest-Run window;
- the Strategy and selected-Universe Benchmark observations contain exactly the
  latest 504 Research Sessions in ascending session order, with the first older
  observation excluded;
- the cumulative Strategy summary is unchanged when the recent observation
  window is truncated and remains anchored to the persisted Tracking Origin;
- the Benchmark universe and methodology come from this Track's immutable
  input, and another Run or Track cannot supply them;
- status, complete Tracking Origin product projection, current Head Release,
  and zero/non-zero lag are returned, while Checkpoint, Generation, Advance,
  Attempt, manifest, object key, and raw continuation terms and values are not.

The named browser test must visibly exercise initial loading, successful detail,
manual Refresh, empty recent analysis, sanitized error with Retry, and a page
reload. It must assert the status, Tracking Origin, Head Release, lag, all three
Factor horizons, cumulative Strategy metrics, selected-Universe Benchmark, and
the 504-session chart without exposing internal mechanics.

## Comments
