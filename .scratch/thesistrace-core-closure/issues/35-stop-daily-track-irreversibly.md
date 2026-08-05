# 35 — Stop a DailyTrack irreversibly

**What to build:** Let a user permanently stop an active or blocked DailyTrack,
fence in-flight work, and retain its authoritative history.

**Blocked by:** 33, 36.

**Status:** ready-for-agent

**Implementation:** complete; final limit criterion awaits Ticket 36

- [x] Stop is accepted from `active` or `blocked` and records the terminal
  `stopped` state atomically.
- [x] Stop advances the Track fence so late work cannot publish a visible
  Checkpoint or move Head.
- [x] Disposable Working Cache is removed while Tracking Origin, committed
  Checkpoints, Head, and product history remain readable.
- [ ] A stopped Track does not count toward the active-or-blocked limit.
- [x] Stopped cannot Retry, reactivate, or advance again.
- [x] Matching request replay returns stopped; different input conflicts; a
  malformed request creates no receipt.
- [x] The Web communicates that Stop is irreversible and shows the terminal
  state after refresh and restart.

**How to verify:**

Run the ticket verification against real PostgreSQL and RustFS, then remove the
isolated runtime even if a check fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_daily_track_stop.py \
  tests/acceptance/test_core_daily_track_recovery.py \
  tests/architecture/test_core_runtime_boundaries.py
bun run --cwd web typecheck
./scripts/core-test-runtime run bun run --cwd web test:e2e:core-shell -- \
  --grep "stops a DailyTrack irreversibly"
```

The acceptance test must stop one active Track with a committed Head and local
Working Cache, stop one blocked Track, and race Stop against a third Track whose
progression has prepared its result but has not published. `POST
/api/daily-tracks/{track_id}/stop` accepts only `{"request_id":"..."}`. Missing
Track returns 404; malformed input returns 422 without a Stop receipt.

For active and blocked Tracks, Stop must atomically persist `stopped`, advance
the execution fence, cancel any unfinished progression and live Attempt, and
leave Tracking Origin, Head, committed Checkpoint rows, and readable detail
unchanged. The worker-local cache file must be absent after the action. The
prepared late worker must be fenced: after it resumes, Publication count,
Checkpoint count, Head, and stopped state remain unchanged.

The acceptance test must also construct an independently rooted worker-local
cache rather than treating the HTTP runtime's cache directory as the worker's
disk. After HTTP Stop, ordinary worker reconciliation must delete that cache
idempotently. A worker paused after durable Checkpoint publication but before
cache installation must not restore a cache after Stop; after it resumes, its
post-install status/fence check or the next reconciliation removes the entry.

After Stop, publishing at least one later Dataset Release and running ordinary
workers must not claim, Retry, reactivate, or move the stopped Track. Matching
request replay, including after constructing a fresh Core runtime, must return
the originally stored stopped outcome without changing the fence or receipt
count. Reusing that request ID for another Track returns 409. Another Stop with
a new request ID and every Retry on a stopped Track return 409.

The named browser test must state that Stop is irreversible before submission,
show the terminal stopped status at the same stable URL after acceptance,
remove both Stop and Retry actions, survive reload, and keep the same Head after
a later Data Release. It must not render Attempt, fence, claim, receipt,
manifest, object key, cache path, or worker controls.

## Comments

- The executable verification contract was specified in `c8119fe` before the
  implementation. Stop was implemented in `3307e06`; `31f881e` added the
  prepared-worker race, malformed/conflict/restart evidence, and the named Web
  proof.
- Review round 1 passed neither axis: Standards found one P2 in the real
  HTTP/worker cache topology, while Spec found that same cache gap plus two Web
  timing/URL P2s. `c489d6b` made each worker reconcile its independently rooted
  cache from durable stopped state, added a post-publication status/fence
  check, retried cleanup on replay, switched the mocked later Release only
  after Stop acceptance, and captured the stable URL before submission.
- Review round 2 passed Standards and Spec with zero findings. It confirmed the
  independently owned cache cleanup, both late-worker boundaries, idempotent
  replay, later-Release ordering, and stable URL behavior.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: backend and architecture reported `28
  passed, 1 warning in 138.96s`; Web typecheck passed; the named browser test
  reported `1 passed in 4.0s`; both runtime containers were removed afterward.
- Full repository verification passed with `make check`: Ruff passed; Pytest
  reported `533 passed, 111 skipped, 2 warnings in 631.96s`; Web typecheck and
  production build passed (`1591` modules in `1.27s`); narrow and desktop E2E
  each reported `1 passed in 31.9s`.
- The one unchecked criterion is intentionally not claimed early: actual
  active-or-blocked admission counting is Ticket 36. Ticket 35 has established
  the terminal `stopped` state that Ticket 36 must exclude; close this ticket
  only after the tenth/eleventh/stopped-capacity acceptance passes there.
