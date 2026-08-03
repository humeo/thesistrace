# 12 — Complete an idempotent no-change Data Update

**What to build:** Complete Data Update safely when no new completed Research
Session exists, while enforcing single active work and request replay rules.

**Blocked by:** 10.

**Status:** ready-for-agent

**Implementation:** complete

- [x] A source batch with no new completed Research Session produces the
  terminal `no_change` outcome and no Dataset Release or Publication.
- [x] PostgreSQL permits at most one active Data Update; concurrent admission
  cannot create duplicate collection work.
- [x] Repeating the same request ID, action, and fingerprint returns the first
  acceptance or terminal outcome without a new Attempt or Release.
- [x] Reusing a request ID with different input returns a conflict.
- [x] A structurally malformed Update request creates no receipt.
- [x] The Data page presents `no_change` as a successful terminal outcome and
  keeps the existing latest Release.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/adapters \
  tests/integration \
  tests/acceptance/test_core_fixture_data_update.py \
  tests/acceptance/test_core_later_data_update.py \
  tests/acceptance/test_core_no_change_data_update.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend suite must prove repeated, conflicting, malformed, and concurrent
Update requests plus an actual source no-change outcome. The browser must run a
third Update after the first and later Releases, show a successful no-change
message, retain the same latest Release, and keep Release history unchanged.

## Comments

- Fixture now represents a fixed available source horizon: Bootstrap publishes
  the fixed 756-session window, the first default incremental collection sees
  session 757, and a later collection against that same horizon returns the
  complete unchanged canonical batch instead of inventing session 758.
- Data validates that unchanged batch, then fences `latest_release_id` and
  atomically completes the Attempt, receipt, and overview as `no_change`.
  Publication preparation is never entered, so Release, manifest, and object
  counts remain unchanged.
- Receipt replay maps `accepted`/`running` back to `accepted` and returns the
  persisted `published`, `no_change`, or `failed` terminal status. PostgreSQL's
  partial unique index remains the single-active authority; the losing
  concurrent admissions return conflict and create no work.
- The HTTP adapter rejects missing/blank keys, invalid JSON, and body fields
  such as `source=fixture` before a receipt is created, and maps stored
  fingerprint mismatch to HTTP 409. Provider mode remains outside the product
  interface.
- TDD red reproduced Fixture growing from 757 to 758 on every call. The fixed
  adapter/validation suite passed `14` tests. Real PostgreSQL/RustFS acceptance
  passed `3` tests in `5.29s`; TypeScript and Core boundary tests passed; real
  browser acceptance passed in `21.0s` and retained exactly two Releases after
  the third Update reported no change.
