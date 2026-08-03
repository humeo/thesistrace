# 26 — Start and reopen one DailyTrack

**What to build:** Start one DailyTrack from a succeeded ResearchRun and reopen
it later without any continuing dependency on the Definition or Run lifecycle.

**Blocked by:** 21.

**Status:** ready-for-agent

- [ ] Only a succeeded Run with a complete verified Result may Start Tracking.
- [ ] ResearchRuns validates its own Run, then calls private
  DailyTrack activation inside the same PostgreSQL transaction.
- [ ] Activation stores the complete Tracking Origin: seed identity, immutable
  input, seed Release, verified Result reference and checksum, initial Strategy
  state, and calculation contracts.
- [ ] Successful activation creates an `active` Track directly; queued and
  running activation state never becomes a product lifecycle.
- [ ] DailyTracks owns its schema, migrations, SQL, and Tracking Origin without
  ResearchRuns querying its tables.
- [ ] After activation the Track never reads Definition or ResearchRun again.
- [ ] DailyTrack has no generic create or delete operation; Start Tracking on a
  succeeded ResearchRun is its only product activation path.
- [ ] The stable list/detail page survives restart and exposes no Activation
  Checkpoint or other internal object.

**How to verify:**

- Run `uv run pytest -q tests/integration tests/acceptance` for one successful
  activation, complete Origin, direct `active` state, reopen, and restart.
- Run `bun run --cwd web test:e2e` and confirm Start Tracking navigates from the
  succeeded Run to one reopenable DailyTrack URL.

## Comments
