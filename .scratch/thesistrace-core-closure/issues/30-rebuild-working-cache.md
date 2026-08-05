# 30 — Rebuild a missing or corrupt Working Cache

**What to build:** Rebuild disposable worker-local DailyTrack cache entirely
from PostgreSQL and verified immutable publications without changing product
truth.

**Blocked by:** 27.

**Status:** complete

**Implementation:** complete

- [x] Working Cache is private, latest-only, worker-local, bounded, and never an
  authoritative database or product resource.
- [x] Missing, corrupt, stale, or fence-mismatched cache content is discarded.
- [x] Tracking Origin and verified immutable Checkpoints are sufficient to
  rebuild the required continuation state.
- [x] Verified Publication failure prevents cache use and Head movement.
- [x] Restart does not make a local cache file authoritative.
- [x] No generic Working Cache port, physical path, or cache content enters the
  API or Web.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel/test_advance_contract.py \
  tests/architecture \
  tests/integration \
  tests/acceptance/test_core_daily_track_advance.py \
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

- Implemented through `0d91c41`. The worker-local cache remains disposable;
  cache misses rebuild only the bounded Alpha/Factor continuation from verified
  immutable Release and Checkpoint publications, while authoritative Strategy
  state is restored from the DailyTrack-owned compact Checkpoint.
- Rebuild selection is bounded by **525 actual Research Sessions**, including
  multi-session Releases and Track histories longer than 525 Checkpoints.
  Ordinary Advance and rebuild both consume the complete target Release, and a
  historical-correction regression test first proves the correction changes
  continuation and Strategy state before proving the two paths agree.
- Independent sixth-round review passed both Standards and Spec with no
  findings. Targeted non-Docker verification passed: Ruff passed and the
  Kernel, rebuild-selection, and architecture set reported `34 passed in
  92.36s`.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: backend `51 passed, 1 warning in
  423.02s`; Core browser `12 passed in 1.4m`; the command block then removed
  both runtime containers.
- Final repository verification passed with `make check`: Ruff passed; Pytest
  reported `533 passed, 100 skipped, 2 warnings in 765.00s`; Web typecheck and
  production build passed (`1590` modules in `1.49s`); narrow E2E reported `1
  passed in 40.8s`; desktop E2E reported `1 passed in 30.3s`.
