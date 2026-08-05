# 44 — Remove legacy DailyTrack and cache paths

**What to build:** Delete old Tracking lifecycle, scheduler, and cache callers
after the DailyTracks module owns activation, progression, recovery, Retry, and
Stop.

**Blocked by:** 43.

**Status:** ready-for-agent

- [ ] Old Tracking, Advance, Checkpoint, Generation, Attempt, scheduler, and
  manual progression product paths are removed.
- [ ] Legacy tracking callers and tests are removed or migrated to the canonical
  DailyTrack product contract.
- [ ] The old global Working Cache abstraction and authoritative-cache behavior
  are removed.
- [ ] Canonical worker-local disposable cache and immutable Checkpoint truth
  remain unchanged.
- [ ] No fallback can activate, advance, retry, stop, or reopen a Track outside
  the DailyTracks module.
- [ ] Removing legacy tracking does not remove shared quantitative behavior now
  owned by the Research Kernel.

**How to verify:**

```sh
set -eu

for removed_path in \
  src/thesistrace/tracking.py \
  src/thesistrace/tracking_operations.py \
  src/thesistrace/working_cache.py \
  tests/acceptance/test_daily_tracking.py \
  tests/acceptance/test_incremental_working_cache.py \
  tests/acceptance/test_revised_v1_product_chain.py \
  tests/acceptance/test_working_cache_activation.py \
  tests/acceptance/test_working_cache_fencing.py \
  tests/acceptance/test_working_cache_recovery.py \
  tests/acceptance/test_working_cache_stop.py \
  tests/kernel/test_tracking_equivalence.py
do
  test ! -e "$removed_path"
done

if rg -n \
  --glob '!docs/adr/*.md' \
  --glob '!docs/research/*.md' \
  --glob '!docs/archive/*.md' \
  --glob '!web/node_modules/**' \
  --glob '!web/dist/**' \
  'thesistrace\.(tracking|tracking_operations|working_cache)|DailyTrackingService|TrackingOperationService|WorkingCache(Store|Port)|/api/v1/daily-tracks' \
  pyproject.toml uv.lock Makefile src scripts tests web
then
  echo 'Legacy Tracking or global Working Cache remains reachable' >&2
  exit 1
fi

if rg -n 'working_cache_root' \
  src/thesistrace/config.py \
  src/thesistrace/runtime.py \
  tests/acceptance/test_runtime_ports.py
then
  echo 'Legacy global Working Cache configuration remains' >&2
  exit 1
fi

test -f src/thesistrace/daily_track/cache.py
test -f src/thesistrace/daily_track/checkpoint.py
test -f src/thesistrace/daily_track/service.py

uv run pytest -q tests/kernel tests/architecture

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/integration tests/acceptance/test_core_daily_track_*.py
./scripts/core-test-runtime run bun run --cwd web test:e2e
```

## Comments
