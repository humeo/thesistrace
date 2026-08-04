# 28 — Catch up a DailyTrack in order

**What to build:** Let a lagging DailyTrack process every already-published
successor Dataset Release one at a time without skipping a boundary.

**Blocked by:** 27.

**Status:** complete

**Implementation:** complete

- [x] Each progression targets only the direct successor of the committed Head.
- [x] A successful progression makes the following successor eligible until
  Head reaches the current latest Release.
- [x] The Track never jumps directly to latest, merges targets, or skips a
  failed target.
- [x] Every intermediate Checkpoint is independently committed and verified.
- [x] A failure leaves Head at the last successful Release and stops catch-up at
  that exact target.
- [x] Dataset publication catch-up and DailyTrack progression catch-up remain
  separate concepts and neither waits for the other.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_daily_track_catch_up.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS to activate a Track at one seed
Release, publish at least three ordered successors before progressing the
Track, and invoke ordinary Core worker processing without a manual catch-up
endpoint or control. They must observe the stable DailyTrack detail move through
each direct successor in order, never jump to latest or merge targets, verify
one independently committed immutable Checkpoint per intermediate Release, and
prove repeated processing becomes a no-op only after Head reaches latest. A
deterministic failure at the middle target must leave Head at the last successful
Release, keep that exact failed target ahead of newer already-published Releases,
and stop this Track from processing later targets while Data publication remains
complete and independently readable. The browser must publish multiple later
Releases through Data and observe the existing Track catch up in order on its
stable URL without exposing Checkpoint, progression, claim, fence, or worker
mechanics.

## Comments

- Implemented in `88d1511` and corrected in `41cd443`. The ordinary worker now
  drains an available DailyTrack backlog by repeatedly invoking the existing
  one-successor progression. Each invocation still derives the direct successor
  from the committed Head and commits its own immutable Checkpoint before the
  following successor becomes eligible; no latest-Release target or merged
  catch-up operation was added.
- Expected kernel or publication failures are converted to a typed
  `DailyTrackProgressionFailed` boundary. The worker stops that catch-up pass at
  the exact failed target without killing its daemon loop. Acceptance coverage
  proves a later Data update can still publish while the failed Track retains
  its last successful Head and exact target.
- The fixture data adapter accepts a deterministic ordered availability
  sequence only through test/runtime assembly; its default one-boundary
  behavior remains unchanged. Browser assembly publishes three real successors
  and observes the same stable DailyTrack URL visit every successor without
  exposing Checkpoint, progression, claim, fence, or worker mechanics.
- The first independent two-axis review found two P1 gaps: an expected Track
  failure could terminate the shared worker, and the browser only exercised one
  successor. Commit `41cd443` fixed both. The second review passed Standards and
  Spec with no blocking findings. It retained only non-blocking test-code smells:
  duplicated acceptance helpers and a stale first browser-test name.
- Final ticket verification was run exactly from **How to verify** and passed:
  backend `83 passed, 1 warning in 309.79s`; real Core browser `12 passed in
  2.2m`; the command then removed the PostgreSQL and RustFS test containers.
- Final repository verification passed with `make check`: Ruff passed; pytest
  reported `523 passed, 92 skipped, 2 warnings in 1045.73s`; Web typecheck and
  production build passed; narrow E2E reported `1 passed in 1.4m`; desktop E2E
  reported `1 passed in 1.2m`. An earlier sandboxed attempt reached passing
  Python/typecheck/build but could not bind `127.0.0.1:5273` (`listen EPERM`);
  the complete recorded run was therefore repeated with local-listen permission
  and exited successfully.
