# 29 — Recover concurrent and interrupted Track progression

**What to build:** Recover DailyTrack progression after duplicate workers,
stale claims, or process restart without publishing the same target twice.

**Blocked by:** 28.

**Status:** ready-for-agent

- [ ] PostgreSQL permits only one live owner for a Track and target Release.
- [ ] Two workers cannot publish or move Head for the same progression twice.
- [ ] A stale worker cannot move Head after its claim or fence is replaced.
- [ ] Worker restart recovers eligible unfinished work from durable Track and
  progression state.
- [ ] Recovery advances Head at most once for each target and then resumes
  ordered catch-up.
- [ ] Claim, Attempt, fence, and recovery fields remain absent from DailyTrack
  list and detail.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_daily_track_recovery.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS with independently assembled
workers sharing the same durable state. They must force duplicate concurrent
claims, expire and replace a live owner's claim or fence before its prepared
publication returns, and construct unfinished durable progression state before
creating a fresh worker runtime. They must prove only one owner can remain live
for one Track and target, a stale owner cannot record a Publication, Checkpoint,
or Head movement, restart recovers the same target without creating a second
progression identity, and repeated delivery becomes a no-op after exactly one
Checkpoint and one Head movement. With a later Release already published,
recovery must finish the interrupted target first and then resume direct-
successor catch-up in order. DailyTrack list, detail, and browser views must
remain usable while exposing none of the claim, Attempt, lease, fence,
publication, Checkpoint, recovery, or worker mechanics.

## Comments
