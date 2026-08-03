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

- Run `uv run pytest -q tests/integration tests/acceptance` after deleting,
  corrupting, and replacing the cache with stale-fence data.
- Continue one progression and confirm the rebuilt path reaches the expected
  next Head without changing prior authoritative state.

## Comments
