# 28 — Catch up a DailyTrack in order

**What to build:** Let a lagging DailyTrack process every already-published
successor Dataset Release one at a time without skipping a boundary.

**Blocked by:** 27.

**Status:** ready-for-agent

- [ ] Each progression targets only the direct successor of the committed Head.
- [ ] A successful progression makes the following successor eligible until
  Head reaches the current latest Release.
- [ ] The Track never jumps directly to latest, merges targets, or skips a
  failed target.
- [ ] Every intermediate Checkpoint is independently committed and verified.
- [ ] A failure leaves Head at the last successful Release and stops catch-up at
  that exact target.
- [ ] Dataset publication catch-up and DailyTrack progression catch-up remain
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
