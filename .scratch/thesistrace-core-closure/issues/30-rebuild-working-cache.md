# 30 — Rebuild a missing or corrupt Working Cache

**What to build:** Rebuild disposable worker-local DailyTrack cache entirely
from PostgreSQL and verified immutable publications without changing product
truth.

**Blocked by:** 27.

**Status:** ready-for-agent

- [ ] Working Cache is private, latest-only, worker-local, bounded, and never an
  authoritative database or product resource.
- [ ] Missing, corrupt, stale, or fence-mismatched cache content is discarded.
- [ ] Tracking Origin and verified immutable Checkpoints are sufficient to
  rebuild the required continuation state.
- [ ] Verified Publication failure prevents cache use and Head movement.
- [ ] Restart does not make a local cache file authoritative.
- [ ] No generic Working Cache port, physical path, or cache content enters the
  API or Web.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/architecture \
  tests/integration \
  tests/acceptance/test_core_daily_track_cache_recovery.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS and invoke ordinary DailyTrack
worker processing. Starting from the same authoritative Tracking Origin and
ordered Release chain, they must delete the worker-local cache, corrupt its
bytes, replace it with an otherwise valid cache bound to an older Head or fence,
and create a fresh worker process with an empty local cache. Each case must
discard the unusable entry, rebuild only from the Origin plus verified immutable
Checkpoints, advance the direct successor, and produce the same canonical
Checkpoint and Head as an intact-cache control. Missing or unverifiable
Publication truth must fail without using cache content, recording another
Checkpoint, or moving Head. The cache must retain only one bounded latest entry
per Track and remain absent from PostgreSQL product tables, HTTP payloads,
stable URLs, and visible browser text; no generic cache endpoint, action, port,
or user-selectable physical path may be added.

## Comments
