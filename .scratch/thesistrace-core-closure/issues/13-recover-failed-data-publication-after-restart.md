# 13 — Recover failed Data publication after restart

**What to build:** Preserve the previous Data truth when collection or
publication fails, then recover durable update state safely after process loss.

**Blocked by:** 11.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Collection, upload, manifest, transaction, stale-worker, and verified-read
  failures expose no partial Dataset Release.
- [x] The previous latest Release remains authoritative after every failure.
- [x] An upload followed by rollback leaves only an invisible orphan.
- [x] Eligible abandoned work can resume after worker restart without duplicate
  Release publication.
- [x] Exhausted bounded retry records a sanitized `failed` outcome while a later
  Update may still be admitted.
- [x] Data overview correctly distinguishes `idle`, `updating`, and `failed`,
  includes the latest terminal outcome, and survives HTTP and worker restart.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/integration \
  tests/acceptance/test_core_fixture_data_update.py \
  tests/acceptance/test_core_later_data_update.py \
  tests/acceptance/test_core_no_change_data_update.py \
  tests/acceptance/test_core_data_recovery.py
./scripts/core-test-runtime down
```

The recovery suite must inject collection, upload/verification, manifest, and
PostgreSQL transaction failures; fence a stale worker; exhaust bounded retries;
and reopen fresh HTTP/worker runtimes between durable transitions. At every
seam it must assert that the prior latest Release remains authoritative and no
partial Release or visible Publication appears.

## Comments

- Data owns a three-Attempt retry bound. A non-final collection or publication
  failure marks only the Attempt failed, returns the receipt to `accepted`, and
  keeps overview `updating` while preserving the prior terminal outcome and
  latest Release. The third failure stores only the exception class and makes
  overview terminal `failed`.
- Every publication/no-change commit locks the Data head and verifies that its
  exact Attempt plus receipt are still `running`. Recovery marks stale running
  Attempts `WorkerLost` and either requeues or exhausts them; a late stale
  worker can neither publish nor change the winner's receipt during its own
  failure cleanup.
- The Core worker checks for Attempts older than its private 15-minute stale
  boundary before claiming accepted work. Fresh HTTP and worker runtimes read
  the same PostgreSQL receipt and head; no process-local recovery state exists.
- Failure injection covers provider collection, interrupted object upload,
  missing-object verification, manifest record, and rollback after Publication
  rows were written. All leave Release and visible Publication counts unchanged;
  uploaded content without a committed reference remains an invisible orphan.
- TDD red proved that the first provider exception previously terminalized the
  receipt. The bounded retry test turned green, and the full real
  PostgreSQL/RustFS recovery suite passed `7 passed, 1 warning` in `30.39s`.
