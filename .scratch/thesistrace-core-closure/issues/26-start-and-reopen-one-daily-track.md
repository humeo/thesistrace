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

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_daily_track_activation.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The tests must use real PostgreSQL and RustFS to reject queued, running, failed,
cancelled, missing, unreadable, and incomplete seed Runs; activate from one
verified succeeded Result; and reopen after fresh HTTP and worker processes.
They must prove same-transaction Run validation plus private DailyTrack
activation, direct `active` state, complete copied Tracking Origin, no later
Definition/ResearchRun dependency, matching-request replay, different-input
conflict, malformed zero receipt, and absence of generic create/delete routes.
The browser must Start Tracking from the succeeded ResearchRun, navigate to the
stable DailyTrack URL, reopen it, and expose only product origin/state without
Activation, Checkpoint, manifest, object, receipt, or worker mechanics.

## Comments
