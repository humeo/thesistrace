# 26 — Start and reopen one DailyTrack

**What to build:** Start one DailyTrack from a succeeded ResearchRun and reopen
it later without any continuing dependency on the Definition or Run lifecycle.

**Blocked by:** 21.

**Status:** complete

**Implementation:** complete

- [x] Only a succeeded Run with a complete verified Result may Start Tracking.
- [x] ResearchRuns validates its own Run, then calls private
  DailyTrack activation inside the same PostgreSQL transaction.
- [x] Activation stores the complete Tracking Origin: seed identity, immutable
  input, seed Release, verified Result reference and checksum, initial Strategy
  state, and calculation contracts.
- [x] Successful activation creates an `active` Track directly; queued and
  running activation state never becomes a product lifecycle.
- [x] DailyTracks owns its schema, migrations, SQL, and Tracking Origin without
  ResearchRuns querying its tables.
- [x] After activation the Track never reads Definition or ResearchRun again.
- [x] DailyTrack has no generic create or delete operation; Start Tracking on a
  succeeded ResearchRun is its only product activation path.
- [x] The stable list/detail page survives restart and exposes no Activation
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

- `POST /api/research-runs/{run_id}/daily-tracks` is the only activation path.
  ResearchRuns validates its own succeeded Run and complete verified published
  Result, then passes a complete private `TrackingOrigin` to DailyTracks inside
  the same PostgreSQL transaction. There is no generic create or delete route.
- The persisted Origin copies the immutable input, seed Dataset Release,
  Definition identity and revision, private Result manifest reference and
  checksum, complete terminal Strategy state, and calculation contracts. A
  Track is created directly as `active` and can reopen after its source
  Definition and ResearchRun have been deleted.
- DailyTracks owns its migrations, tables, SQL, idempotency receipts, and
  activation locks. ResearchRuns calls only private DailyTrack service seams
  and never queries `daily_tracks.*`; Publication verification reuses the
  caller transaction rather than opening a second pooled connection.
- Receipt resolution happens before source-Run validation. A matching request
  replays even if the source has since disappeared, while reuse for another
  source conflicts before missing/status validation. Temporary PostgreSQL,
  pool, or object-store failures return `503`; deterministic ineligible or
  damaged Results return `409`; unexpected programming failures propagate.
- The Web starts from a succeeded ResearchRun, navigates to a stable DailyTrack
  URL, and reopens it from the list. It exposes product origin and state only,
  not Activation, Checkpoint, receipt, manifest, object, or worker mechanics.
- The final ticket backend command written above passed `16 passed, 1 warning`
  in `15.47s` against real PostgreSQL and RustFS. The final Core browser command
  passed `12 passed` in `35.8s`; the command's final `down` removed the isolated
  containers.
- Independent review passed `Standards: PASS` and `Spec: PASS` with no final
  findings. The first review identified receipt ordering, missing private
  manifest provenance, nested pool use, and over-broad exception handling;
  commit `38b171b` fixed all four and added direct regression coverage.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `522 passed, 90 skipped, 2 warnings` in `459.11s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `24.9s` and
  `28.9s`.
