# 33 — Block one failed DailyTrack independently

**What to build:** Move only the affected DailyTrack to blocked after its
automatic progression retries are exhausted while Data and other Tracks keep
working.

**Blocked by:** 28.

**Status:** ready-for-agent

- [ ] Exhausted automatic retry changes the affected Track to `blocked`, records
  a sanitized readable reason, and preserves its last successful Head.
- [ ] Its current failed target remains fixed even when newer Releases appear.
- [ ] Data continues to publish later Dataset Releases without waiting for the
  blocked Track.
- [ ] Other active DailyTracks continue to discover and advance successor
  Releases.
- [ ] Process restart preserves enough PostgreSQL and Publication truth to
  retry or stop the blocked Track.
- [ ] The Web shows blocked status and reason without exposing Attempt, claim,
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
