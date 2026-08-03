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

- Run `uv run pytest -q tests/architecture tests/integration tests/acceptance`
  and exercise Track activation through Stop with only canonical modules.
- Inspect remaining entrypoints and imports; no legacy tracking or global cache
  caller may remain reachable.

## Comments
