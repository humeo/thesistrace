# 35 — Stop a DailyTrack irreversibly

**What to build:** Let a user permanently stop an active or blocked DailyTrack,
fence in-flight work, and retain its authoritative history.

**Blocked by:** 33.

**Status:** ready-for-agent

- [ ] Stop is accepted from `active` or `blocked` and records the terminal
  `stopped` state atomically.
- [ ] Stop advances the Track fence so late work cannot publish a visible
  Checkpoint or move Head.
- [ ] Disposable Working Cache is removed while Tracking Origin, committed
  Checkpoints, Head, and product history remain readable.
- [ ] A stopped Track does not count toward the active-or-blocked limit.
- [ ] Stopped cannot Retry, reactivate, or advance again.
- [ ] Matching request replay returns stopped; different input conflicts; a
  malformed request creates no receipt.
- [ ] The Web communicates that Stop is irreversible and shows the terminal
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
