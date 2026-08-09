# 18 — Recover DailyTrack without duplicate or partial history

**What to build:** Recover interrupted or blocked DailyTrack catch-up from its
last authoritative Checkpoint without publishing partial sessions, duplicating
accounting, trusting stale cache state, or blocking unrelated Tracks.

**Blocked by:** 17 — Start and catch up a DailyTrack from terminal state.

**Status:** ready-for-agent

- [ ] Failure partway through a multi-session Advance leaves Tracking Head and authoritative Checkpoints at the last successful boundary and exposes only a sanitized blocked state.
- [ ] Retry resumes from the last successful Checkpoint and ultimately publishes every later session exactly once, without duplicated cash changes, positions, costs, NAV, pending signals, or Rebalance phase.
- [ ] Lost or expired Worker ownership is fenced; a late Attempt cannot overwrite a retry success, newer Checkpoint, or terminal Stop.
- [ ] If Head moves while the Track is blocked or advancing, recovery selects and pins a current Generation and processes only the still-unpublished session frontier in order.
- [ ] Missing, corrupt, stale, over-limit, or fence-mismatched Working Cache is rebuilt from the authoritative Checkpoint and current Canonical Data, producing the same retained state as an intact control Track.
- [ ] An absent or unverifiable authoritative Checkpoint blocks progression even when a cache appears valid; no partial result can be promoted from cache alone.
- [ ] Persisted checkpoint progression remains canonically equivalent to the same Tracking Origin and session sequence through the pure Run/Advance contract.
- [ ] Real Core HTTP and Worker acceptance with PostgreSQL, RustFS, a temporary mount, mid-Advance failure, restart, cache-corruption, and fence barriers proves public Track state and authoritative Checkpoint outcomes without private call-count assertions; one failed Track does not block others and all waits use timeout-bounded polling.
