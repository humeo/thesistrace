# 34 — Retry the same failed DailyTrack target

**What to build:** Let a user retry exactly the Dataset Release progression that
blocked a DailyTrack, then resume ordered catch-up only after that target
succeeds.

**Blocked by:** 29, 33.

**Status:** complete

**Implementation:** complete

- [x] Retry is accepted only for a blocked Track and always addresses its
  existing failed target.
- [x] It cannot select, skip to, or merge a newer Dataset Release.
- [x] Success moves Head to the original target, returns the Track to `active`,
  and makes the next direct successor eligible.
- [x] Another failure preserves `blocked`, its prior Head, and the same target.
- [x] Matching request replay returns the original action outcome; different
  input with the same request ID conflicts.
- [x] A structurally malformed Retry creates no action receipt.
- [x] The Web exposes Retry and its resulting product state without internal
  Attempt controls.

**How to verify:**

Run the ticket verification against real PostgreSQL and RustFS, then remove the
isolated runtime even if a check fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_daily_track_retry.py \
  tests/acceptance/test_core_daily_track_failure_isolation.py \
  tests/architecture/test_core_runtime_boundaries.py
bun run --cwd web typecheck
./scripts/core-test-runtime run bun run --cwd web test:e2e:core-shell -- \
  --grep "retries the same blocked DailyTrack target"
```

The acceptance test must first create a blocked Track with three failed
automatic Attempts at one direct-successor Dataset Release, publish at least
one newer successor, and persist a second independently blocked Track. `POST
/api/daily-tracks/{track_id}/retry` must accept only a structurally valid
`{"request_id":"..."}` for a currently blocked Track. It must not accept a
target, Release, Definition, or Run input. Missing Track returns 404; active
Track returns 409; malformed input returns 422 and creates no Retry receipt.

An accepted Retry must atomically make only the existing blocked progression
eligible again, clear the public blocked reason while work is active, and leave
Head unchanged. Before any later Release can be processed, one ordinary
`process_next()` call must move Head to the original failed target and return
the Track to `active`; only a subsequent call may process its next direct
successor. No new ResearchRun, merged progression, or latest-Release jump is
allowed.

Replaying the same request ID for the same Track and failed target, including
after constructing a fresh Core runtime, must return the originally stored
action outcome without creating another receipt or Attempt. Reusing that
request ID for another blocked Track must return 409. If the retried target
fails again, the Track must return to `blocked` after that Retry Attempt with
the same Head, target, and sanitized reason; it must not consume the newer
Release.

The named browser test must show Retry only on blocked detail, submit no target
selection, visibly transition through the accepted state, and prove the Head
first reaches the original failed Release before later ordered catch-up. It
must show a sanitized repeated failure with Retry still available and must not
render Attempt, fence, claim, receipt, manifest, object key, or worker controls.

## Comments

- The executable verification contract was specified in `cb326e0` before the
  implementation. The real PostgreSQL/RustFS TDD test initially failed at the
  absent DailyTrack Retry persistence/API boundary.
- Implemented in `a24a8ee`. The typed Retry command accepts only `request_id`;
  DailyTracks atomically reopens the persisted blocked Progression, clears the
  temporary public blocked state, and writes its module-owned idempotency
  receipt without changing Head or creating a ResearchRun.
- Real acceptance blocks two Tracks at the same direct successor, publishes a
  newer Release, and proves malformed, missing, active, replay, and cross-Track
  conflict behavior. A successful Retry advances first to the original failed
  target and only then to the newer successor. A failed Retry Attempt restores
  the same blocked Head, target, and sanitized reason. Fresh-runtime replay
  returns the stored outcome without another receipt or Attempt.
- The named browser test submits only a generated request ID, shows the accepted
  state, observes the Head at the original target before latest, and covers a
  repeated sanitized failure with Retry still available. It renders no target
  selector or internal execution controls.
- Independent review passed both Standards and Spec with no findings. It
  confirmed transaction/module ownership, fixed-target semantics, ordering,
  idempotency, restart behavior, no new ResearchRun, and the product-only Web
  surface.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: backend and architecture reported `22
  passed, 1 warning in 62.93s`; Web typecheck passed; the named browser test
  reported `1 passed in 5.2s`; the trap removed both runtime containers.
- Final repository verification passed with `make check`: Ruff passed; Pytest
  reported `533 passed, 106 skipped, 2 warnings in 1125.57s`; Web typecheck and
  production build passed (`1591` modules in `2.21s`); narrow E2E reported `1
  passed in 49.5s`; desktop E2E reported `1 passed in 45.1s`.
