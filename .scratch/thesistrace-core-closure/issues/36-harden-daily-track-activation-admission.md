# 36 — Harden DailyTrack activation admission

**What to build:** Make Start Tracking concurrency-safe, idempotent, and
bounded after the first DailyTrack activation path already works.

**Blocked by:** 26.

**Status:** ready-for-agent

- [ ] ResearchRuns records its Start Tracking receipt and calls private
  DailyTrack activation in one PostgreSQL transaction; failure leaves neither a
  receipt nor a partial Track.
- [ ] DailyTracks enforces one Track per seed ResearchRun under concurrent
  activation without ResearchRuns reading DailyTrack tables.
- [ ] Activation is allowed when the current active-or-blocked count is below
  ten, the tenth Track succeeds, and the eleventh is rejected; stopped Tracks
  do not count.
- [ ] Matching request replay returns the originally activated DailyTrack.
- [ ] Reusing a request ID with different action input returns a conflict, and a
  structurally malformed request creates no receipt.
- [ ] Duplicate-seed, limit, replay, conflict, and rollback outcomes are visible
  as product action results without exposing transaction or Activation
  Checkpoint internals.

**How to verify:**

Run the ticket verification against real PostgreSQL and RustFS, then remove the
isolated runtime even if a check fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_daily_track_activation_admission.py \
  tests/acceptance/test_core_daily_track_activation.py \
  tests/architecture/test_core_runtime_boundaries.py
bun run --cwd web typecheck
./scripts/core-test-runtime run bun run --cwd web test:e2e:core-shell -- \
  --grep "handles Start Tracking replay and active limit"
```

The acceptance tests must use the product action `POST
/api/research-runs/{run_id}/daily-tracks` with only
`{"request_id":"..."}`. They must prove that ResearchRuns owns the Start
Tracking receipt while DailyTracks owns the unique `seed_run_id` Track row and
all activation SQL. Matching replay returns the original Track without another
row or receipt; cross-Run request-ID reuse returns 409; malformed input returns
422 without a receipt. Concurrent requests for one previously untracked seed
must all return the same single Track. An injected failure after private
DailyTrack activation but before the outer transaction commits must leave no
Track and no ResearchRuns receipt.

For admission capacity, first persist nine active-or-blocked Tracks, including
at least one blocked Track. Race two different eligible seed Runs for the final
slot: exactly one becomes the tenth Track and the other returns 409 with a
product-safe limit result. The database must contain exactly ten active or
blocked Tracks and no receipt or partial Track for the rejected Run. Stop one
of those Tracks through the product Stop action, retry the rejected seed with a
new request ID, and prove it now succeeds as the tenth active-or-blocked Track;
the stopped Track remains readable but is excluded from the count.

The named browser test must simulate a response lost after the server accepted
Start Tracking, retry from the same Run detail with the same request ID, and
navigate to the originally created Track without a duplicate. It must also
show the active-limit outcome on a succeeded Run without navigating or creating
a partial DailyTrack. Neither outcome may expose transaction, receipt, unique
constraint, lock, quota-profile, checkpoint, manifest, object, worker, or
deployment internals.

## Comments
