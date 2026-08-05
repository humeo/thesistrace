# 50 — Retry transient object response-stream reads

**What to build:** Keep standard-S3 publication reads deterministic when an
otherwise healthy object store terminates a response body before the declared
content length, without weakening immutable-object verification.

**Blocked by:** 48.

**Status:** ready-for-agent

- [ ] Publication retries transient response-stream failures at one shared
  object-read boundary used by both existing-object verification and committed
  publication reads.
- [ ] Retry is strictly bounded; exhaustion remains a typed
  `PublicationUnavailableError` for the owning product workflow to handle.
- [ ] Missing objects, non-transient S3 errors, wrong lengths, wrong checksums,
  and conflicting content-address bytes still fail immediately as verification
  errors.
- [ ] Every acquired response body is closed, including a body whose read
  raises a transient streaming exception.
- [ ] Integration tests prove first-read recovery on both public paths and
  bounded exhaustion without depending on a flaky RustFS response.

**How to verify:**

```sh
set -eu

uv run ruff check \
  src/thesistrace/publication/service.py \
  tests/integration/test_publication_bytes.py

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/integration/test_publication_bytes.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q \
    tests/acceptance/test_core_daily_track_cache_recovery.py \
    tests/acceptance/test_core_daily_track_equivalence.py
```

## Comments

- Discovered by Ticket 49's clean `make check`: RustFS twice returned an empty
  response stream for the same approximately 19.7 MiB content-addressed object,
  once during cache recovery and once during equivalence setup. Botocore raised
  `ResponseStreamingError` from `IncompleteRead`; Publication classified it as
  transient but did not retry the response-body read.
