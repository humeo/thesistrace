# 32 — Show recent and cumulative DailyTrack analysis

**What to build:** Present the bounded recent analysis and fixed-origin
cumulative Strategy view on DailyTrack detail.

**Blocked by:** 27.

**Status:** complete

**Implementation:** complete

- [x] Detail shows status, Tracking Origin, current Head Release, and lag or a
  readable blocked reason.
- [x] Factor Summary uses the latest 504 valid signal sessions for each required
  horizon.
- [x] Strategy and its selected-Universe Benchmark chart use the latest 504
  Research Sessions.
- [x] Cumulative Strategy metrics remain measured from the fixed Tracking
  Origin rather than the recent chart window.
- [x] The Benchmark belongs to this Track's Strategy and is not a cross-Run or
  cross-Track comparison.
- [x] Checkpoint chain, Generation, Advance, Attempt, manifest, object key, and
  raw continuation state are not returned.
- [x] The page has observable loading, refresh, success, empty, and error states
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

- The executable verification contract was specified in `87a8e95` before the
  implementation. TDD then failed at the missing DailyTrack detail projection
  and missing visible Head Release before the backend and Web work was added.
- Implemented in `bcb156e`, with proof-boundary corrections in `aaae4f2` and
  complete visible cumulative-metric assertions in `e714875`. DailyTrack owns
  its analysis view; ResearchRun remains independent and no shared product
  module or cross-Run comparison was introduced.
- Real PostgreSQL/RustFS acceptance constructs more than 504 sessions and
  independently replays the persisted Tracking Origin through the pure Research
  Kernel. It proves exact session identities, summaries, and coverage for the
  1-, 5-, and 20-session Factor horizons; exact 504-session Strategy/Benchmark
  observations; fixed-origin cumulative metrics; Track-owned Benchmark input;
  internal-field exclusion; lag; and restart equality.
- The focused DailyTrack detail test passed (`1 passed, 1 warning in 112.90s`).
  Related cache, catch-up, recovery, equivalence, activation, advance, Kernel,
  architecture, typecheck, and real browser regressions also passed.
- Independent final review passed both Standards and Spec with no findings. It
  specifically confirmed module ownership, exact Factor session boundaries,
  fixed-origin cumulative proof, and visible assertions for all six cumulative
  metrics.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: backend and architecture reported `20
  passed, 1 warning in 104.14s`; Web typecheck passed; the named browser test
  reported `1 passed in 9.6s`; the trap removed the runtime containers.
- Final repository verification passed with `make check`: Ruff passed; Pytest
  reported `533 passed, 103 skipped, 2 warnings in 834.52s`; Web typecheck and
  production build passed (`1591` modules in `2.26s`); narrow E2E reported `1
  passed in 38.8s`; desktop E2E reported `1 passed in 35.4s`.
