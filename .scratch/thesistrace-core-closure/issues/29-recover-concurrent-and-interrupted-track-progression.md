# 29 — Recover concurrent and interrupted Track progression

**What to build:** Recover DailyTrack progression after duplicate workers,
stale claims, or process restart without publishing the same target twice.

**Blocked by:** 28.

**Status:** complete

**Implementation:** complete

- [x] PostgreSQL permits only one live owner for a Track and target Release.
- [x] Two workers cannot publish or move Head for the same progression twice.
- [x] A stale worker cannot move Head after its claim or fence is replaced.
- [x] Worker restart recovers eligible unfinished work from durable Track and
  progression state.
- [x] Recovery advances Head at most once for each target and then resumes
  ordered catch-up.
- [x] Claim, Attempt, fence, and recovery fields remain absent from DailyTrack
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

- Implemented in `6e4a18d`, aligned with the accepted Attempt lifecycle in
  `31f9de8`, and strengthened browser no-leak coverage in `c52d282`.
  DailyTracks owns `progression_attempts`; a partial PostgreSQL unique index
  permits one `running` Attempt for one `(Track, target Release)`, while the
  existing progression primary key preserves one durable work identity across
  replacement Attempts.
- Each claim records its ordinal, fence, heartbeat, and lease privately. A live
  worker renews only while its Track, progression, and Attempt fences all remain
  current. An expired owner becomes a `failed` Attempt with the internal
  `WorkerLost` reason, then recovery increments the same progression's fence and
  creates its next Attempt. The accepted
  `queued -> running -> succeeded | failed | cancelled` state set is retained
  for later blocked Retry and Stop work.
- Success locks and validates the Track, progression, and exact Attempt before
  calling `Publication.record`; the Publication reference, immutable
  Checkpoint, Head movement, progression success, and Attempt success commit in
  one PostgreSQL transaction. A stale prepared service uses an independent spy
  and proves `record_calls == 0`, not merely one content-addressed manifest.
- Real acceptance constructs both succeeded and running `0002` progressions,
  lets a fresh runtime apply final `0003`, verifies the backfilled ordinal,
  fence, lease, finish state, and then recovers the running progression. Other
  scenarios prove process restart resumes the interrupted direct successor
  before the later one, a heartbeat prevents a duplicate live claim, stale
  prepared work is fenced, repeated delivery is a no-op, and every target has
  exactly one Checkpoint and Head movement.
- DailyTrack list and detail acceptance assert their complete exact key sets.
  The real browser opens both list and stable detail views and rejects internal
  mechanics with a non-alphanumeric boundary that detects snake_case fields
  such as `attempt_id`, `execution_fence`, `manifest_sha256`, and `object_key`
  without falsely matching the product term `Dataset Release`.
- Independent review required three rounds. The first found one P1 Attempt
  lifecycle conflict plus three P2 gaps for upgrade proof, stale Publication
  proof, and API/Web no-leak assertions. The second passed Standards but found
  one remaining P2 because JavaScript word boundaries miss underscores. The
  third review passed both Standards and Spec with no material findings. It
  retained only non-blocking test-name, string-stage, and duplicated-helper
  smells.
- Final verification was run exactly from **How to verify** and passed: backend
  `19 passed, 1 warning in 111.80s`; real Core browser `12 passed in 1.6m`;
  PostgreSQL and RustFS were then removed by the command block.
- Final repository verification passed with `make check`: Ruff passed; pytest
  reported `523 passed, 96 skipped, 2 warnings in 541.03s`; Web typecheck and
  production build passed (`1590` modules in `1.42s`); narrow E2E reported
  `1 passed in 36.0s`; desktop E2E reported `1 passed in 35.1s`.
