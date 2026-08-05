# 33 — Block one failed DailyTrack independently

**What to build:** Move only the affected DailyTrack to blocked after its
automatic progression retries are exhausted while Data and other Tracks keep
working.

**Blocked by:** 28.

**Status:** complete

**Implementation:** complete

- [x] Exhausted automatic retry changes the affected Track to `blocked`, records
  a sanitized readable reason, and preserves its last successful Head.
- [x] Its current failed target remains fixed even when newer Releases appear.
- [x] Data continues to publish later Dataset Releases without waiting for the
  blocked Track.
- [x] Other active DailyTracks continue to discover and advance successor
  Releases.
- [x] Process restart preserves enough PostgreSQL and Publication truth to
  retry or stop the blocked Track.
- [x] The Web shows blocked status and reason without exposing Attempt, claim,
  or worker diagnostics.

**How to verify:**

Run the ticket verification against real PostgreSQL and RustFS, then remove the
isolated runtime even if a check fails:

```sh
set -eu
./scripts/core-test-runtime reset
trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime run uv run pytest -q \
  tests/acceptance/test_core_daily_track_failure_isolation.py \
  tests/acceptance/test_core_daily_track_catch_up.py \
  tests/architecture/test_core_runtime_boundaries.py
bun run --cwd web typecheck
./scripts/core-test-runtime run bun run --cwd web test:e2e:core-shell -- \
  --grep "blocks one failed DailyTrack independently"
```

The acceptance test must activate two independent Tracks at the same Head,
publish their direct successor, and inject a deterministic Kernel failure only
for the first Track at that Release. Ordinary worker processing must make at
most three automatic Attempts for that exact `(track_id, target_release_id)`.
After the third failure it must atomically persist the first Track as `blocked`,
a fixed blocked target, and the product-safe reason `DailyTrack could not
process this Dataset Release.` while leaving its Head, Checkpoint count, and
Head publication unchanged.

Without editing or retrying the blocked Track, the test must then publish at
least one later direct-successor Dataset Release and prove that Data reports it
as latest and the second Track advances through both Releases in order. The
blocked Track must remain at its previous Head and original failed target; it
must create no Attempt for the later Release. Constructing a fresh Core runtime
must return the same blocked status, reason, Head, and target from PostgreSQL and
must not automatically claim the blocked Track. Attempt failure text must not
equal the public blocked reason, and neither the list nor detail response may
contain Attempt identifiers, ordinals, fences, claims, exception text, object
keys, manifests, or worker diagnostics.

The named browser test must render one blocked DailyTrack on its stable detail
URL with `Status blocked`, the sanitized readable reason, its unchanged Head,
and its existing analysis. It must also show the other Track at the latest
Release and the Data page at that Release, with no Retry control yet and no
internal execution mechanics.

## Comments

- The executable verification contract was specified in `8240a05` before the
  implementation. The first real PostgreSQL/RustFS TDD run failed because the
  affected Track remained `active` after its deterministic progression failure.
- Implemented in `c880cee`. DailyTracks owns the three-Attempt bound and the
  atomic Attempt/Progression/Track transition. The shared worker continues
  processing after one Track failure, while HTTP and Web expose only `blocked`,
  the unchanged Head, and the fixed product-safe reason.
- Real acceptance activates two Tracks, fails only one Track at one direct
  successor, proves exactly three failed Attempts and no failed-Track
  Checkpoint publication, then publishes a later Release. Data reaches latest
  and the other Track advances through both Releases while the blocked Track
  retains its Head and original failed target across a fresh Core runtime.
- The first independent review passed Standards but found one Spec P2: a third
  expired `WorkerLost` Attempt could create ordinal 4. A new restart red test
  reproduced it, and `58a8c4e` fixed both synchronous and expired-worker paths
  to use the same atomic `_block_progression` transition. Failure isolation,
  worker-loss Recovery, and architecture then reported `25 passed, 1 warning
  in 132.74s`.
- Independent re-review passed both Standards and Spec with no findings. It
  confirmed that the third expired Attempt is marked failed and blocked in one
  transaction, no fourth Attempt is inserted, module ownership remains intact,
  and no execution internals enter the product projection.
- Final verification was run exactly from **How to verify** against isolated
  real PostgreSQL and RustFS and passed: backend and architecture reported `22
  passed, 1 warning in 118.16s`; Web typecheck passed; the named browser test
  reported `1 passed in 4.4s`; the trap removed both runtime containers.
- Final repository verification passed with `make check`: Ruff passed; Pytest
  reported `533 passed, 105 skipped, 2 warnings in 1015.82s`; Web typecheck and
  production build passed (`1591` modules in `1.65s`); narrow E2E reported `1
  passed in 36.2s`; desktop E2E reported `1 passed in 1.0m`.
