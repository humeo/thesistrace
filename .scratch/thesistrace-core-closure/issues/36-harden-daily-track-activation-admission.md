# 36 — Harden DailyTrack activation admission

**What to build:** Make Start Tracking concurrency-safe, idempotent, and
bounded after the first DailyTrack activation path already works.

**Blocked by:** 26.

**Status:** complete

**Implementation:** complete

- [x] ResearchRuns records its Start Tracking receipt and calls private
  DailyTrack activation in one PostgreSQL transaction; failure leaves neither a
  receipt nor a partial Track.
- [x] DailyTracks enforces one Track per seed ResearchRun under concurrent
  activation without ResearchRuns reading DailyTrack tables.
- [x] Activation is allowed when the current active-or-blocked count is below
  ten, the tenth Track succeeds, and the eleventh is rejected; stopped Tracks
  do not count.
- [x] Matching request replay returns the originally activated DailyTrack.
- [x] Reusing a request ID with different action input returns a conflict, and a
  structurally malformed request creates no receipt.
- [x] Duplicate-seed, limit, replay, conflict, and rollback outcomes are visible
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

The same acceptance file must construct a pre-cutover DailyTracks-owned Start
Tracking receipt and prove that canonical runtime startup moves its identity,
fingerprint, outcome, and creation time into ResearchRuns, deletes the legacy
row only after the move succeeds, and preserves replay/conflict behavior after
another restart. If an identical ResearchRuns receipt already exists, startup
accepts it and removes the legacy copy. If the same request ID has incompatible
stored identity or outcome, startup must fail explicitly and the transaction
must preserve the legacy row.

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

- The executable verification contract was committed first in `2d152c8`.
  `0736e79` implemented ResearchRuns-owned receipts, the atomic private
  DailyTracks activation seam, unique-seed concurrency, the active-or-blocked
  limit, stopped exclusion, and the product-safe Web outcomes.
- Review round 1 found two P2 gaps: legacy DailyTracks receipts were not moved,
  and the browser test did not model acceptance before response loss.
  `0fb3343` added upgrade/restart coverage and an accepted-first browser model.
- Review round 2 found that the first cutover fix used cross-module SQL, was not
  collision-safe, and left `StartTrackingCommand` in DailyTracks. `1ce7e6d`
  removed the extra schema, made runtime assembly coordinate one transaction
  through module-owned SQL, serialized concurrent startup, accepted identical
  collisions, rejected incompatible collisions without deleting legacy data,
  and moved the request model to ResearchRuns. `99599cc` added these cases to
  **How to verify**.
- Review round 3 passed Standards and Spec with zero findings. It confirmed SQL
  ownership, transaction rollback/delete ordering, fingerprint compatibility,
  startup serialization, admission concurrency and browser accepted-first
  replay.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: backend and architecture reported `25
  passed, 1 warning in 22.17s`; Web typecheck passed; the named browser test
  reported `1 passed in 4.2s`; both runtime containers were removed afterward.
- Full repository verification passed with `make check`: Ruff passed; Pytest
  reported `534 passed, 115 skipped, 2 warnings in 764.65s`; Web typecheck and
  production build passed (`1591` modules in `1.33s`); narrow E2E reported `1
  passed in 31.9s` and desktop E2E reported `1 passed in 25.4s`.
