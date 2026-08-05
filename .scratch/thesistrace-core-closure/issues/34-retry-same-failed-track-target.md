# 34 — Retry the same failed DailyTrack target

**What to build:** Let a user retry exactly the Dataset Release progression that
blocked a DailyTrack, then resume ordered catch-up only after that target
succeeds.

**Blocked by:** 29, 33.

**Status:** ready-for-agent

- [ ] Retry is accepted only for a blocked Track and always addresses its
  existing failed target.
- [ ] It cannot select, skip to, or merge a newer Dataset Release.
- [ ] Success moves Head to the original target, returns the Track to `active`,
  and makes the next direct successor eligible.
- [ ] Another failure preserves `blocked`, its prior Head, and the same target.
- [ ] Matching request replay returns the original action outcome; different
  input with the same request ID conflicts.
- [ ] A structurally malformed Retry creates no action receipt.
- [ ] The Web exposes Retry and its resulting product state without internal
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
